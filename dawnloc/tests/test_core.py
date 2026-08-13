# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

import time

import pytest
from app.locator import Locator
from app.parser import parse_hearing_map
from app.store import Store

CLIENT = "02:11:22:33:44:55"
AP_ONE = "aa:bb:cc:dd:ee:01"
AP_TWO = "aa:bb:cc:dd:ee:02"


@pytest.fixture
def store(tmp_path):
    database = Store(str(tmp_path / "dawnloc.db"))
    yield database
    database.close()


def test_discovery_ignores_clients_without_ip(store):
    locator = Locator(store)
    locator.ingest(
        parse_hearing_map({"Home": {CLIENT: {AP_ONE: {"signal": -48}}}}),
        access_points=[{"bssid": AP_ONE, "hostname": "ap-kitchen", "band": "5 GHz"}],
    )
    assert locator.discovered()["clients"] == []


def test_strong_single_ap_uses_assigned_room(store):
    store.upsert_device(CLIENT, "Phone", "phone")
    store.upsert_room("Kitchen", "kitchen")
    store.set_access_point_room("ap-kitchen", "kitchen")
    locator = Locator(store, stable_seconds=0, single_ap_threshold=-58)
    locator.ingest(
        parse_hearing_map({"Home": {CLIENT: {AP_ONE: {"signal": -47}}}}),
        clients=[{"mac": CLIENT, "ip": "192.168.1.20"}],
        access_points=[{"bssid": AP_ONE, "hostname": "ap-kitchen", "band": "5 GHz"}],
    )
    state = locator.classify(CLIENT)
    assert state["instant_room_slug"] == "kitchen"
    assert state["method"] == "strong_single_ap"


def test_last_room_is_retained_while_device_is_online(store):
    store.upsert_device(CLIENT, "Phone", "phone")
    store.upsert_room("Kitchen", "kitchen")
    store.set_access_point_room("ap-kitchen", "kitchen")
    locator = Locator(store, stable_seconds=0, offline_after=300, single_ap_threshold=-58)
    locator.ingest(
        parse_hearing_map({"Home": {CLIENT: {AP_ONE: {"signal": -47}}}}),
        clients=[{"mac": CLIENT, "ip": "192.168.1.20"}],
        access_points=[{"bssid": AP_ONE, "hostname": "ap-kitchen", "band": "5 GHz"}],
    )
    locator.tick()
    assert locator.classify(CLIENT)["stable_room_slug"] == "kitchen"
    locator.history[CLIENT].clear()
    locator.client_last_seen[CLIENT] = time.time()
    locator.tick()
    assert locator.classify(CLIENT)["stable_room_slug"] == "kitchen"


def test_fingerprint_export_contains_dependencies(store):
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_device(CLIENT, "Phone", "phone")
    store.add_fingerprint(CLIENT, "kitchen", {"ap:ap-kitchen|5 ghz": -48}, 10)
    data = store.export_data("fingerprints")
    assert len(data["devices"]) == 1
    assert len(data["rooms"]) == 1
    assert len(data["fingerprints"]) == 1


def test_legacy_room_anchors_are_removed_on_startup(tmp_path):
    path = tmp_path / "dawnloc.db"
    first = Store(str(path))
    first.upsert_room("Kitchen", "kitchen")
    with first.lock, first.conn:
        first.conn.execute(
            """INSERT INTO devices
            (mac,name,slug,enabled,device_type,reference_room_slug,created_at)
            VALUES(?,?,?,1,'reference','kitchen',?)""",
            (CLIENT, "Old anchor", "old_anchor", time.time()),
        )
    first.close()

    migrated = Store(str(path))
    try:
        assert migrated.get_device(CLIENT) is None
    finally:
        migrated.close()


def test_ap_assignment_is_per_hostname(store):
    store.upsert_room("Office", "office")
    assignment = store.set_access_point_room("AP-OFFICE", "office")
    assert assignment["room_slug"] == "office"
    assert store.access_point_room_map()["ap-office"]["room_slug"] == "office"


def test_ble_samples_stay_in_memory_and_locate_mapped_person(store):
    store.upsert_device(CLIENT, "Phone", "phone")
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_person("Example Person", "example", "person.example")
    store.map_ble_identity("ibeacon:test:1:1", "Phone beacon", "example")
    store.map_ble_scanner("scanner-kitchen", "Kitchen proxy", "kitchen")
    locator = Locator(store, stable_seconds=0)
    locator.ingest_ble(
        {
            "identity": "ibeacon:test:1:1",
            "identity_type": "ibeacon",
            "observations": [{"scanner_source": "scanner-kitchen", "rssi": -50}],
        }
    )
    state = locator.classify_person("example")
    assert state["offline"] is False
    assert state["instant_room_slug"] == "kitchen"
    assert state["method"] == "ble"
    tables = {
        row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "ble_observations" not in tables


def test_ble_mappings_are_in_full_export(store):
    store.upsert_device(CLIENT, "Phone", "phone")
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_person("Example Person", "example")
    store.map_ble_identity("ibeacon:test:1:1", "Phone beacon", "example")
    store.map_ble_scanner("scanner-kitchen", "Kitchen proxy", "kitchen")
    data = store.export_data("all")
    assert data["ble_identities"][0]["person_slug"] == "example"
    assert data["ble_scanners"][0]["room_slug"] == "kitchen"
    assert data["persons"][0]["ha_person_entity"] is None


def test_person_combines_wifi_and_ble_sources(store):
    store.upsert_device(CLIENT, "Phone", "phone")
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_person("Example Person", "example")
    store.assign_device_to_person(CLIENT, "example")
    store.map_ble_identity("ibeacon:test:1:1", "Watch", "example")
    store.map_ble_scanner("scanner-kitchen", "Kitchen proxy", "kitchen")
    locator = Locator(store, stable_seconds=0)
    locator.ingest_ble(
        {
            "identity": "ibeacon:test:1:1",
            "observations": [{"scanner_source": "scanner-kitchen", "rssi": -45}],
        }
    )
    state = locator.classify_person("example")
    assert state["stable_room_slug"] == "kitchen"
    assert state["offline"] is False


def test_context_rules_are_generic_and_memory_only(store):
    store.upsert_person("Example Person", "example")
    locator = Locator(store, stable_seconds=0)
    locator.ingest_context(
        {
            "entity_id": "binary_sensor.any_motion",
            "state": "on",
            "rule": {"role": "room", "room": "office", "weight": 20, "max_age": 30},
        }
    )
    state = locator.classify_person("example")
    assert state["instant_room_slug"] is None
    tables = {
        row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "context_events" not in tables
