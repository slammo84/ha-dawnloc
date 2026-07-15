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


def test_reference_devices_are_not_returned_as_live_trackers(store):
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_device(CLIENT, "Alexa", "alexa", "reference", "kitchen")
    locator = Locator(store)
    assert locator.list_states() == []


def test_fingerprint_export_contains_dependencies(store):
    store.upsert_room("Kitchen", "kitchen")
    store.upsert_device(CLIENT, "Phone", "phone")
    store.add_fingerprint(CLIENT, "kitchen", {"ap:ap-kitchen|5 ghz": -48}, 10)
    data = store.export_data("fingerprints")
    assert len(data["devices"]) == 1
    assert len(data["rooms"]) == 1
    assert len(data["fingerprints"]) == 1


def test_ap_assignment_is_per_hostname(store):
    store.upsert_room("Office", "office")
    assignment = store.set_access_point_room("AP-OFFICE", "office")
    assert assignment["room_slug"] == "office"
    assert store.access_point_room_map()["ap-office"]["room_slug"] == "office"
