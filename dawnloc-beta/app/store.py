# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from typing import Any

from .parser import is_mac, normalize_mac

SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = value.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
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

    def _init_schema(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS devices (
                    mac TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rooms (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fingerprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_mac TEXT NOT NULL,
                    room_slug TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(device_mac) REFERENCES devices(mac) ON DELETE CASCADE,
                    FOREIGN KEY(room_slug) REFERENCES rooms(slug) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS discovery_cleanup (
                    slug TEXT PRIMARY KEY,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS access_point_rooms (
                    hostname TEXT PRIMARY KEY,
                    room_slug TEXT,
                    weight REAL NOT NULL DEFAULT 0.08,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(room_slug) REFERENCES rooms(slug) ON DELETE SET NULL
                );
                """
            )

    def list_devices(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM devices ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_device(self, mac: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM devices WHERE mac = ?", (normalize_mac(mac),)
            ).fetchone()
        return dict(row) if row else None

    def get_device_by_slug(self, slug: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM devices WHERE slug = ?", (slug,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_device(self, mac: str, name: str, slug: str | None = None) -> dict[str, Any]:
        mac = normalize_mac(mac)
        existing = self.get_device(mac)
        stable_slug = existing["slug"] if existing else slugify(slug or name)
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO devices(mac, name, slug, enabled, created_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(mac) DO UPDATE SET
                    name=excluded.name,
                    enabled=1
                """,
                (mac, name.strip(), stable_slug, time.time()),
            )
        return self.get_device(mac) or {}

    def rename_device(self, mac: str, name: str) -> dict[str, Any] | None:
        mac = normalize_mac(mac)
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE devices SET name = ? WHERE mac = ?",
                (name.strip(), mac),
            )
        return self.get_device(mac)

    def delete_device(self, mac: str) -> None:
        mac = normalize_mac(mac)
        with self.lock, self.conn:
            row = self.conn.execute("SELECT slug FROM devices WHERE mac = ?", (mac,)).fetchone()
            if row:
                self.conn.execute(
                    "INSERT OR REPLACE INTO discovery_cleanup(slug, created_at) VALUES (?, ?)",
                    (row["slug"], time.time()),
                )
            self.conn.execute("DELETE FROM devices WHERE mac = ?", (mac,))

    def list_cleanup_slugs(self) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT slug FROM discovery_cleanup ORDER BY created_at"
            ).fetchall()
        return [str(row["slug"]) for row in rows]

    def clear_cleanup_slug(self, slug: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM discovery_cleanup WHERE slug = ?", (slug,))

    def list_rooms(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM rooms ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [room_record(row) or {} for row in rows]

    def get_room(self, room_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM rooms WHERE slug = ?", (room_id,)
            ).fetchone()
        return room_record(row)

    def upsert_room(self, name: str, slug: str | None = None) -> dict[str, Any]:
        room_id = slugify(slug or name)
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO rooms(slug, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET name=excluded.name
                """,
                (room_id, name.strip(), time.time()),
            )
        return self.get_room(room_id) or {}

    def rename_room(self, room_id: str, name: str) -> dict[str, Any] | None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE rooms SET name = ? WHERE slug = ?",
                (name.strip(), room_id),
            )
        return self.get_room(room_id)

    def delete_room(self, room_id: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM rooms WHERE slug = ?", (room_id,))

    def room_names(self) -> dict[str, str]:
        with self.lock:
            rows = self.conn.execute("SELECT slug, name FROM rooms").fetchall()
        return {row["slug"]: row["name"] for row in rows}

    def add_fingerprint(
        self,
        device_mac: str,
        room_slug: str,
        vector: dict[str, float],
        sample_count: int,
    ) -> int:
        normalized = {
            normalize_mac(key) if is_mac(key) else key.strip().casefold(): round(float(value), 1)
            for key, value in vector.items()
        }
        with self.lock, self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO fingerprints(
                    device_mac, room_slug, vector_json, sample_count, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalize_mac(device_mac),
                    room_slug,
                    json.dumps(normalized, sort_keys=True),
                    sample_count,
                    time.time(),
                ),
            )
        return int(cursor.lastrowid)

    def list_fingerprints(self, device_mac: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT f.*, d.name AS device_name, r.name AS room_name
            FROM fingerprints f
            LEFT JOIN devices d ON d.mac = f.device_mac
            LEFT JOIN rooms r ON r.slug = f.room_slug
        """
        args: tuple[Any, ...] = ()
        if device_mac:
            sql += " WHERE f.device_mac = ?"
            args = (normalize_mac(device_mac),)
        sql += " ORDER BY f.created_at DESC"

        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()

        fingerprints = []
        for row in rows:
            item = dict(row)
            item["room_id"] = item["room_slug"]
            item["vector"] = json.loads(item.pop("vector_json"))
            fingerprints.append(item)
        return fingerprints

    def delete_fingerprint(self, fingerprint_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM fingerprints WHERE id = ?", (fingerprint_id,))

    def list_access_point_rooms(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT a.hostname, a.room_slug, a.weight, a.updated_at,
                       r.name AS room_name
                FROM access_point_rooms a
                LEFT JOIN rooms r ON r.slug = a.room_slug
                ORDER BY a.hostname COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def access_point_room_map(self) -> dict[str, dict[str, Any]]:
        return {
            str(item["hostname"]).casefold(): item
            for item in self.list_access_point_rooms()
        }

    def set_access_point_room(
        self,
        hostname: str,
        room_slug: str | None,
        weight: float = 0.08,
    ) -> dict[str, Any]:
        hostname = hostname.strip()
        if not hostname:
            raise ValueError("hostname is required")
        if room_slug and not self.get_room(room_slug):
            raise ValueError("errors.room_not_configured")
        weight = max(0.0, min(float(weight), 0.25))
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO access_point_rooms(hostname, room_slug, weight, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(hostname) DO UPDATE SET
                    room_slug=excluded.room_slug,
                    weight=excluded.weight,
                    updated_at=excluded.updated_at
                """,
                (hostname, room_slug or None, weight, time.time()),
            )
        return next(
            item for item in self.list_access_point_rooms()
            if item["hostname"].casefold() == hostname.casefold()
        )

    def room_profile_fingerprints(self) -> list[dict[str, Any]]:
        # All consciously calibrated fingerprints are eligible for the
        # shared profile. Device count is retained so one device cannot
        # silently masquerade as broad support.
        return self.list_fingerprints()

