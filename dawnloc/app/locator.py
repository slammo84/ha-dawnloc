# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import math
import statistics
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .parser import Observation, is_mac, normalize_mac
from .store import Store

SignalVector = dict[str, float]
FEATURE_PREFIX = "ap:"
MAX_RSSI_DELTA = 32.0
MISSING_FEATURE_PENALTY = 14.0
SCORE_DECAY = 13.0
SEPARATION_TARGET = 8.0
MAX_ACCEPTED_SCORE = 24.0
MIN_ACCEPTED_COVERAGE = 0.45
MIN_ACCEPTED_CONFIDENCE = 55.0
MIN_ROOM_GAP = 1.5
NEIGHBOURS_PER_ROOM = 3
MIN_CALIBRATION_SAMPLES = 2


def band_from_frequency(value: Any) -> str:
    try:
        frequency = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if 2400 <= frequency < 2500:
        return "2.4 GHz"
    if 4900 <= frequency < 5900:
        return "5 GHz"
    if 5925 <= frequency < 7125:
        return "6 GHz"
    return "unknown"


def normalize_band(value: Any) -> str:
    text = str(value or "unknown").strip()
    lowered = text.lower().replace(" ", "")
    if lowered in {"2.4", "2.4ghz", "2g", "2ghz"}:
        return "2.4 GHz"
    if lowered in {"5", "5ghz", "5g"}:
        return "5 GHz"
    if lowered in {"6", "6ghz", "6g"}:
        return "6 GHz"
    return text if text else "unknown"


def channel_from_frequency(value: Any) -> int | None:
    try:
        frequency = int(float(value))
    except (TypeError, ValueError):
        return None
    if frequency == 2484:
        return 14
    if 2412 <= frequency <= 2472:
        return (frequency - 2407) // 5
    if 5000 <= frequency < 5925:
        return (frequency - 5000) // 5
    if 5955 <= frequency <= 7115:
        return (frequency - 5950) // 5
    return None


@dataclass
class CalibrationSession:
    id: str
    device_mac: str
    room_slug: str
    started_at: float
    ends_at: float
    samples: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    status: str = "running"
    fingerprint_id: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class Match:
    score: float
    shared_aps: int
    coverage: float
    shared_features: int


@dataclass(frozen=True)
class RoomMatch:
    score: float
    shared_aps: int
    coverage: float
    support: int


