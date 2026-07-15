# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

import json
import time

import pytest
from app.locator import Locator
from app.mqtt_worker import MQTTWorker
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


def test_parser_reads_nested_hearing_map():
    payload = {
        "hearing_map": {
            "Home": {
                CLIENT: {
                    AP_ONE: {"signal": 4294967238},
                    AP_TWO: {"rcpi": 100},
                }
            }
        }
    }

    observations = sorted(parse_hearing_map(payload), key=lambda item: item.bssid)

    assert len(observations) == 2
    assert observations[0].client == CLIENT
    assert observations[0].rssi == -58.0
    assert observations[1].rssi == -60.0


def test_parser_reads_explicit_fields():
    payload = {
        "result": {
            "client": CLIENT,
            "bssid": AP_ONE,
            "ssid": "Home",
            "signal_dbm": "-61",
        }
    }

    [observation] = parse_hearing_map(payload)

    assert observation.client == CLIENT
    assert observation.bssid == AP_ONE
    assert observation.ssid == "Home"
    assert observation.rssi == -61.0


def test_room_fingerprint_classification(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_room("Office", "office")
    store.add_fingerprint(CLIENT, "kitchen", {AP_ONE: -48, AP_TWO: -73}, 20)
    store.add_fingerprint(CLIENT, "office", {AP_ONE: -75, AP_TWO: -50}, 20)

    locator = Locator(store, stable_seconds=0, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {
                "Home": {
                    CLIENT: {
                        AP_ONE: {"signal": -50},
                        AP_TWO: {"signal": -71},
                    }
                }
            }
        ),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-kitchen", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-office", "band": "5 GHz"},
        ],
    )
    result = locator.classify(CLIENT)

    assert result["instant_room"] == "Kitchen"
    assert result["stable_room"] == "Kitchen"
    assert result["confidence"] > 50
    assert result["visible_aps"] == 2


def test_stable_room_uses_current_room_name(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.add_fingerprint(CLIENT, "kitchen", {AP_ONE: -50, AP_TWO: -70}, 20)

    locator = Locator(store, stable_seconds=0, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -50}, AP_TWO: {"signal": -70}}}}
        ),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-kitchen", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-office", "band": "5 GHz"},
        ],
    )
    store.upsert_room("Dining room", "kitchen")

    assert locator.classify(CLIENT)["stable_room"] == "Dining room"


def test_calibration_creates_grouped_fingerprint(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    locator = Locator(store, min_shared_aps=2)
    access_points = [
        {"bssid": AP_ONE, "hostname": "ap-kitchen", "band": "5 GHz"},
        {"bssid": AP_TWO, "hostname": "ap-office", "band": "5 GHz"},
    ]

    session = locator.start_calibration(CLIENT, "kitchen", 5)
    payload = parse_hearing_map(
        {"Home": {CLIENT: {AP_ONE: {"signal": -55}, AP_TWO: {"signal": -72}}}}
    )
    locator.ingest(payload, access_points=access_points)
    locator.ingest(payload, access_points=access_points)
    session.ends_at = time.time() - 1
    locator.tick()
    status = locator.calibration_status(session.id)
    fingerprints = store.list_fingerprints()

    assert status is not None
    assert status["status"] == "complete"
    assert status["ap_count"] == 2
    assert len(fingerprints) == 1
    assert set(fingerprints[0]["vector"]) == {
        "ap:ap-kitchen|5 ghz",
        "ap:ap-office|5 ghz",
    }


def test_discovered_clients_include_network_metadata_and_need_multiple_aps(store):
    locator = Locator(store, min_shared_aps=2)
    observations = parse_hearing_map(
        {"Home": {CLIENT: {AP_ONE: {"signal": -55}, AP_TWO: {"signal": -65}}}}
    )
    locator.ingest(
        observations,
        clients=[{"mac": CLIENT, "hostname": "phone", "ip": "192.168.1.50"}],
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
        ],
    )

    client = locator.discovered()["clients"][0]
    assert client["hostname"] == "phone"
    assert client["ip_address"] == "192.168.1.50"
    assert client["visible_aps"] == 2
    assert client["locatable"] is True


