# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .parser import is_mac, normalize_mac

SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slugify(value: str) -> str:
    value = (
        value.strip().lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    )
    value = re.sub(r"\s+", "_", value)
    return SLUG_RE.sub("_", value).strip("_") or "item"


def room_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["id"] = item["slug"]
    return item


class Store:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._init_schema()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            try:
                self.conn.execute("BEGIN")
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _columns(self, table: str) -> set[str]:
        return {str(r["name"]) for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _init_schema(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript("""
            PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS devices (
              mac TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
              enabled INTEGER NOT NULL DEFAULT 1, device_type TEXT NOT NULL DEFAULT 'tracked',
              reference_room_slug TEXT, created_at REAL NOT NULL,
              FOREIGN KEY(reference_room_slug) REFERENCES rooms(slug) ON DELETE SET NULL);
            CREATE TABLE IF NOT EXISTS rooms (slug TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS fingerprints (
              id INTEGER PRIMARY KEY AUTOINCREMENT, device_mac TEXT NOT NULL, room_slug TEXT NOT NULL,
              vector_json TEXT NOT NULL, sample_count INTEGER NOT NULL, created_at REAL NOT NULL,
              FOREIGN KEY(device_mac) REFERENCES devices(mac) ON DELETE CASCADE,
              FOREIGN KEY(room_slug) REFERENCES rooms(slug) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS discovery_cleanup (slug TEXT PRIMARY KEY, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS access_point_rooms (
              hostname TEXT PRIMARY KEY, room_slug TEXT, updated_at REAL NOT NULL,
              FOREIGN KEY(room_slug) REFERENCES rooms(slug) ON DELETE SET NULL);
            CREATE TABLE IF NOT EXISTS ble_identities (
              identity TEXT PRIMARY KEY, name TEXT NOT NULL, device_mac TEXT,
              FOREIGN KEY(device_mac) REFERENCES devices(mac) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS ble_scanners (
              source TEXT PRIMARY KEY, name TEXT NOT NULL, room_slug TEXT,
              FOREIGN KEY(room_slug) REFERENCES rooms(slug) ON DELETE SET NULL);
            CREATE TABLE IF NOT EXISTS persons (
              slug TEXT PRIMARY KEY, name TEXT NOT NULL, ha_person_entity TEXT,
              created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS person_devices (
              person_slug TEXT NOT NULL, device_mac TEXT NOT NULL UNIQUE,
              weight REAL NOT NULL DEFAULT 1.0,
              PRIMARY KEY(person_slug, device_mac),
              FOREIGN KEY(person_slug) REFERENCES persons(slug) ON DELETE CASCADE,
              FOREIGN KEY(device_mac) REFERENCES devices(mac) ON DELETE CASCADE);
            """)
            cols = self._columns("devices")
            if "device_type" not in cols:
                self.conn.execute(
                    "ALTER TABLE devices ADD COLUMN device_type TEXT NOT NULL DEFAULT 'tracked'"
                )
            if "reference_room_slug" not in cols:
                self.conn.execute("ALTER TABLE devices ADD COLUMN reference_room_slug TEXT")
            # Room anchors were experimental. Remove them during the beta migration;
            # their fingerprints are removed by the existing cascade.
            self.conn.execute("DELETE FROM devices WHERE device_type='reference'")
            self.conn.execute("UPDATE devices SET device_type='tracked', reference_room_slug=NULL")
            if "person_slug" not in self._columns("ble_identities"):
                self.conn.execute("ALTER TABLE ble_identities ADD COLUMN person_slug TEXT")

    def list_devices(self) -> list[dict[str, Any]]:
        sql = "SELECT * FROM devices ORDER BY name COLLATE NOCASE"
        with self.lock:
            rows = self.conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def get_device(self, mac: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM devices WHERE mac=?", (normalize_mac(mac),)
            ).fetchone()
        return dict(row) if row else None

    def get_device_by_slug(self, slug: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM devices WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None

    def upsert_device(
        self,
        mac: str,
        name: str,
        slug: str | None = None,
    ) -> dict[str, Any]:
        mac = normalize_mac(mac)
        existing = self.get_device(mac)
        stable_slug = existing["slug"] if existing else slugify(slug or name)
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO devices(mac,name,slug,enabled,device_type,reference_room_slug,created_at)
            VALUES(?,?,?,1,?,?,?) ON CONFLICT(mac) DO UPDATE SET name=excluded.name,enabled=1,
            device_type=excluded.device_type,reference_room_slug=excluded.reference_room_slug""",
                (mac, name.strip(), stable_slug, "tracked", None, time.time()),
            )
        return self.get_device(mac) or {}

    def rename_device(self, mac: str, name: str) -> dict[str, Any] | None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE devices SET name=? WHERE mac=?", (name.strip(), normalize_mac(mac))
            )
        return self.get_device(mac)

    def delete_device(self, mac: str) -> None:
        mac = normalize_mac(mac)
        with self.lock, self.conn:
            row = self.conn.execute("SELECT slug FROM devices WHERE mac=?", (mac,)).fetchone()
            if row:
                self.conn.execute(
                    "INSERT OR REPLACE INTO discovery_cleanup VALUES(?,?)",
                    (row["slug"], time.time()),
                )
            self.conn.execute("DELETE FROM devices WHERE mac=?", (mac,))

    def list_persons(self) -> list[dict[str, Any]]:
        with self.lock:
            people = [
                dict(row)
                for row in self.conn.execute(
                    "SELECT * FROM persons ORDER BY name COLLATE NOCASE"
                ).fetchall()
            ]
            links = self.conn.execute(
                """SELECT p.person_slug,p.device_mac,p.weight,d.name device_name
                FROM person_devices p JOIN devices d ON d.mac=p.device_mac"""
            ).fetchall()
        by_person: dict[str, list[dict[str, Any]]] = {}
        for row in links:
            item = dict(row)
            by_person.setdefault(str(item.pop("person_slug")), []).append(item)
        for person in people:
            person["devices"] = by_person.get(str(person["slug"]), [])
        return people

    def get_person(self, slug: str) -> dict[str, Any] | None:
        return next((person for person in self.list_persons() if person["slug"] == slug), None)

    def upsert_person(
        self, name: str, slug: str | None = None, ha_person_entity: str | None = None
    ) -> dict[str, Any]:
        person_slug = slugify(slug or name)
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO persons(slug,name,ha_person_entity,created_at) VALUES(?,?,?,?)
                ON CONFLICT(slug) DO UPDATE SET name=excluded.name,
                ha_person_entity=excluded.ha_person_entity""",
                (person_slug, name.strip(), ha_person_entity or None, time.time()),
            )
        return self.get_person(person_slug) or {}

    def delete_person(self, slug: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM persons WHERE slug=?", (slug,))

    def assign_device_to_person(self, device_mac: str, person_slug: str | None) -> None:
        device_mac = normalize_mac(device_mac)
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM person_devices WHERE device_mac=?", (device_mac,))
            if person_slug:
                self.conn.execute(
                    "INSERT INTO person_devices(person_slug,device_mac) VALUES(?,?)",
                    (person_slug, device_mac),
                )

    def person_device_map(self) -> dict[str, str]:
        with self.lock:
            rows = self.conn.execute("SELECT device_mac,person_slug FROM person_devices").fetchall()
        return {str(row["device_mac"]): str(row["person_slug"]) for row in rows}

    def list_cleanup_slugs(self) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT slug FROM discovery_cleanup ORDER BY created_at"
            ).fetchall()
        return [str(r["slug"]) for r in rows]

    def clear_cleanup_slug(self, slug: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM discovery_cleanup WHERE slug=?", (slug,))

    def list_rooms(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM rooms ORDER BY name COLLATE NOCASE").fetchall()
        return [room_record(r) or {} for r in rows]

    def get_room(self, slug: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM rooms WHERE slug=?", (slug,)).fetchone()
        return room_record(row)

    def upsert_room(self, name: str, slug: str | None = None) -> dict[str, Any]:
        sid = slugify(slug or name)
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO rooms VALUES(?,?,?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name",
                (sid, name.strip(), time.time()),
            )
        return self.get_room(sid) or {}

    def rename_room(self, slug: str, name: str) -> dict[str, Any] | None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE rooms SET name=? WHERE slug=?", (name.strip(), slug))
        return self.get_room(slug)

    def delete_room(self, slug: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM rooms WHERE slug=?", (slug,))

    def room_names(self) -> dict[str, str]:
        with self.lock:
            rows = self.conn.execute("SELECT slug,name FROM rooms").fetchall()
        return {r["slug"]: r["name"] for r in rows}

    def add_fingerprint(
        self,
        device_mac: str,
        room_slug: str,
        vector: dict[str, float],
        sample_count: int,
        created_at: float | None = None,
    ) -> int:
        norm = {
            normalize_mac(k) if is_mac(k) else k.strip().casefold(): round(float(v), 1)
            for k, v in vector.items()
        }
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO fingerprints(device_mac,room_slug,vector_json,sample_count,created_at) VALUES(?,?,?,?,?)",
                (
                    normalize_mac(device_mac),
                    room_slug,
                    json.dumps(norm, sort_keys=True),
                    sample_count,
                    created_at or time.time(),
                ),
            )
        return int(cur.lastrowid)

    def list_fingerprints(self, device_mac: str | None = None) -> list[dict[str, Any]]:
        sql = """SELECT f.*,d.name device_name,r.name room_name FROM fingerprints f
        LEFT JOIN devices d ON d.mac=f.device_mac LEFT JOIN rooms r ON r.slug=f.room_slug"""
        args = ()
        if device_mac:
            sql += " WHERE f.device_mac=?"
            args = (normalize_mac(device_mac),)
        sql += " ORDER BY f.created_at DESC"
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["room_id"] = item["room_slug"]
            item["vector"] = json.loads(item.pop("vector_json"))
            out.append(item)
        return out

    def delete_fingerprint(self, fid: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM fingerprints WHERE id=?", (fid,))

    def list_access_point_rooms(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("""SELECT a.hostname,a.room_slug,a.updated_at,r.name room_name FROM access_point_rooms a
        LEFT JOIN rooms r ON r.slug=a.room_slug ORDER BY a.hostname COLLATE NOCASE""").fetchall()
        return [dict(r) for r in rows]

    def map_ble_identity(self, identity: str, name: str, person_slug: str | None) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO ble_identities(identity,name,device_mac,person_slug)
                VALUES(?,?,NULL,?) ON CONFLICT(identity) DO UPDATE SET
                name=excluded.name,device_mac=NULL,person_slug=excluded.person_slug""",
                (identity.strip().casefold(), name.strip(), person_slug or None),
            )

    def map_ble_scanner(self, source: str, name: str, room_slug: str | None) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO ble_scanners(source,name,room_slug) VALUES(?,?,?)
            ON CONFLICT(source) DO UPDATE SET name=excluded.name,room_slug=excluded.room_slug""",
                (source.strip().casefold(), name.strip(), room_slug or None),
            )

    def ble_identity_mappings(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM ble_identities").fetchall()
        return {str(r["identity"]): dict(r) for r in rows}

    def ble_scanner_mappings(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM ble_scanners").fetchall()
        return {str(r["source"]): dict(r) for r in rows}

    def access_point_room_map(self) -> dict[str, dict[str, Any]]:
        return {str(x["hostname"]).casefold(): x for x in self.list_access_point_rooms()}

    def set_access_point_room(self, hostname: str, room_slug: str | None) -> dict[str, Any]:
        hostname = hostname.strip()
        if not hostname:
            raise ValueError("hostname is required")
        if room_slug and not self.get_room(room_slug):
            raise ValueError("errors.room_not_configured")
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO access_point_rooms VALUES(?,?,?) ON CONFLICT(hostname) DO UPDATE SET room_slug=excluded.room_slug,updated_at=excluded.updated_at",
                (hostname, room_slug or None, time.time()),
            )
        return next(
            x
            for x in self.list_access_point_rooms()
            if x["hostname"].casefold() == hostname.casefold()
        )

    def export_data(self, kind: str) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if kind in {"devices", "all"}:
            data["devices"] = self.list_devices()
        if kind in {"fingerprints", "all"}:
            data["rooms"] = self.list_rooms()
            data["devices"] = self.list_devices()
            data["fingerprints"] = self.list_fingerprints()
        if kind == "all":
            data["access_point_rooms"] = self.list_access_point_rooms()
            data["ble_identities"] = list(self.ble_identity_mappings().values())
            data["ble_scanners"] = list(self.ble_scanner_mappings().values())
            data["persons"] = self.list_persons()
        return data

    def import_data(self, payload: dict[str, Any]) -> dict[str, int]:
        counts = {
            "rooms": 0,
            "devices": 0,
            "fingerprints": 0,
            "access_point_rooms": 0,
            "ble_identities": 0,
            "ble_scanners": 0,
            "persons": 0,
        }
        for r in payload.get("rooms", []):
            self.upsert_room(str(r["name"]), str(r["slug"]))
            counts["rooms"] += 1
        for d in payload.get("devices", []):
            self.upsert_device(
                str(d["mac"]),
                str(d["name"]),
                str(d.get("slug") or ""),
            )
            counts["devices"] += 1
        for person in payload.get("persons", []):
            saved = self.upsert_person(
                str(person["name"]),
                str(person.get("slug") or ""),
                person.get("ha_person_entity"),
            )
            for link in person.get("devices", []):
                self.assign_device_to_person(str(link["device_mac"]), saved["slug"])
            counts["persons"] += 1
        existing = {
            (
                f["device_mac"],
                f["room_slug"],
                json.dumps(f["vector"], sort_keys=True),
                int(f["sample_count"]),
                round(float(f["created_at"]), 3),
            )
            for f in self.list_fingerprints()
        }
        for f in payload.get("fingerprints", []):
            key = (
                normalize_mac(str(f["device_mac"])),
                str(f["room_slug"]),
                json.dumps(f["vector"], sort_keys=True),
                int(f["sample_count"]),
                round(float(f.get("created_at") or 0), 3),
            )
            if key in existing:
                continue
            self.add_fingerprint(
                key[0], key[1], f["vector"], key[3], float(f.get("created_at") or time.time())
            )
            counts["fingerprints"] += 1
        for a in payload.get("access_point_rooms", []):
            self.set_access_point_room(str(a["hostname"]), a.get("room_slug"))
            counts["access_point_rooms"] += 1
        for b in payload.get("ble_identities", []):
            self.map_ble_identity(str(b["identity"]), str(b["name"]), b.get("device_mac"))
            counts["ble_identities"] += 1
        for b in payload.get("ble_scanners", []):
            self.map_ble_scanner(str(b["source"]), str(b["name"]), b.get("room_slug"))
            counts["ble_scanners"] += 1
        return counts
