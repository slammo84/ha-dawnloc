# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

from . import __version__
from .locator import Locator
from .parser import parse_hearing_map
from .store import Store

LOGGER = logging.getLogger(__name__)
BASE_TOPIC = "dawnloc"
DISCOVERY_PREFIX = "homeassistant"


def _json_payload(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _optional_timestamp(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class MQTTWorker:
    def __init__(
        self,
        store: Store,
        locator: Locator,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        raw_topic: str,
    ) -> None:
        self.store = store
        self.locator = locator
        self.raw_topic = raw_topic
        self.host = host
        self.port = port
        self.connected = False
        self.stop_event = threading.Event()
        self.known_discovery_slugs: set[str] = set()
        self.maintenance_thread: threading.Thread | None = None

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="dawnloc-ha-app",
        )
        if username:
            self.client.username_pw_set(username, password)
        self.client.will_set(f"{BASE_TOPIC}/status", "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.stop_event.clear()
        self.client.connect_async(self.host, self.port, 60)
        self.client.loop_start()
        self.maintenance_thread = threading.Thread(
            target=self._maintenance_loop,
            name="dawnloc-maintenance",
            daemon=True,
        )
        self.maintenance_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.connected:
            self.client.publish(f"{BASE_TOPIC}/status", "offline", retain=True)
        self.client.disconnect()
        self.client.loop_stop()
        if self.maintenance_thread:
            self.maintenance_thread.join(timeout=3)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        LOGGER.info("Connected to MQTT broker %s:%s (%s)", self.host, self.port, reason_code)
        self.connected = True
        client.publish(f"{BASE_TOPIC}/status", "online", retain=True)
        client.subscribe(self.raw_topic)
        client.subscribe("homeassistant/status")
        self.sync_discovery()
        self.publish_all_states()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        self.connected = False
        if not self.stop_event.is_set():
            LOGGER.warning("Disconnected from MQTT broker (%s)", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        if message.topic == "homeassistant/status":
            if message.payload.decode(errors="ignore").strip() == "online":
                self.sync_discovery()
                self.publish_all_states()
            return

        if message.topic != self.raw_topic:
            return

        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            LOGGER.warning("Discarding invalid JSON received on %s", message.topic)
            return

        observations = parse_hearing_map(payload, self.locator.ap_last_seen.keys())
        if not observations:
            LOGGER.debug("DAWN payload contained no usable observations")

        clients = payload.get("clients")
        access_points = payload.get("access_points")
        self.locator.ingest(
            observations,
            generated_at=_optional_timestamp(payload.get("generated_at")),
            source_node=payload.get("node") if isinstance(payload.get("node"), str) else None,
            clients=clients if isinstance(clients, list) else None,
            access_points=access_points if isinstance(access_points, list) else None,
        )
        self.publish_all_states()

    def _maintenance_loop(self) -> None:
        while not self.stop_event.wait(2.0):
            self.locator.tick()
            if self.connected:
                self._process_cleanup()
                self.publish_all_states()

    @staticmethod
    def _device_registry(device: dict[str, Any]) -> dict[str, Any]:
        return {
            "identifiers": [f"dawnloc_{device['slug']}"],
            "name": device["name"],
            "manufacturer": "DAWNLoc",
            "model": "Wi-Fi room tracker",
            "sw_version": __version__,
            "connections": [["mac", device["mac"]]],
        }

    @staticmethod
    def _discovery_topics(slug: str, include_legacy: bool = True) -> list[str]:
        entities = [
            ("device_tracker", "tracker"),
            ("sensor", "room"),
            ("sensor", "instant_room"),
            ("sensor", "confidence"),
            ("sensor", "current_ap"),
            ("sensor", "current_channel"),
            ("sensor", "current_band"),
            ("sensor", "visible_aps"),
            ("sensor", "last_seen"),
        ]
        if include_legacy:
            entities.extend(
                [
                    ("sensor", "snapshot_time"),
                    ("button", "snapshot"),
                    ("sensor", "strongest_ap"),
                ]
            )
        return [
            f"{DISCOVERY_PREFIX}/{domain}/dawnloc_{slug}_{key}/config"
            for domain, key in entities
        ]

    def _clear_discovery(self, slug: str) -> None:
        for topic in self._discovery_topics(slug):
            self.client.publish(topic, "", retain=True)
        self.client.publish(f"{BASE_TOPIC}/device/{slug}/state", "", retain=True)

    def _process_cleanup(self) -> None:
        if not self.connected:
            return
        for stale_slug in self.store.list_cleanup_slugs():
            self._clear_discovery(stale_slug)
            self.store.clear_cleanup_slug(stale_slug)

    def sync_discovery(self) -> None:
        if not self.connected:
            return

        self._process_cleanup()
        devices = self.store.list_devices()
        current_slugs = {device["slug"] for device in devices}
        for stale_slug in self.known_discovery_slugs - current_slugs:
            self._clear_discovery(stale_slug)

        self.known_discovery_slugs = current_slugs
        for device in devices:
            self.publish_discovery(device)

    def remove_device(self, device: dict[str, Any]) -> None:
        slug = device["slug"]
        self.known_discovery_slugs.discard(slug)
        if not self.connected:
            return
        self._clear_discovery(slug)
        self.store.clear_cleanup_slug(slug)

    def publish_discovery(self, device: dict[str, Any]) -> None:
        slug = device["slug"]
        state_topic = f"{BASE_TOPIC}/device/{slug}/state"
        availability_topic = f"{BASE_TOPIC}/status"
        registry = self._device_registry(device)
        origin = {
            "name": "DAWNLoc",
            "sw_version": __version__,
            "support_url": "https://github.com/slammo84/ha-dawnloc",
        }

        for domain, key in (
            ("sensor", "snapshot_time"),
            ("button", "snapshot"),
            ("sensor", "strongest_ap"),
        ):
            self.client.publish(
                f"{DISCOVERY_PREFIX}/{domain}/dawnloc_{slug}_{key}/config",
                "",
                retain=True,
            )

        tracker = {
            "name": device["name"],
            "unique_id": f"dawnloc_{slug}_tracker",
            "default_entity_id": f"device_tracker.{slug}",
            "state_topic": state_topic,
            "value_template": "{{ value_json.presence }}",
            "json_attributes_topic": state_topic,
            "source_type": "router",
            "availability_topic": availability_topic,
            "device": registry,
            "origin": origin,
        }
        self.client.publish(
            f"{DISCOVERY_PREFIX}/device_tracker/dawnloc_{slug}_tracker/config",
            _json_payload(tracker),
            retain=True,
        )

        sensors: dict[str, dict[str, Any]] = {
            "room": {
                "name": "Raum",
                "value_template": "{{ value_json.room }}",
                "icon": "mdi:home-map-marker",
            },
            "instant_room": {
                "name": "Aktuelle Raumzuordnung",
                "value_template": "{{ value_json.instant_room }}",
                "icon": "mdi:map-marker-question",
                "entity_category": "diagnostic",
            },
            "confidence": {
                "name": "Ortungssicherheit",
                "value_template": "{{ value_json.confidence }}",
                "unit_of_measurement": "%",
                "icon": "mdi:signal",
                "entity_category": "diagnostic",
            },
            "current_ap": {
                "name": "Aktueller AP (geschätzt)",
                "value_template": "{{ value_json.current_ap }}",
                "icon": "mdi:access-point",
                "entity_category": "diagnostic",
            },
            "current_channel": {
                "name": "WLAN-Kanal",
                "value_template": "{{ value_json.current_channel }}",
                "icon": "mdi:radio-tower",
                "entity_category": "diagnostic",
            },
            "current_band": {
                "name": "Frequenzband",
                "value_template": "{{ value_json.current_band }}",
                "icon": "mdi:wifi",
                "entity_category": "diagnostic",
            },
            "visible_aps": {
                "name": "Sichtbare APs",
                "value_template": "{{ value_json.visible_aps }}",
                "icon": "mdi:access-point-network",
                "entity_category": "diagnostic",
            },
            "last_seen": {
                "name": "Zuletzt gesehen",
                "value_template": "{{ value_json.last_seen }}",
                "device_class": "timestamp",
                "entity_category": "diagnostic",
            },
        }

        for key, fields in sensors.items():
            config = {
                "unique_id": f"dawnloc_{slug}_{key}",
                "default_entity_id": f"sensor.{slug}_{key}",
                "state_topic": state_topic,
                "availability_topic": availability_topic,
                "device": registry,
                "origin": origin,
                **fields,
            }
            self.client.publish(
                f"{DISCOVERY_PREFIX}/sensor/dawnloc_{slug}_{key}/config",
                _json_payload(config),
                retain=True,
            )

    def _publish_device_state(self, device: dict[str, Any]) -> None:
        state = self.locator.classify(device["mac"])
        stable_room = state.get("stable_room")
        instant_room = state.get("instant_room")
        present = not state["offline"]
        room_known = bool(stable_room) and present
        room = stable_room if room_known else "Nicht geortet"

        payload = {
            "presence": "home" if present else "not_home",
            "location": "home" if present else "not_home",
            "room": room,
            "instant_room": instant_room or "Unbekannt",
            "confidence": state.get("confidence", 0.0),
            "current_ap": state.get("current_ap") or "Unbekannt",
            "current_channel": state.get("current_channel") or "Unbekannt",
            "current_band": state.get("current_band") or "Unbekannt",
            "current_frequency": state.get("current_frequency"),
            "current_bssid": state.get("current_bssid") or "",
            "current_ap_estimated": state.get("current_ap_estimated", False),
            "strongest_ap": state.get("current_ap") or "Unbekannt",
            "visible_aps": state.get("visible_aps", 0),
            "visible_bssids": state.get("visible_bssids", 0),
            "last_seen": state.get("last_seen_iso") or "",
            "hostname": state.get("hostname") or "",
            "ip_address": state.get("ip_address") or "",
            "mac_address": device["mac"],
            "offline": state["offline"],
            "located": room_known,
            "instant_located": state.get("located", False),
            "room_held": state.get("room_held", False),
            "age_seconds": state.get("age_seconds"),
            "score": state.get("score"),
            "shared_aps": state.get("shared_aps"),
            "coverage": state.get("coverage"),
            "rssi": state.get("vector"),
            "method": state.get("method"),
        }
        self.client.publish(
            f"{BASE_TOPIC}/device/{device['slug']}/state",
            _json_payload(payload),
            retain=True,
        )

    def publish_device_state(self, device: dict[str, Any]) -> None:
        if not self.connected:
            return
        self.locator.tick()
        self._publish_device_state(device)

    def publish_all_states(self) -> None:
        if not self.connected:
            return
        self.locator.tick()
        for device in self.store.list_devices():
            self._publish_device_state(device)