def test_two_radios_on_one_physical_ap_do_not_make_client_locatable(store):
    locator = Locator(store, min_shared_aps=2)
    observations = parse_hearing_map(
        {"Home": {CLIENT: {AP_ONE: {"signal": -55}, AP_TWO: {"signal": -65}}}}
    )
    locator.ingest(
        observations,
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "2.4 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-one", "band": "5 GHz"},
        ],
    )

    client = locator.discovered()["clients"][0]
    assert client["visible_aps"] == 1
    assert client["locatable"] is False


def test_deleted_device_is_queued_for_discovery_cleanup(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.delete_device(CLIENT)

    assert store.get_device(CLIENT) is None
    assert store.list_cleanup_slugs() == ["test_phone"]
    store.clear_cleanup_slug("test_phone")
    assert store.list_cleanup_slugs() == []


def test_access_points_are_grouped_by_hostname_and_band(store):
    locator = Locator(store)
    locator.ingest(
        [],
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "2.4 GHz"},
            {"bssid": "aa:bb:cc:dd:ee:03", "hostname": "ap-one", "band": "2.4 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-one", "band": "5 GHz"},
        ],
    )

    access_points = locator.discovered()["access_points"]
    assert len(access_points) == 2
    assert {item["band"] for item in access_points} == {"2.4 GHz", "5 GHz"}
    assert max(item["bssid_count"] for item in access_points) == 2


def test_unknown_bssids_are_not_counted_as_physical_access_points(store):
    locator = Locator(store, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -55}, AP_TWO: {"signal": -65}}}}
        )
    )

    discovered = locator.discovered()
    client = discovered["clients"][0]
    assert client["visible_bssids"] == 2
    assert client["visible_aps"] == 0
    assert client["locatable"] is False
    assert discovered["access_points"] == []


def test_multiple_bssids_share_one_fingerprint_feature(store):
    third_bssid = "aa:bb:cc:dd:ee:03"
    locator = Locator(store, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {
                "Home": {
                    CLIENT: {
                        AP_ONE: {"signal": -50},
                        third_bssid: {"signal": -54},
                        AP_TWO: {"signal": -70},
                    }
                }
            }
        ),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
            {"bssid": third_bssid, "hostname": "ap-one", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
        ],
    )

    vector = locator.filtered_vector(CLIENT)

    assert vector == {"ap:ap-one|5 ghz": -52.0, "ap:ap-two|5 ghz": -70.0}
    assert locator.discovered()["clients"][0]["visible_aps"] == 2


def test_ambiguous_room_match_is_rejected(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_room("Office", "office")
    store.add_fingerprint(
        CLIENT,
        "kitchen",
        {"ap:ap-one|5 ghz": -55, "ap:ap-two|5 ghz": -65},
        20,
    )
    store.add_fingerprint(
        CLIENT,
        "office",
        {"ap:ap-one|5 ghz": -56, "ap:ap-two|5 ghz": -64},
        20,
    )
    locator = Locator(store, stable_seconds=0, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -55}, AP_TWO: {"signal": -65}}}}
        ),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
        ],
    )

    result = locator.classify(CLIENT)

    assert result["located"] is False
    assert result["instant_room"] is None


def test_device_tracker_uses_home_and_not_home(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.add_fingerprint(CLIENT, "kitchen", {AP_ONE: -50, AP_TWO: -70}, 20)
    locator = Locator(store, stable_seconds=0, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -50}, AP_TWO: {"signal": -70}}}}
        ),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
        ],
    )
    worker = MQTTWorker(store, locator, "localhost", 1883, None, None, "raw")
    messages = []

    class Client:
        def publish(self, topic, payload, retain=False):
            messages.append((topic, payload, retain))

    worker.client = Client()
    worker.connected = True
    device = store.get_device(CLIENT)
    assert device is not None

    worker.publish_device_state(device)
    first = json.loads(messages[-1][1])
    locator.client_last_seen[CLIENT] = time.time() - 120
    worker.publish_device_state(device)
    second = json.loads(messages[-1][1])

    assert first["presence"] == "home"
    assert first["room"] == "Kitchen"
    assert second["presence"] == "not_home"
    assert second["room"] == "Nicht geortet"


