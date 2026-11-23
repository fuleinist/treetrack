"""SQLite storage for trees, waterings and cached weather."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    species TEXT NOT NULL DEFAULT 'generic',
    planted_on TEXT NOT NULL,
    trunk_cm REAL NOT NULL DEFAULT 6,
    bed_m2 REAL NOT NULL DEFAULT 1.0,
    mulch TEXT NOT NULL DEFAULT 'none',
    bucket_l REAL NOT NULL DEFAULT 10,
    adopter TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS waterings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_id INTEGER NOT NULL REFERENCES trees(id) ON DELETE CASCADE,
    on_date TEXT NOT NULL,
    litres REAL NOT NULL,
    by_name TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS waterings_tree_date ON waterings(tree_id, on_date);

CREATE TABLE IF NOT EXISTS weather_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return text.strip("-")[:60] or "tree"


def _unique_slug(connection: sqlite3.Connection, base: str) -> str:
    candidate = base
    index = 2
    while connection.execute("SELECT 1 FROM trees WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def create_tree(connection: sqlite3.Connection, data: dict) -> dict:
    base = slugify(str(data.get("name") or "tree"))
    slug = _unique_slug(connection, base)
    connection.execute(
        """
        INSERT INTO trees (slug, name, address, lat, lon, species, planted_on, trunk_cm,
                           bed_m2, mulch, bucket_l, adopter, contact, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            slug,
            str(data.get("name") or "Street tree").strip(),
            str(data.get("address") or "").strip(),
            float(data.get("lat") or 0),
            float(data.get("lon") or 0),
            str(data.get("species") or "generic"),
            str(data.get("planted_on") or date.today().isoformat())[:10],
            float(data.get("trunk_cm") or 6),
            float(data.get("bed_m2") or 1.0),
            str(data.get("mulch") or "none"),
            float(data.get("bucket_l") or 10),
            str(data.get("adopter") or "").strip(),
            str(data.get("contact") or "").strip(),
            now_iso(),
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM trees WHERE slug = ?", (slug,)).fetchone()
    return dict(row)


def _tree_select(connection: sqlite3.Connection, where: str, params: tuple) -> list[dict]:
    week_start = (date.today() - timedelta(days=6)).isoformat()
    rows = connection.execute(
        f"""
        SELECT t.*,
               (SELECT MAX(on_date) FROM waterings w WHERE w.tree_id = t.id) AS last_watered,
               (SELECT COALESCE(SUM(litres), 0) FROM waterings w
                 WHERE w.tree_id = t.id AND w.on_date >= ?) AS litres_7d,
               (SELECT COUNT(*) FROM waterings w WHERE w.tree_id = t.id) AS watering_count
        FROM trees t
        {where}
        ORDER BY t.name COLLATE NOCASE
        """,
        (week_start,) + params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_trees(connection: sqlite3.Connection) -> list[dict]:
    return _tree_select(connection, "", ())


def get_tree(connection: sqlite3.Connection, slug: str) -> dict | None:
    rows = _tree_select(connection, "WHERE t.slug = ?", (slug,))
    if not rows:
        return None
    tree = rows[0]
    tree["waterings"] = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM waterings WHERE tree_id = ? ORDER BY on_date DESC, id DESC",
            (tree["id"],),
        ).fetchall()
    ]
    return tree


def add_watering(
    connection: sqlite3.Connection,
    slug: str,
    litres: float,
    on_date: str | None = None,
    by_name: str = "",
    note: str = "",
) -> dict | None:
    tree = connection.execute("SELECT id FROM trees WHERE slug = ?", (slug,)).fetchone()
    if not tree:
        return None
    connection.execute(
        "INSERT INTO waterings (tree_id, on_date, litres, by_name, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            tree["id"],
            (on_date or date.today().isoformat())[:10],
            float(litres),
            by_name.strip(),
            note.strip(),
            now_iso(),
        ),
    )
    connection.commit()
    return dict(connection.execute("SELECT * FROM waterings WHERE id = last_insert_rowid()").fetchone())


