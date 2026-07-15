# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
METRIC_KEYS = {"signal", "rssi", "signal_dbm", "rcpi", "rsni"}
CLIENT_KEYS = {"client", "client_addr", "client_address", "sta", "station", "address", "mac"}
BSSID_KEYS = {"bssid", "ap", "ap_bssid"}
SSID_KEYS = {"ssid"}
UINT32_WRAP = 4_294_967_296
INT32_MAX = 2_147_483_647


def normalize_mac(value: str) -> str:
    return value.strip().lower()


def is_mac(value: Any) -> bool:
    return isinstance(value, str) and bool(MAC_RE.fullmatch(value.strip()))


def _signed_32(value: int | float) -> float:
    number = float(value)
    if number > INT32_MAX:
        number -= UINT32_WRAP
    return number


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _extract_rssi(node: dict[str, Any]) -> tuple[float | None, str]:
    for key in ("signal", "rssi", "signal_dbm"):
        value = _to_number(node.get(key))
        if value is None:
            continue
        value = _signed_32(value)
        if -127 <= value <= 0:
            return value, key

    rcpi = _to_number(node.get("rcpi"))
    if rcpi is not None and 0 < rcpi <= 220:
        return (rcpi / 2.0) - 110.0, "rcpi"

    return None, "unknown"


@dataclass(frozen=True)
class Observation:
    client: str
    bssid: str
    rssi: float
    ssid: str | None = None
    source: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)


def _first_mac_field(node: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = node.get(key)
        if is_mac(value):
            return normalize_mac(value)
    return None


def parse_hearing_map(
    payload: dict[str, Any],
    known_bssids: Iterable[str] = (),
) -> list[Observation]:

    known = {normalize_mac(mac) for mac in known_bssids}
    observations: dict[tuple[str, str], Observation] = {}
    root = payload.get("hearing_map", payload)

    def walk(node: Any, path: list[str], inherited_ssid: str | None = None) -> None:
        if not isinstance(node, dict):
            return

        ssid = inherited_ssid
        explicit_ssid = node.get("ssid")
        if isinstance(explicit_ssid, str) and explicit_ssid:
            ssid = explicit_ssid

        path_macs = [normalize_mac(part) for part in path if is_mac(part)]
        bssid = _first_mac_field(node, BSSID_KEYS)
        client = _first_mac_field(node, CLIENT_KEYS)

        if bssid is None and known:
            bssid = next((mac for mac in reversed(path_macs) if mac in known), None)

        if bssid is None and len(path_macs) >= 2:
            bssid = path_macs[-1]
        if client is None and bssid is not None:
            client = next((mac for mac in reversed(path_macs[:-1]) if mac != bssid), None)
        if client is None and len(path_macs) >= 2:
            client = path_macs[-2]
        if bssid is None and client is not None:
            bssid = next((mac for mac in reversed(path_macs) if mac != client), None)
        if client == bssid:
            client = None

        rssi, source = _extract_rssi(node)
        if client and bssid and rssi is not None:
            observation = Observation(
                client=client,
                bssid=bssid,
                rssi=round(rssi, 1),
                ssid=ssid,
                source=source,
                metadata={
                    key: value
                    for key, value in node.items()
                    if key in METRIC_KEYS or key in {"freq", "counter"}
                },
            )
            observation_key = (client, bssid)
            previous = observations.get(observation_key)
            prefer_new = previous is None or (
                previous.source == "rcpi" and source != "rcpi"
            ) or rssi > previous.rssi
            if prefer_new:
                observations[observation_key] = observation

        ignored_keys = METRIC_KEYS | CLIENT_KEYS | BSSID_KEYS | SSID_KEYS
        for key, value in node.items():
            if key in ignored_keys:
                continue
            next_ssid = ssid
            if (
                not path
                and not is_mac(key)
                and isinstance(value, dict)
                and key not in {"data", "result"}
            ):
                next_ssid = key
            walk(value, [*path, str(key)], next_ssid)

    walk(root, [])
    return list(observations.values())
