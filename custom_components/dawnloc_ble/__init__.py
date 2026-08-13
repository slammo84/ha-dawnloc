from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import bluetooth, mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.yaml import load_yaml

from .const import CONF_TOPIC, DEFAULT_TOPIC

PUBLISH_INTERVAL = 10.0
RSSI_CHANGE_THRESHOLD = 4
MAX_IDENTITIES = 200
CONTEXT_TOPIC = "dawnloc/raw/context"
CONTEXT_CONFIG_FILE = "dawnloc_context.yaml"
LOGGER = logging.getLogger(__name__)


def _context_rules(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("sensors"), dict):
        return {}
    rules: dict[str, dict[str, Any]] = {}

    def number(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    for entity_id, value in raw["sensors"].items():
        if not isinstance(entity_id, str) or not isinstance(value, dict):
            continue
        role = value.get("role")
        if role not in {"room", "transition"}:
            continue
        rule = {
            "role": role,
            "active_state": str(value.get("active_state") or "on"),
            "max_age": number(value.get("max_age"), 20, 1, 300),
        }
        if role == "room" and isinstance(value.get("room"), str):
            rule["room"] = value["room"]
            rule["weight"] = number(value.get("weight"), 15, 1, 40)
            requires = value.get("requires")
            if isinstance(requires, list):
                rule["requires"] = [item for item in requires if isinstance(item, str)]
        elif role == "transition":
            rule["switch_seconds"] = number(value.get("switch_seconds"), 8, 0, 60)
        else:
            continue
        rules[entity_id] = rule
    return rules


def _ibeacon_identity(manufacturer_data: dict[int, bytes]) -> str | None:
    data = manufacturer_data.get(76)
    if not data or len(data) < 23 or data[:2] != b"\x02\x15":
        return None
    hexed = data[2:18].hex()
    uuid = f"{hexed[:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:]}"
    major = int.from_bytes(data[18:20], "big")
    minor = int.from_bytes(data[20:22], "big")
    return f"ibeacon:{uuid}:{major}:{minor}"


def _identity(service_info: bluetooth.BluetoothServiceInfoBleak) -> tuple[str, str] | None:
    ibeacon = _ibeacon_identity(service_info.manufacturer_data)
    return (ibeacon, "ibeacon") if ibeacon else None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await mqtt.async_wait_for_mqtt_client(hass)
    topic = entry.data.get(CONF_TOPIC, DEFAULT_TOPIC)
    known: dict[str, bluetooth.BluetoothServiceInfoBleak] = {}
    last_published: dict[str, tuple[float, tuple[tuple[str, int], ...]]] = {}
    context_path = hass.config.path(CONTEXT_CONFIG_FILE)
    try:
        context_config = await hass.async_add_executor_job(load_yaml, context_path)
    except (OSError, ValueError):
        context_config = {}
    context_rules = _context_rules(context_config)

    @callback
    def publish(service_info: bluetooth.BluetoothServiceInfoBleak, *, force: bool = False) -> None:
        if not bluetooth.async_address_present(hass, service_info.address, connectable=False):
            known.pop(service_info.address, None)
            return
        identity_info = _identity(service_info)
        if identity_info is None:
            return
        identity, identity_type = identity_info
        observations: list[dict[str, Any]] = []
        for item in bluetooth.async_scanner_devices_by_address(
            hass, service_info.address, connectable=False
        ):
            scanner = item.scanner
            observations.append(
                {
                    "scanner_source": scanner.source,
                    "scanner_name": getattr(scanner, "name", None) or scanner.source,
                    "rssi": item.advertisement.rssi,
                }
            )
        if not observations:
            return
        signature = tuple(
            sorted(
                (str(item["scanner_source"]), round(float(item["rssi"]))) for item in observations
            )
        )
        now = time.monotonic()
        previous = last_published.get(identity)
        if previous and not force:
            previous_time, previous_signature = previous
            old = dict(previous_signature)
            scanner_set_changed = {item[0] for item in signature} != set(old)
            rssi_changed = any(
                abs(rssi - old.get(source, rssi)) >= RSSI_CHANGE_THRESHOLD
                for source, rssi in signature
            )
            if (
                now - previous_time < PUBLISH_INTERVAL
                and not scanner_set_changed
                and not rssi_changed
            ):
                return
        payload = {
            "generated_at": time.time(),
            "identity": identity,
            "identity_type": identity_type,
            "address": service_info.address.lower(),
            "name": service_info.name or service_info.address,
            "observations": observations,
        }
        hass.create_task(
            mqtt.async_publish(hass, topic, json.dumps(payload, separators=(",", ":")), 0, False)
        )
        last_published[identity] = (now, signature)

    @callback
    def discovered(
        service_info: bluetooth.BluetoothServiceInfoBleak, change: bluetooth.BluetoothChange
    ) -> None:
        if _identity(service_info) is None:
            return
        if service_info.address not in known and len(known) >= MAX_IDENTITIES:
            known.pop(next(iter(known)), None)
        known[service_info.address] = service_info
        publish(service_info)

    @callback
    def refresh(_now: datetime) -> None:
        for service_info in list(known.values()):
            publish(service_info, force=True)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            discovered,
            {"connectable": False},
            bluetooth.BluetoothScanningMode.PASSIVE,
            replay=bluetooth.BluetoothCallbackReplay.NEWEST_FIRST,
        )
    )
    entry.async_on_unload(
        async_track_time_interval(hass, refresh, timedelta(seconds=PUBLISH_INTERVAL))
    )

    @callback
    def context_changed(event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state not in {"on", "off"}:
            return
        payload = {
            "entity_id": new_state.entity_id,
            "state": new_state.state,
            "generated_at": time.time(),
            "rule": context_rules[new_state.entity_id],
        }
        hass.create_task(
            mqtt.async_publish(
                hass, CONTEXT_TOPIC, json.dumps(payload, separators=(",", ":")), 0, False
            )
        )

    if context_rules:
        entry.async_on_unload(
            async_track_state_change_event(hass, tuple(context_rules), context_changed)
        )
    else:
        LOGGER.info("No DAWNLoc context sensors configured in %s", context_path)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