def test_new_device_with_one_visible_ap_has_unknown_room(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.add_fingerprint(CLIENT, "kitchen", {AP_ONE: -50, AP_TWO: -70}, 20)
    locator = Locator(store, stable_seconds=0, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map({"Home": {CLIENT: {AP_ONE: {"signal": -50}}}}),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
            {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
        ],
    )

    result = locator.classify(CLIENT)

    assert result["stable_room"] is None
    assert result["instant_room"] is None


def test_last_room_is_kept_with_one_visible_ap(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.add_fingerprint(CLIENT, "kitchen", {AP_ONE: -50, AP_TWO: -70}, 20)
    locator = Locator(store, stable_seconds=0, min_shared_aps=2, room_hold_seconds=60)
    access_points = [
        {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
        {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
    ]
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -50}, AP_TWO: {"signal": -70}}}}
        ),
        access_points=access_points,
    )
    locator.history[CLIENT][AP_TWO].clear()
    locator.tick()

    result = locator.classify(CLIENT)

    assert result["visible_aps"] == 1
    assert result["stable_room"] == "Kitchen"
    assert result["room_held"] is True


def test_room_switch_requires_configured_confidence(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_room("Office", "office")
    store.add_fingerprint(CLIENT, "kitchen", {AP_ONE: -48, AP_TWO: -73}, 20)
    store.add_fingerprint(CLIENT, "office", {AP_ONE: -75, AP_TWO: -50}, 20)
    locator = Locator(
        store,
        stable_seconds=0,
        min_shared_aps=2,
        switch_confidence=100,
    )
    access_points = [
        {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz"},
        {"bssid": AP_TWO, "hostname": "ap-two", "band": "5 GHz"},
    ]
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -49}, AP_TWO: {"signal": -72}}}}
        ),
        access_points=access_points,
    )
    locator.history[CLIENT].clear()
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -74}, AP_TWO: {"signal": -51}}}}
        ),
        access_points=access_points,
    )

    result = locator.classify(CLIENT)

    assert result["instant_room"] == "Office"
    assert result["stable_room"] == "Kitchen"


def test_current_ap_channel_and_band_use_strongest_fresh_bssid(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    locator = Locator(store, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map(
            {"Home": {CLIENT: {AP_ONE: {"signal": -45}, AP_TWO: {"signal": -70}}}}
        ),
        access_points=[
            {
                "bssid": AP_ONE,
                "hostname": "ap-lina",
                "band": "5 GHz",
                "frequency": 5180,
            },
            {
                "bssid": AP_TWO,
                "hostname": "router",
                "band": "2.4 GHz",
                "frequency": 2412,
            },
        ],
    )

    result = locator.classify(CLIENT)

    assert result["current_ap"] == "ap-lina"
    assert result["current_channel"] == 36
    assert result["current_frequency"] == 5180
    assert result["current_band"] == "5 GHz"
    assert result["current_ap_estimated"] is True


def test_device_tracker_stays_home_without_room_fix(store):
    store.upsert_device(CLIENT, "Test phone", "test_phone")
    locator = Locator(store, stable_seconds=0, min_shared_aps=2)
    locator.ingest(
        parse_hearing_map({"Home": {CLIENT: {AP_ONE: {"signal": -50}}}}),
        access_points=[
            {"bssid": AP_ONE, "hostname": "ap-one", "band": "5 GHz", "frequency": 5180}
        ],
    )
    worker = MQTTWorker(store, locator, "localhost", 1883, None, None, "raw")
    messages = []

    class Client:
        def publish(self, topic, payload, retain=False):
            messages.append((topic, payload, retain))

    worker.client = Client()
    worker.connected = True
    device = store.get_device(CLIENT)
    assert device is not None

    worker.publish_device_state(device)
    payload = json.loads(messages[-1][1])

    assert payload["presence"] == "home"
    assert payload["room"] == "Nicht geortet"
    assert payload["located"] is False
