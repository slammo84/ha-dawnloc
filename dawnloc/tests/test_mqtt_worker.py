from types import SimpleNamespace

from app.mqtt_worker import MQTTWorker


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))


def test_device_state_only_publishes_stable_changes():
    locator = SimpleNamespace(classify=lambda _mac: {"offline": False, "stable_room": "Kitchen"})
    worker = object.__new__(MQTTWorker)
    worker.locator = locator
    worker.client = FakeClient()
    worker.published_states = {}
    device = {"mac": "02:11:22:33:44:55", "slug": "phone"}

    worker._publish_device_state(device)
    worker._publish_device_state(device)

    assert worker.client.messages == [
        ("dawnloc/device/phone/presence", "home", True),
        ("dawnloc/device/phone/room", "Kitchen", True),
    ]


def test_discovery_does_not_publish_volatile_entities():
    worker = object.__new__(MQTTWorker)
    worker.client = FakeClient()
    worker.published_states = {}
    worker.publish_discovery({"mac": "02:11:22:33:44:55", "slug": "phone", "name": "Phone"})
    configured = {topic for topic, payload, _retain in worker.client.messages if payload}
    assert configured == {
        "homeassistant/device_tracker/dawnloc_phone_tracker/config",
        "homeassistant/sensor/dawnloc_phone_room/config",
    }