class Locator:
    def __init__(
        self,
        store: Store,
        ttl_seconds: int = 20,
        offline_after: int = 60,
        stable_seconds: int = 5,
        sample_window: int = 7,
        min_shared_aps: int = 2,
        room_hold_seconds: int = 60,
        switch_confidence: float = 70.0,
    ) -> None:
        self.store = store
        self.ttl = ttl_seconds
        self.offline_after = offline_after
        self.stable_seconds = stable_seconds
        self.sample_window = sample_window
        self.min_shared_aps = max(2, min_shared_aps)
        self.room_hold_seconds = max(0, room_hold_seconds)
        self.switch_confidence = max(0.0, min(float(switch_confidence), 100.0))
        self.lock = threading.RLock()
        self.history: dict[str, dict[str, deque[tuple[float, float]]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self.sample_window))
        )
        self.client_last_seen: dict[str, float] = {}
        self.ap_last_seen: dict[str, float] = {}
        self.client_ssids: dict[str, set[str]] = defaultdict(set)
        self.client_metadata: dict[str, dict[str, str]] = {}
        self.ap_metadata: dict[str, dict[str, Any]] = {}
        self.client_associations: dict[str, dict[str, Any]] = {}
        self.source_associations: dict[str, set[str]] = defaultdict(set)
        self.feature_labels: dict[str, str] = {}
        self.sessions: dict[str, CalibrationSession] = {}
        self.stable_room_slug: dict[str, str | None] = {}
        self.candidate_room_slug: dict[str, str | None] = {}
        self.candidate_since: dict[str, float] = {}
        self.last_room_fix: dict[str, float] = {}
        self.last_raw_message: float | None = None
        self.source_node: str | None = None

    def ingest(
        self,
        observations: list[Observation],
        generated_at: float | None = None,
        source_node: str | None = None,
        clients: list[dict[str, Any]] | None = None,
        access_points: list[dict[str, Any]] | None = None,
        associations: list[dict[str, Any]] | None = None,
    ) -> None:
        now = time.time()
        with self.lock:
            self.last_raw_message = generated_at if generated_at is not None else now
            if source_node:
                self.source_node = source_node
            self._ingest_client_metadata(clients or [])
            self._ingest_ap_metadata(access_points or [], source_node, now)
            self._ingest_associations(associations or [], source_node, now)
            for observation in observations:
                client = normalize_mac(observation.client)
                bssid = normalize_mac(observation.bssid)
                self.history[client][bssid].append((now, observation.rssi))
                self.client_last_seen[client] = now
                self.ap_last_seen[bssid] = now
                if observation.ssid:
                    self.client_ssids[client].add(observation.ssid)
                frequency = observation.metadata.get("freq")
                if frequency is not None:
                    metadata = self.ap_metadata.setdefault(bssid, {})
                    metadata.setdefault("band", band_from_frequency(frequency))
                    metadata.setdefault("frequency", frequency)
                    self._remember_feature(bssid)
                if observation.ssid:
                    metadata = self.ap_metadata.setdefault(bssid, {})
                    ssids = set(metadata.get("ssids", []))
                    ssids.add(observation.ssid)
                    metadata["ssids"] = sorted(ssids)
                for session in self.sessions.values():
                    if (
                        session.status == "running"
                        and session.device_mac == client
                        and now <= session.ends_at
                    ):
                        session.samples[bssid].append(observation.rssi)
            self._finalize_due(now)
            self._update_all_stable(now)

    def _ingest_associations(
        self,
        associations: list[dict[str, Any]],
        source_node: str | None,
        now: float,
    ) -> None:
        source_key = source_node.strip().casefold() if isinstance(source_node, str) else ""
        current_macs: set[str] = set()
        for item in associations:
            mac = item.get("mac")
            bssid = item.get("bssid")
            if not isinstance(mac, str) or not is_mac(mac):
                continue
            if not isinstance(bssid, str) or not is_mac(bssid):
                continue
            mac = normalize_mac(mac)
            bssid = normalize_mac(bssid)
            frequency = item.get("frequency") or item.get("freq")
            try:
                frequency = int(float(frequency)) if frequency is not None else None
            except (TypeError, ValueError):
                frequency = None
            channel = item.get("channel")
            try:
                channel = int(float(channel)) if channel is not None else None
            except (TypeError, ValueError):
                channel = None
            if channel is None:
                channel = channel_from_frequency(frequency)
            hostname = item.get("hostname") or source_node
            metadata = self.ap_metadata.setdefault(bssid, {})
            if isinstance(hostname, str) and hostname.strip():
                metadata["hostname"] = hostname.strip()
            band = normalize_band(item.get("band") or metadata.get("band"))
            if band == "unknown" and frequency is not None:
                band = band_from_frequency(frequency)
            if band != "unknown":
                metadata["band"] = band
            if frequency is not None:
                metadata["frequency"] = frequency
            if channel is not None:
                metadata["channel"] = channel
            metadata["last_metadata"] = now
            self.ap_last_seen[bssid] = now
            self._remember_feature(bssid)
            signal = item.get("signal")
            try:
                signal = round(float(signal), 1) if signal is not None else None
            except (TypeError, ValueError):
                signal = None
            self.client_associations[mac] = {
                "bssid": bssid,
                "hostname": metadata.get("hostname"),
                "frequency": frequency,
                "channel": channel,
                "band": band if band != "unknown" else None,
                "signal": signal,
                "source_node": source_key,
                "last_seen": now,
            }
            self.client_last_seen[mac] = now
            current_macs.add(mac)
        if source_key:
            previous_macs = self.source_associations.get(source_key, set())
            for mac in previous_macs - current_macs:
                association = self.client_associations.get(mac)
                if association and association.get("source_node") == source_key:
                    self.client_associations.pop(mac, None)
            self.source_associations[source_key] = current_macs

    def _ingest_client_metadata(self, clients: list[dict[str, Any]]) -> None:
        for item in clients:
            mac = item.get("mac")
            if not isinstance(mac, str):
                continue
            mac = normalize_mac(mac)
            metadata = self.client_metadata.setdefault(mac, {})
            hostname = item.get("hostname")
            ip_address = item.get("ip") or item.get("ip_address")
            if isinstance(hostname, str) and hostname and hostname != "*":
                metadata["hostname"] = hostname
            if isinstance(ip_address, str) and ip_address:
                metadata["ip_address"] = ip_address

    def _ingest_ap_metadata(
        self,
        access_points: list[dict[str, Any]],
        source_node: str | None,
        now: float,
    ) -> None:
        for item in access_points:
            bssid = item.get("bssid")
            if not isinstance(bssid, str):
                continue
            bssid = normalize_mac(bssid)
            metadata = self.ap_metadata.setdefault(bssid, {})
            hostname = item.get("hostname") or source_node
            if isinstance(hostname, str) and hostname.strip():
                metadata["hostname"] = hostname.strip()
            band = item.get("band")
            frequency = item.get("frequency") or item.get("freq")
            if isinstance(band, str) and band:
                metadata["band"] = normalize_band(band)
            elif frequency is not None:
                metadata["band"] = band_from_frequency(frequency)
            if frequency is not None:
                metadata["frequency"] = frequency
            channel = item.get("channel")
            if channel is not None:
                metadata["channel"] = channel
            ssid = item.get("ssid")
            if isinstance(ssid, str) and ssid:
                ssids = set(metadata.get("ssids", []))
                ssids.add(ssid)
                metadata["ssids"] = sorted(ssids)
            metadata["last_metadata"] = now
            self.ap_last_seen[bssid] = now
            self._remember_feature(bssid)

    def _remember_feature(self, bssid: str) -> None:
        feature = self._feature_for_bssid(bssid)
        if feature is None:
            return
        metadata = self.ap_metadata[bssid]
        hostname = str(metadata["hostname"]).strip()
        band = normalize_band(metadata["band"])
        self.feature_labels[feature] = f"{hostname} · {band}"

    def tick(self) -> None:
        now = time.time()
        with self.lock:
            self._finalize_due(now)
            self._update_all_stable(now)

    def filtered_bssid_vector(self, device_mac: str, now: float | None = None) -> SignalVector:
        now = now or time.time()
        device_mac = normalize_mac(device_mac)
        vector: SignalVector = {}
        with self.lock:
            for bssid, samples in self.history.get(device_mac, {}).items():
                values = [rssi for timestamp, rssi in samples if now - timestamp <= self.ttl]
                if values:
                    vector[bssid] = round(float(statistics.median(values)), 1)
        return vector

    def filtered_vector(self, device_mac: str, now: float | None = None) -> SignalVector:
        return self._group_vector(self.filtered_bssid_vector(device_mac, now))

    def _feature_for_bssid(self, bssid: str) -> str | None:
        metadata = self.ap_metadata.get(normalize_mac(bssid), {})
        hostname = metadata.get("hostname")
        band = normalize_band(metadata.get("band"))
        if not isinstance(hostname, str) or not hostname.strip() or band == "unknown":
            return None
        return f"{FEATURE_PREFIX}{hostname.strip().casefold()}|{band.casefold()}"

    @staticmethod
    def _feature_host(feature: str) -> str | None:
        if not feature.startswith(FEATURE_PREFIX):
            return None
        value = feature[len(FEATURE_PREFIX) :]
        hostname, separator, _band = value.partition("|")
        return hostname if separator and hostname else None

    def _group_vector(self, vector: SignalVector) -> SignalVector:
        grouped: dict[str, list[float]] = defaultdict(list)
        for key, rssi in vector.items():
            if key.startswith(FEATURE_PREFIX):
                grouped[key].append(float(rssi))
                continue
            if not is_mac(key):
                continue
            feature = self._feature_for_bssid(key)
            if feature is not None:
                grouped[feature].append(float(rssi))
        return {
            feature: round(float(statistics.median(values)), 1)
            for feature, values in grouped.items()
            if values
        }

    def _group_samples(
        self, samples: dict[str, list[float]]
    ) -> tuple[SignalVector, dict[str, int]]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for bssid, values in samples.items():
            feature = self._feature_for_bssid(bssid)
            if feature is not None:
                grouped[feature].extend(values)
        usable = {
            feature: values
            for feature, values in grouped.items()
            if len(values) >= MIN_CALIBRATION_SAMPLES
        }
        vector = {
            feature: round(float(statistics.median(values)), 1)
            for feature, values in usable.items()
        }
        counts = {feature: len(values) for feature, values in usable.items()}
        return vector, counts

    def _visible_ap_count(self, vector: SignalVector) -> int:
        hosts = {self._feature_host(feature) for feature in vector}
        hosts.discard(None)
        return len(hosts)

    def _feature_label(self, feature: str) -> str:
        label = self.feature_labels.get(feature)
        if label:
            return label
        if not feature.startswith(FEATURE_PREFIX):
            return feature
        value = feature[len(FEATURE_PREFIX) :]
        hostname, separator, band = value.partition("|")
        if not separator:
            return value
        return f"{hostname} · {normalize_band(band)}"

    def _display_vector(self, vector: SignalVector) -> SignalVector:
        ordered = sorted(
            vector.items(),
            key=lambda item: self._feature_label(item[0]),
        )
        return {self._feature_label(feature): rssi for feature, rssi in ordered}

    def _current_connection(self, device_mac: str, now: float) -> dict[str, Any]:
        association = self.client_associations.get(normalize_mac(device_mac))
        if not association or now - float(association.get("last_seen", 0)) > self.ttl:
            return {
                "current_ap": None,
                "current_bssid": None,
                "current_channel": None,
                "current_frequency": None,
                "current_band": None,
                "current_ap_estimated": False,
            }
        return {
            "current_ap": association.get("hostname"),
            "current_bssid": association.get("bssid"),
            "current_channel": association.get("channel"),
            "current_frequency": association.get("frequency"),
            "current_band": association.get("band"),
            "current_ap_estimated": False,
        }

    def _strongest_ap(self, raw_vector: SignalVector) -> str | None:
        if not raw_vector:
            return None
        bssid = max(raw_vector, key=raw_vector.get)
        metadata = self.ap_metadata.get(bssid, {})
        hostname = metadata.get("hostname")
        return hostname if isinstance(hostname, str) and hostname else None

    def _fingerprint_score(self, current: SignalVector, fingerprint: SignalVector) -> Match:
        reference = self._group_vector(fingerprint)
        shared = set(current) & set(reference)
        if not shared:
            return Match(math.inf, 0, 0.0, 0)
        shared_hosts = {self._feature_host(feature) for feature in shared}
        shared_hosts.discard(None)
        if len(shared_hosts) < self.min_shared_aps:
            return Match(math.inf, len(shared_hosts), 0.0, len(shared))
        errors_by_ap: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for feature in shared:
            current_rssi = current[feature]
            reference_rssi = reference[feature]
            delta = min(abs(current_rssi - reference_rssi), MAX_RSSI_DELTA)
            strongest = max(current_rssi, reference_rssi)
            strength = max(0.0, min(1.0, (strongest + 95.0) / 45.0))
            weight = 0.65 + 0.85 * strength
            hostname = self._feature_host(feature)
            if hostname is not None:
                errors_by_ap[hostname].append((weight, delta * delta))
        ap_errors = []
        for values in errors_by_ap.values():
            total_weight = sum(weight for weight, _error in values)
            ap_errors.append(
                sum(weight * error for weight, error in values) / max(total_weight, 1e-9)
            )
        rmse = math.sqrt(sum(ap_errors) / max(len(ap_errors), 1))
        current_hosts = {self._feature_host(feature) for feature in current}
        reference_hosts = {self._feature_host(feature) for feature in reference}
        current_hosts.discard(None)
        reference_hosts.discard(None)
        host_union = current_hosts | reference_hosts
        host_coverage = len(shared_hosts) / max(len(host_union), 1)
        feature_union = set(current) | set(reference)
        feature_coverage = len(shared) / max(len(feature_union), 1)
        coverage = 0.7 * host_coverage + 0.3 * feature_coverage
        score = rmse + (1.0 - coverage) * MISSING_FEATURE_PENALTY
        return Match(score, len(shared_hosts), coverage, len(shared))

    @staticmethod
    def _combine_room_matches(matches: list[Match]) -> RoomMatch:
        selected = sorted(matches, key=lambda item: item.score)[:NEIGHBOURS_PER_ROOM]
        weights = [1.0 / max(match.score, 0.5) ** 2 for match in selected]
        total = sum(weights)
        pairs = list(zip(selected, weights, strict=True))
        score = sum(match.score * weight for match, weight in pairs) / total
        coverage = sum(match.coverage * weight for match, weight in pairs) / total
        shared_aps = max(match.shared_aps for match in selected)
        return RoomMatch(score, shared_aps, coverage, len(selected))

    def _room_matches(self, device_mac: str, vector: SignalVector) -> dict[str, RoomMatch]:
        grouped: dict[str, list[Match]] = defaultdict(list)
        for fingerprint in self.store.list_fingerprints(device_mac):
            match = self._fingerprint_score(vector, fingerprint["vector"])
            if math.isfinite(match.score):
                grouped[fingerprint["room_slug"]].append(match)
        return {
            room_slug: self._combine_room_matches(matches)
            for room_slug, matches in grouped.items()
            if matches
        }

    def _confidence(
        self,
        best: RoomMatch,
        second: RoomMatch | None,
    ) -> tuple[float, float]:
        gap = max(0.0, second.score - best.score) if second else SEPARATION_TARGET * 0.7
        quality = math.exp(-best.score / SCORE_DECAY)
        separation = min(1.0, gap / SEPARATION_TARGET)
        ap_factor = min(1.0, best.shared_aps / max(3, self.min_shared_aps))
        support = min(1.0, best.support / 2.0)
        confidence = 100.0 * (
            0.44 * quality
            + 0.24 * separation
            + 0.18 * best.coverage
            + 0.09 * ap_factor
            + 0.05 * support
        )
        return max(0.0, min(confidence, 100.0)), gap

    def classify(self, device_mac: str, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        device_mac = normalize_mac(device_mac)
        raw_vector = self.filtered_bssid_vector(device_mac, now)
        vector = self._group_vector(raw_vector)
        visible_aps = self._visible_ap_count(vector)
        last_seen = self.client_last_seen.get(device_mac)
        offline = last_seen is None or now - last_seen > self.offline_after
        room_names = self.store.room_names()
        stable_slug = self.stable_room_slug.get(device_mac)
        metadata = self.client_metadata.get(device_mac, {})
        connection = self._current_connection(device_mac, now)
        result: dict[str, Any] = {
            "device_mac": device_mac,
            "hostname": metadata.get("hostname"),
            "ip_address": metadata.get("ip_address"),
            "offline": offline,
            "located": False,
            "room_held": bool(stable_slug and not offline),
            "last_seen": last_seen,
            "last_seen_iso": (
                datetime.fromtimestamp(last_seen, UTC).isoformat() if last_seen else None
            ),
            "age_seconds": round(now - last_seen, 1) if last_seen else None,
            "vector": self._display_vector(vector),
            "vector_raw": raw_vector,
            "visible_aps": visible_aps,
            "visible_radios": len(vector),
            "visible_bssids": len(raw_vector),
            "strongest_ap": self._strongest_ap(raw_vector),
            "instant_room": None,
            "instant_room_slug": None,
            "stable_room": room_names.get(stable_slug, stable_slug),
            "stable_room_slug": stable_slug,
            "confidence": 0.0,
            "score": None,
            "second_score": None,
            "shared_aps": 0,
            "coverage": 0.0,
            "method": "fingerprint_knn",
            **connection,
        }
        if offline or visible_aps < self.min_shared_aps:
            return result
        matches = self._room_matches(device_mac, vector)
        if not matches:
            return result
        ranked = sorted(matches.items(), key=lambda item: item[1].score)
        best_slug, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else None
        confidence, gap = self._confidence(best, second)
        accepted = (
            best.score <= MAX_ACCEPTED_SCORE
            and best.coverage >= MIN_ACCEPTED_COVERAGE
            and confidence >= MIN_ACCEPTED_CONFIDENCE
            and (second is None or gap >= MIN_ROOM_GAP)
        )
        result.update(
            {
                "located": accepted,
                "confidence": round(confidence, 1),
                "score": round(best.score, 2),
                "second_score": round(second.score, 2) if second else None,
                "shared_aps": best.shared_aps,
                "coverage": round(best.coverage, 3),
            }
        )
        if accepted:
            result["instant_room"] = room_names.get(best_slug, best_slug)
            result["instant_room_slug"] = best_slug
            result["room_held"] = bool(stable_slug and stable_slug != best_slug)
        return result

    def _reset_candidate(self, device_mac: str) -> None:
        self.candidate_room_slug.pop(device_mac, None)
        self.candidate_since.pop(device_mac, None)

    def _clear_room(self, device_mac: str) -> None:
        self.stable_room_slug.pop(device_mac, None)
        self.last_room_fix.pop(device_mac, None)
        self._reset_candidate(device_mac)

    def _room_hold_expired(self, device_mac: str, now: float) -> bool:
        last_fix = self.last_room_fix.get(device_mac)
        return last_fix is None or now - last_fix >= self.room_hold_seconds

    def _update_all_stable(self, now: float) -> None:
        for device in self.store.list_devices():
            mac = device["mac"]
            result = self.classify(mac, now)
            stable = self.stable_room_slug.get(mac)
            if result["offline"]:
                self._clear_room(mac)
                continue
            visible_aps = int(result.get("visible_aps") or 0)
            if visible_aps == 1:
                self._reset_candidate(mac)
                continue
            candidate = result.get("instant_room_slug") if result.get("located") else None
            if candidate is None:
                self._reset_candidate(mac)
                if stable and self._room_hold_expired(mac, now):
                    self._clear_room(mac)
                continue
            confidence = float(result.get("confidence") or 0.0)
            if candidate == stable:
                self.last_room_fix[mac] = now
                self._reset_candidate(mac)
                continue
            required_confidence = (
                MIN_ACCEPTED_CONFIDENCE if stable is None else self.switch_confidence
            )
            if confidence < required_confidence:
                self._reset_candidate(mac)
                if stable and self._room_hold_expired(mac, now):
                    self._clear_room(mac)
                continue
            current_candidate = self.candidate_room_slug.get(mac)
            if current_candidate != candidate:
                self.candidate_room_slug[mac] = candidate
                self.candidate_since[mac] = now
                if self.stable_seconds == 0:
                    self.stable_room_slug[mac] = candidate
                    self.last_room_fix[mac] = now
                    self._reset_candidate(mac)
                continue
            if now - self.candidate_since.get(mac, now) >= self.stable_seconds:
                self.stable_room_slug[mac] = candidate
                self.last_room_fix[mac] = now
                self._reset_candidate(mac)

    def list_states(self) -> list[dict[str, Any]]:
        states = []
        now = time.time()
        with self.lock:
            self._update_all_stable(now)
            for device in self.store.list_devices():
                state = self.classify(device["mac"], now)
                state["name"] = device["name"]
                state["slug"] = device["slug"]
                states.append(state)
        return states

    def discovered(self) -> dict[str, Any]:
        now = time.time()
        with self.lock:
            clients = []
            for mac, timestamp in sorted(
                self.client_last_seen.items(), key=lambda item: item[1], reverse=True
            ):
                raw_vector = self.filtered_bssid_vector(mac, now)
                vector = self._group_vector(raw_vector)
                visible_aps = self._visible_ap_count(vector)
                metadata = self.client_metadata.get(mac, {})
                clients.append(
                    {
                        "mac": mac,
                        "hostname": metadata.get("hostname"),
                        "ip_address": metadata.get("ip_address"),
                        "last_seen": timestamp,
                        "age_seconds": round(now - timestamp, 1),
                        "ssids": sorted(self.client_ssids.get(mac, set())),
                        "visible_aps": visible_aps,
                        "visible_radios": len(vector),
                        "visible_bssids": len(raw_vector),
                        "locatable": visible_aps >= max(2, self.min_shared_aps),
                    }
                )
            grouped: dict[tuple[str, str], dict[str, Any]] = {}
            for bssid, timestamp in self.ap_last_seen.items():
                metadata = self.ap_metadata.get(bssid, {})
                hostname = str(metadata.get("hostname") or "").strip()
                if not hostname:
                    continue
                band = normalize_band(metadata.get("band"))
                if band == "unknown":
                    continue
                group_key = (hostname.casefold(), band)
                current = grouped.setdefault(
                    group_key,
                    {
                        "hostname": hostname,
                        "band": band,
                        "bssid": bssid,
                        "last_seen": timestamp,
                        "ssids": [],
                        "bssids": set(),
                    },
                )
                current["bssids"].add(bssid)
                current["ssids"] = sorted(
                    set(current.get("ssids", [])) | set(metadata.get("ssids", []))
                )
                if timestamp >= current["last_seen"]:
                    current["last_seen"] = timestamp
                    current["bssid"] = bssid
            access_points = []
            for item in sorted(
                grouped.values(),
                key=lambda entry: (str(entry["hostname"]).casefold(), str(entry["band"])),
            ):
                item["age_seconds"] = round(now - item["last_seen"], 1)
                item["bssid_count"] = len(item.pop("bssids"))
                access_points.append(item)
        return {"clients": clients, "access_points": access_points}

    def start_calibration(
        self,
        device_mac: str,
        room_slug: str,
        duration: int,
    ) -> CalibrationSession:
        device_mac = normalize_mac(device_mac)
        if not self.store.get_device(device_mac):
            raise ValueError("errors.device_not_configured")
        if room_slug not in self.store.room_names():
            raise ValueError("errors.room_not_configured")
        now = time.time()
        session = CalibrationSession(
            id=uuid.uuid4().hex,
            device_mac=device_mac,
            room_slug=room_slug,
            started_at=now,
            ends_at=now + max(5, min(duration, 120)),
        )
        with self.lock:
            self.sessions[session.id] = session
        return session

    def _finalize_due(self, now: float) -> None:
        for session in self.sessions.values():
            if session.status != "running" or now < session.ends_at:
                continue
            vector, counts = self._group_samples(session.samples)
            sample_count = sum(counts.values())
            if not vector:
                session.status = "failed"
                session.error = "errors.no_observations"
                continue
            if self._visible_ap_count(vector) < self.min_shared_aps:
                session.status = "failed"
                session.error = "errors.not_enough_access_points"
                continue
            session.fingerprint_id = self.store.add_fingerprint(
                session.device_mac,
                session.room_slug,
                vector,
                sample_count,
            )
            session.status = "complete"

    def calibration_status(self, session_id: str) -> dict[str, Any] | None:
        self.tick()
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                return None
            now = time.time()
            vector, counts = self._group_samples(session.samples)
            return {
                "id": session.id,
                "device_mac": session.device_mac,
                "room_slug": session.room_slug,
                "started_at": session.started_at,
                "ends_at": session.ends_at,
                "remaining_seconds": max(0, round(session.ends_at - now, 1)),
                "status": session.status,
                "sample_count": sum(counts.values()),
                "ap_count": self._visible_ap_count(vector),
                "fingerprint_id": session.fingerprint_id,
                "error": session.error,
            }
