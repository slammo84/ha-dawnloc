# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .locator import Locator
from .mqtt_worker import MQTTWorker
from .parser import is_mac
from .store import Store

DEFAULT_OPTIONS: dict[str, Any] = {
    "raw_topic": "dawnloc/raw/hearing_map",
    "sample_ttl_seconds": 20,
    "offline_after_seconds": 300,
    "stable_seconds": 60,
    "sample_window": 7,
    "min_shared_aps": 2,
    "room_hold_seconds": 60,
    "switch_confidence": 70,
    "log_level": "info",
}


@dataclass(frozen=True)
class Settings:
    raw_topic: str
    sample_ttl_seconds: int
    offline_after_seconds: int
    stable_seconds: int
    sample_window: int
    min_shared_aps: int
    room_hold_seconds: int
    switch_confidence: float
    log_level: str

    @classmethod
    def load(cls) -> Settings:
        options_path = Path(os.environ.get("DAWNLOC_OPTIONS", "/data/options.json"))
        options = DEFAULT_OPTIONS.copy()
        if options_path.exists():
            options.update(json.loads(options_path.read_text(encoding="utf-8")))
        return cls(
            raw_topic=str(options["raw_topic"]),
            sample_ttl_seconds=int(options["sample_ttl_seconds"]),
            offline_after_seconds=int(options["offline_after_seconds"]),
            stable_seconds=int(options["stable_seconds"]),
            sample_window=int(options["sample_window"]),
            min_shared_aps=max(2, int(options["min_shared_aps"])),
            room_hold_seconds=max(0, int(options["room_hold_seconds"])),
            switch_confidence=max(0.0, min(float(options["switch_confidence"]), 100.0)),
            log_level=str(options["log_level"]),
        )


SETTINGS = Settings.load()
logging.basicConfig(
    level=getattr(logging, SETTINGS.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

STORE = Store(os.environ.get("DAWNLOC_DB", "/data/dawnloc.db"))
LOCATOR = Locator(
    STORE,
    ttl_seconds=SETTINGS.sample_ttl_seconds,
    offline_after=SETTINGS.offline_after_seconds,
    stable_seconds=SETTINGS.stable_seconds,
    sample_window=SETTINGS.sample_window,
    min_shared_aps=SETTINGS.min_shared_aps,
    room_hold_seconds=SETTINGS.room_hold_seconds,
    switch_confidence=SETTINGS.switch_confidence,
)
MQTT = MQTTWorker(
    STORE,
    LOCATOR,
    host=os.environ.get("MQTT_HOST", "localhost"),
    port=int(os.environ.get("MQTT_PORT", "1883")),
    username=os.environ.get("MQTT_USERNAME"),
    password=os.environ.get("MQTT_PASSWORD"),
    raw_topic=SETTINGS.raw_topic,
)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    MQTT.start()
    try:
        yield
    finally:
        MQTT.stop()
        STORE.close()


app = FastAPI(title="DAWNLoc", version=__version__, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class DeviceInput(BaseModel):
    mac: str
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = None


class RoomInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = None


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AccessPointRoomInput(BaseModel):
    room_slug: str | None = None
    weight: float = 0.08


class CalibrationInput(BaseModel):
    device_mac: str
    room_slug: str
    duration: int = Field(default=25, ge=5, le=120)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mqtt_connected": MQTT.connected}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "mqtt_connected": MQTT.connected,
        "raw_topic": MQTT.raw_topic,
        "last_raw_message": LOCATOR.last_raw_message,
        "source_node": LOCATOR.source_node,
        "device_count": len(STORE.list_devices()),
        "room_count": len(STORE.list_rooms()),
        "fingerprint_count": len(STORE.list_fingerprints()),
        "version": __version__,
    }


@app.get("/api/live")
def live() -> list[dict[str, Any]]:
    return LOCATOR.list_states()


@app.get("/api/discovered")
def discovered() -> dict[str, Any]:
    data = LOCATOR.discovered()
    configured_macs = {device["mac"] for device in STORE.list_devices()}
    clients = []
    for client in data["clients"]:
        if not client["locatable"]:
            continue
        client["configured"] = client["mac"] in configured_macs
        clients.append(client)
    data["clients"] = clients
    return data


@app.get("/api/devices")
def devices() -> list[dict[str, Any]]:
    return STORE.list_devices()


@app.post("/api/devices")
def add_device(item: DeviceInput) -> dict[str, Any]:
    if not is_mac(item.mac):
        raise HTTPException(status_code=400, detail="errors.invalid_mac")
    try:
        device = STORE.upsert_device(item.mac, item.name, item.slug)
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="errors.duplicate_device") from error
    MQTT.sync_discovery()
    MQTT.publish_device_state(device)
    return device


@app.delete("/api/devices/{mac}")
def delete_device(mac: str) -> dict[str, bool]:
    if not is_mac(mac):
        raise HTTPException(status_code=400, detail="errors.invalid_mac")
    device = STORE.get_device(mac)
    if device is None:
        raise HTTPException(status_code=404, detail="errors.device_not_found")
    STORE.delete_device(mac)
    MQTT.remove_device(device)
    return {"ok": True}


@app.patch("/api/devices/{mac}")
def rename_device(mac: str, item: NameInput) -> dict[str, Any]:
    if not is_mac(mac):
        raise HTTPException(status_code=400, detail="errors.invalid_mac")
    device = STORE.rename_device(mac, item.name)
    if device is None:
        raise HTTPException(status_code=404, detail="errors.device_not_found")
    MQTT.sync_discovery()
    MQTT.publish_device_state(device)
    return device


@app.get("/api/rooms")
def rooms() -> list[dict[str, Any]]:
    return STORE.list_rooms()


@app.post("/api/rooms")
def add_room(item: RoomInput) -> dict[str, Any]:
    return STORE.upsert_room(item.name, item.slug)


@app.delete("/api/rooms/{slug}")
def delete_room(slug: str) -> dict[str, bool]:
    STORE.delete_room(slug)
    return {"ok": True}


@app.patch("/api/rooms/{room_id}")
def rename_room(room_id: str, item: NameInput) -> dict[str, Any]:
    room = STORE.rename_room(room_id, item.name)
    if room is None:
        raise HTTPException(status_code=404, detail="errors.room_not_configured")
    MQTT.publish_all_states()
    return room


@app.get("/api/access-point-rooms")
def access_point_rooms() -> list[dict[str, Any]]:
    return STORE.list_access_point_rooms()


@app.put("/api/access-point-rooms/{hostname}")
def set_access_point_room(hostname: str, item: AccessPointRoomInput) -> dict[str, Any]:
    try:
        return STORE.set_access_point_room(hostname, item.room_slug, item.weight)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/fingerprints")
def fingerprints() -> list[dict[str, Any]]:
    return STORE.list_fingerprints()


@app.delete("/api/fingerprints/{fingerprint_id}")
def delete_fingerprint(fingerprint_id: int) -> dict[str, bool]:
    STORE.delete_fingerprint(fingerprint_id)
    return {"ok": True}


@app.post("/api/calibrations/start")
def start_calibration(item: CalibrationInput) -> dict[str, Any]:
    try:
        session = LOCATOR.start_calibration(item.device_mac, item.room_slug, item.duration)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return LOCATOR.calibration_status(session.id) or {}


@app.get("/api/calibrations/{session_id}")
def calibration_status(session_id: str) -> dict[str, Any]:
    result = LOCATOR.calibration_status(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="errors.calibration_not_found")
    return result


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8099, proxy_headers=True)


if __name__ == "__main__":
    run()