def adopt(connection: sqlite3.Connection, slug: str, adopter: str, contact: str = "") -> dict | None:
    tree = connection.execute("SELECT id FROM trees WHERE slug = ?", (slug,)).fetchone()
    if not tree:
        return None
    connection.execute(
        "UPDATE trees SET adopter = ?, contact = ? WHERE id = ?",
        (adopter.strip(), contact.strip(), tree["id"]),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM trees WHERE id = ?", (tree["id"],)).fetchone()
    return dict(row)


def weather_get(connection: sqlite3.Connection, key: str) -> dict | None:
    row = connection.execute("SELECT payload, fetched_at FROM weather_cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError:
        return None
    payload["fetched_at"] = row["fetched_at"]
    return payload


def weather_put(connection: sqlite3.Connection, key: str, payload: dict) -> None:
    fetched_at = str(payload.get("fetched_at") or now_iso())
    connection.execute(
        "INSERT INTO weather_cache (key, payload, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at",
        (key, json.dumps(payload), fetched_at),
    )
    connection.commit()


def setting_get(connection: sqlite3.Connection, key: str) -> dict | None:
    row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return None


def setting_set(connection: sqlite3.Connection, key: str, value: dict) -> None:
    connection.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    connection.commit()


def seed_demo(connection: sqlite3.Connection) -> int:
    """Add six trees on one street. Return the number added."""
    if connection.execute("SELECT COUNT(*) AS n FROM trees").fetchone()["n"]:
        return 0
    today = date.today()

    def days_ago(count: int) -> str:
        return (today - timedelta(days=count)).isoformat()

    trees = [
        {
            "name": "The lilly pilly on Wattle Street",
            "address": "12 Wattle Street, Cherrybrook",
            "lat": -33.7305,
            "lon": 151.0521,
            "species": "lilly-pilly",
            "planted_on": days_ago(230),
            "trunk_cm": 4.5,
            "bed_m2": 1.2,
            "mulch": "woodchip",
            "bucket_l": 10,
            "adopter": "Mia Chen",
        },
        {
            "name": "The corner jacaranda",
            "address": "Cnr Wattle Street and Shepherds Drive",
            "lat": -33.7308,
            "lon": 151.0525,
            "species": "jacaranda",
            "planted_on": days_ago(430),
            "trunk_cm": 6.0,
            "bed_m2": 1.0,
            "mulch": "compost",
            "bucket_l": 10,
            "adopter": "Sam Okafor",
        },
        {
            "name": "Crepe myrtle at the bus stop",
            "address": "Wattle Street at Cherrybrook Road",
            "lat": -33.7312,
            "lon": 151.0516,
            "species": "crepe-myrtle",
            "planted_on": days_ago(760),
            "trunk_cm": 8.0,
            "bed_m2": 1.4,
            "mulch": "woodchip",
            "bucket_l": 10,
            "adopter": "",
        },
        {
            "name": "The young eucalyptus",
            "address": "28 Wattle Street, Cherrybrook",
            "lat": -33.7299,
            "lon": 151.0518,
            "species": "eucalyptus",
            "planted_on": days_ago(160),
            "trunk_cm": 3.5,
            "bed_m2": 0.8,
            "mulch": "none",
            "bucket_l": 10,
            "adopter": "Rae Patel",
        },
        {
            "name": "London plane by the crossing",
            "address": "Wattle Street at Franklin Road",
            "lat": -33.7320,
            "lon": 151.0529,
            "species": "plane",
            "planted_on": days_ago(1220),
            "trunk_cm": 18.0,
            "bed_m2": 1.6,
            "mulch": "compost",
            "bucket_l": 10,
            "adopter": "",
        },
        {
            "name": "The old fig on the corner",
            "address": "2 Franklin Road, Cherrybrook",
            "lat": -33.7322,
            "lon": 151.0527,
            "species": "fig",
            "planted_on": days_ago(2800),
            "trunk_cm": 42.0,
            "bed_m2": 2.0,
            "mulch": "woodchip",
            "bucket_l": 10,
            "adopter": "The Nguyen family",
        },
    ]
    created = []
    for tree in trees:
        created.append(create_tree(connection, tree))
    by_slug = {row["slug"]: row for row in created}
    lilly = by_slug.get(slugify("The lilly pilly on Wattle Street"))
    jacaranda = by_slug.get(slugify("The corner jacaranda"))
    myrtle = by_slug.get(slugify("Crepe myrtle at the bus stop"))
    if lilly:
        add_watering(connection, lilly["slug"], 10, days_ago(3), "Mia", "Two buckets after work.")
    if jacaranda:
        add_watering(connection, jacaranda["slug"], 10, days_ago(11), "Sam", "")
    if myrtle:
        add_watering(connection, myrtle["slug"], 20, days_ago(6), "A neighbour", "Filled a watering can twice.")
    # A fixed fallback so the demo works with no network.
    fallback = {
        "et0_7d": 31.5,
        "rain_7d": 3.2,
        "rain_next_3d": 0.0,
        "days": [],
        "source": "manual",
        "fetched_at": now_iso(),
    }
    for row in created:
        key = f"{float(row['lat']):.3f},{float(row['lon']):.3f}"
        setting_set(connection, "manual:" + key, fallback)
    return len(created)