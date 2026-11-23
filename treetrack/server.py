"""HTTP server for treetrack.

The server uses only the Python standard library. It serves the JSON API, the
dashboard, the public tree page, the printable sign and the calendar file.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import db, model, qrgen, weather

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DEFAULT_DB = ROOT.parent / "data" / "treetrack.db"

STATUS_LABEL = {
    "water": "Water now",
    "wait": "Wait for rain",
    "rain": "Rain covered",
    "watch": "Watch",
    "established": "Established",
}

MAX_BODY = 1_000_000


class App:
    def __init__(self, db_path: str | Path = DEFAULT_DB, offline: bool = False, base_url: str | None = None):
        self.db_path = Path(db_path)
        self.offline = offline
        self.base_url = base_url.rstrip("/") if base_url else ""

    def connection(self):
        return db.connect(self.db_path)

    def setup(self, demo: bool = False) -> int:
        connection = self.connection()
        try:
            db.init(connection)
            return db.seed_demo(connection) if demo else 0
        finally:
            connection.close()

    def window(self, connection, lat: float, lon: float, cache: dict) -> weather.Window | None:
        key = f"{float(lat):.3f},{float(lon):.3f}"
        if key in cache:
            return cache[key]
        stored = db.weather_get(connection, key)
        window = weather.Window.from_dict(stored) if stored else None
        if window is not None and window.fetched_at:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(window.fetched_at)
            except ValueError:
                age = timedelta(days=1)
            if age < timedelta(hours=3):
                cache[key] = window
                return window
        if not self.offline:
            try:
                fresh = weather.fetch(lat, lon, date.today())
                db.weather_put(connection, key, fresh.to_dict())
                cache[key] = fresh
                return fresh
            except weather.WeatherError:
                pass
        if window is not None:
            cache[key] = window
            return window
        manual = db.setting_get(connection, "manual:" + key)
        if manual:
            fallback = weather.Window.from_dict(manual)
            cache[key] = fallback
            return fallback
        cache[key] = None
        return None


def _plan_for(tree: dict, window: weather.Window | None) -> dict | None:
    if window is None:
        return None
    try:
        planted = date.fromisoformat(str(tree.get("planted_on"))[:10])
    except ValueError:
        planted = date.today()
    return model.weekly_plan(
        today=date.today(),
        planted_on=planted,
        et0_7d_mm=window.et0_7d,
        rain_7d_mm=window.rain_7d,
        rain_next_3d_mm=window.rain_next_3d,
        bed_m2=float(tree.get("bed_m2") or 1.0),
        species=str(tree.get("species") or "generic"),
        mulch=str(tree.get("mulch") or "none"),
        bucket_l=float(tree.get("bucket_l") or 10),
        logged_l=float(tree.get("litres_7d") or 0),
    ).to_dict()


def tree_payload(tree: dict, window: weather.Window | None) -> dict:
    data = dict(tree)
    data["plan"] = _plan_for(tree, window)
    data["weather"] = window.to_dict() if window else None
    data["status_label"] = STATUS_LABEL.get((data["plan"] or {}).get("status", ""), "No weather")
    return data


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def render_sign(tree: dict, plan: dict | None, url: str, window: weather.Window | None) -> str:
    dose = int(round((plan or {}).get("dose_l") or 0))
    buckets = (plan or {}).get("buckets") or 0
    reason = (plan or {}).get("reason") or "Weather data is not available yet. Check the tree page."
    dose_line = f"{dose} L" if dose else "No water"
    detail = f"{buckets} bucket{'s' if buckets != 1 else ''} this week" if dose else "This week"
    source = ""
    if window is not None:
        source = f"ET0 {window.et0_7d:.0f} mm and rain {window.rain_7d:.0f} mm over seven days. Source: {window.source}."
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Adopt {_escape(tree['name'])}</title>
<style>
  :root {{ --ink: #14301c; --muted: #4d5f52; --line: #cfd8cd; --paper: #fbf8ef; --green: #1f5138; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #e7e1d2; color: var(--ink);
         font-family: "Segoe UI", -apple-system, Roboto, sans-serif; }}
  .sheet {{ width: 210mm; min-height: 297mm; margin: 16px auto; background: var(--paper);
            padding: 18mm 18mm 14mm; display: flex; flex-direction: column; }}
  .top {{ display: flex; align-items: center; gap: 10px; letter-spacing: .12em;
          text-transform: uppercase; font-size: 12px; font-weight: 700; color: var(--green); }}
  .mark {{ width: 30px; height: 30px; }}
  .kicker {{ margin: 26mm 0 4px; font-size: 14px; letter-spacing: .18em; text-transform: uppercase; color: var(--muted); }}
  h1 {{ font-family: Georgia, "Times New Roman", serif; font-size: 42px; line-height: 1.05;
        margin: 0 0 10px; max-width: 150mm; }}
  .address {{ margin: 0; font-size: 15px; color: var(--muted); }}
  .dose {{ display: flex; align-items: baseline; gap: 14px; margin: 26px 0 8px;
           padding: 18px 20px; border: 2px solid var(--green); border-radius: 6px; }}
  .dose .num {{ font-family: Georgia, serif; font-size: 56px; line-height: 1; }}
  .dose .unit {{ font-size: 14px; line-height: 1.3; color: var(--muted); }}
  .reason {{ font-size: 17px; line-height: 1.45; margin: 0 0 22px; max-width: 150mm; }}
  .qr {{ display: flex; gap: 18px; align-items: center; margin-top: auto;
         border-top: 1px solid var(--line); padding-top: 16px; }}
  .qr svg {{ width: 46mm; height: 46mm; display: block; }}
  .qr p {{ margin: 0; font-size: 16px; line-height: 1.4; }}
  .url {{ font-size: 12px; color: var(--muted); margin: 10px 0 0; word-break: break-all; }}
  .foot {{ margin-top: 14px; font-size: 11px; line-height: 1.45; color: var(--muted); }}
  @page {{ size: A4; margin: 0; }}
  @media print {{ body {{ background: #fff; }} .sheet {{ margin: 0; box-shadow: none; }} }}
</style>
</head>
<body>
<main class="sheet">
  <div class="top">
    <svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><path fill="#1f5138" d="M16 2c-5 0-9 3.6-9 8.4 0 2.3 1 4.5 2.7 6.1-.4 1.8-1.6 3.3-3.2 4.2l1.4 2.5c2.4-1.3 4.1-3.4 4.8-6 1 .3 2.1.4 3.3.4s2.3-.1 3.3-.4c.7 2.6 2.4 4.7 4.8 6l1.4-2.5c-1.6-.9-2.8-2.4-3.2-4.2C23 15 24 12.7 24 10.4 24 5.6 21 2 16 2Z"/><rect x="14.7" y="16" width="2.6" height="14" rx="1.3" fill="#6b4f3a"/></svg>
    <span>treetrack</span>
  </div>
  <p class="kicker">Adopt this street tree</p>
  <h1>{_escape(tree['name'])}</h1>
  <p class="address">{_escape(tree['address'])}</p>
  <div class="dose">
    <span class="num">{dose_line}</span>
    <span class="unit">{detail}<br />slowly, at the root ball</span>
  </div>
  <p class="reason">{_escape(reason)}</p>
  <div class="qr">
    {qrgen.svg(url, 180)}
    <p>Scan to see this week&rsquo;s dose<br />and log a watering.<br /><strong>Every bucket counts.</strong></p>
  </div>
  <p class="url">{_escape(url)}</p>
  <p class="foot">Adopted by {_escape(tree.get('adopter') or 'a neighbour')}. {_escape(source)}<br />
  This sign is a guide, not a promise of survival. Water slowly. Do not block the footpath.</p>
</main>
</body>
</html>"""


def _ics_escape(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def render_ics(tree: dict, plan: dict | None, url: str) -> str:
    dose = int(round((plan or {}).get("dose_l") or 0))
    start = (plan or {}).get("next_check") or (date.today() + timedelta(days=7)).isoformat()
    start_date = start.replace("-", "")
    summary = f"Water {tree['name']} - {dose} L" if dose else f"Check {tree['name']}"
    reason = (plan or {}).get("reason") or "Check the tree page for this week's dose."
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//treetrack//Street tree watering//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:treetrack-{tree['slug']}@treetrack.local",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{start_date}",
        "DURATION:P1D",
        "RRULE:FREQ=WEEKLY;COUNT=12",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(reason + ' ' + url)}",
        f"LOCATION:{_ics_escape(tree.get('address') or '')}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


class Handler(BaseHTTPRequestHandler):
    server_version = "treetrack/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send(self, status: int, body, content_type: str = "application/json; charset=utf-8", cache: str = "no-store"):
        if isinstance(body, (dict, list)):
            raw = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Body must be a JSON object.")
        return value

    def _static(self, relative: str, content_type: str | None = None):
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            return self._send(404, {"error": "Not found"})
        if not target.is_file():
            return self._send(404, {"error": "Not found"})
        guessed = content_type or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), guessed, cache="no-cache")

    def _base_url(self) -> str:
        if self.app.base_url:
            return self.app.base_url
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
        return f"http://{host}"

    def _tree_url(self, slug: str) -> str:
        return f"{self._base_url()}/t/{slug}"

    def _load(self, connection, slug: str):
        tree = db.get_tree(connection, slug)
        if not tree:
            return None, None
        window = self.app.window(connection, tree["lat"], tree["lon"], {})
        return tree, window

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/health":
                return self._send(200, {"ok": True, "version": "1.0"})
            if path == "/api/trees":
                connection = self.app.connection()
                try:
                    trees = db.list_trees(connection)
                    cache: dict = {}
                    payload = [tree_payload(tree, self.app.window(connection, tree["lat"], tree["lon"], cache)) for tree in trees]
                finally:
                    connection.close()
                return self._send(200, {"today": date.today().isoformat(), "trees": payload})
            match = re.fullmatch(r"/api/trees/([^/]+)", path)
            if match:
                connection = self.app.connection()
                try:
                    tree, window = self._load(connection, match.group(1))
                finally:
                    connection.close()
                if not tree:
                    return self._send(404, {"error": "Tree not found"})
                return self._send(200, tree_payload(tree, window))
            if path == "/api/weather":
                query = parsed.query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                try:
                    lat = float(params.get("lat", ""))
                    lon = float(params.get("lon", ""))
                except ValueError:
                    return self._send(400, {"error": "lat and lon are required"})
                connection = self.app.connection()
                try:
                    window = self.app.window(connection, lat, lon, {})
                finally:
                    connection.close()
                if window is None:
                    return self._send(503, {"error": "Weather is not available. Enter a manual reading."})
                return self._send(200, window.to_dict())
            sign = re.fullmatch(r"/t/([^/]+)/sign", path)
            if sign:
                connection = self.app.connection()
                try:
                    tree, window = self._load(connection, sign.group(1))
                finally:
                    connection.close()
                if not tree:
                    return self._send(404, "Tree not found", "text/plain; charset=utf-8")
                plan = _plan_for(tree, window)
                return self._send(200, render_sign(tree, plan, self._tree_url(tree["slug"]), window), "text/html; charset=utf-8")
            ics = re.fullmatch(r"/t/([^/]+)/reminder\.ics", path)
            if ics:
                connection = self.app.connection()
                try:
                    tree, window = self._load(connection, ics.group(1))
                finally:
                    connection.close()
                if not tree:
                    return self._send(404, "Tree not found", "text/plain; charset=utf-8")
                plan = _plan_for(tree, window)
                body = render_ics(tree, plan, self._tree_url(tree["slug"]))
                self.send_response(200)
                raw = body.encode("utf-8")
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{tree["slug"]}.ics"')
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            page = re.fullmatch(r"/t/([^/]+)", path)
            if page:
                return self._static("tree.html", "text/html; charset=utf-8")
            if path == "/":
                return self._static("index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            return self._send(404, {"error": "Not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:  # keep the server alive
            print(f"GET {path} failed: {exc}")
            return self._send(500, {"error": "Server error"})

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        try:
            body = self._json_body()
            if path == "/api/trees":
                return self._create_tree(body)
            watering = re.fullmatch(r"/api/trees/([^/]+)/waterings", path)
            if watering:
                return self._add_watering(watering.group(1), body)
            adopt = re.fullmatch(r"/api/trees/([^/]+)/adopt", path)
            if adopt:
                return self._adopt(adopt.group(1), body)
            if path == "/api/weather/manual":
                return self._manual_weather(body)
            return self._send(404, {"error": "Not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            print(f"POST {path} failed: {exc}")
            return self._send(500, {"error": "Server error"})

    def _create_tree(self, body: dict):
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 80:
            raise ValueError("A tree name is required, up to 80 characters.")
        try:
            lat = float(body.get("lat"))
            lon = float(body.get("lon"))
        except (TypeError, ValueError):
            raise ValueError("Latitude and longitude are required.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Latitude or longitude is out of range.")
        planted = str(body.get("planted_on") or date.today().isoformat())[:10]
        try:
            planted_date = date.fromisoformat(planted)
        except ValueError:
            raise ValueError("Planting date must be YYYY-MM-DD.")
        if planted_date > date.today():
            raise ValueError("Planting date cannot be in the future.")
        bed = float(body.get("bed_m2") or 1.0)
        bucket = float(body.get("bucket_l") or 10)
        if not (0.1 <= bed <= 20):
            raise ValueError("Bed area must be between 0.1 and 20 square metres.")
        if not (1 <= bucket <= 50):
            raise ValueError("Bucket size must be between 1 and 50 litres.")
        connection = self.app.connection()
        try:
            tree = db.create_tree(
                connection,
                {
                    "name": name,
                    "address": body.get("address"),
                    "lat": lat,
                    "lon": lon,
                    "species": body.get("species"),
                    "planted_on": planted,
                    "trunk_cm": body.get("trunk_cm"),
                    "bed_m2": bed,
                    "mulch": body.get("mulch"),
                    "bucket_l": bucket,
                    "adopter": body.get("adopter"),
                    "contact": body.get("contact"),
                },
            )
            window = self.app.window(connection, tree["lat"], tree["lon"], {})
        finally:
            connection.close()
        return self._send(201, tree_payload(tree, window))

    def _add_watering(self, slug: str, body: dict):
        try:
            litres = float(body.get("litres"))
        except (TypeError, ValueError):
            raise ValueError("Litres must be a number.")
        if not (0.1 <= litres <= 500):
            raise ValueError("Litres must be between 0.1 and 500.")
        on_date = str(body.get("on_date") or date.today().isoformat())[:10]
        try:
            when = date.fromisoformat(on_date)
        except ValueError:
            raise ValueError("Watering date must be YYYY-MM-DD.")
        if when > date.today() + timedelta(days=1):
            raise ValueError("Watering date cannot be in the future.")
        connection = self.app.connection()
        try:
            entry = db.add_watering(
                connection,
                slug,
                litres,
                on_date=on_date,
                by_name=str(body.get("by_name") or "")[:40],
                note=str(body.get("note") or "")[:200],
            )
            if entry is None:
                return self._send(404, {"error": "Tree not found"})
            tree = db.get_tree(connection, slug)
            window = self.app.window(connection, tree["lat"], tree["lon"], {}) if tree else None
        finally:
            connection.close()
        return self._send(201, {"watering": entry, "tree": tree_payload(tree, window) if tree else None})

    def _adopt(self, slug: str, body: dict):
        adopter = str(body.get("adopter") or "").strip()
        if not adopter or len(adopter) > 60:
            raise ValueError("Your name is required, up to 60 characters.")
        connection = self.app.connection()
        try:
            tree = db.adopt(connection, slug, adopter, str(body.get("contact") or "")[:120])
        finally:
            connection.close()
        if tree is None:
            return self._send(404, {"error": "Tree not found"})
        return self._send(200, {"tree": tree})

    def _manual_weather(self, body: dict):
        try:
            lat = float(body.get("lat"))
            lon = float(body.get("lon"))
            et0 = float(body.get("et0_7d"))
            rain = float(body.get("rain_7d"))
            next3 = float(body.get("rain_next_3d") or 0)
        except (TypeError, ValueError):
            raise ValueError("Latitude, longitude, ET0 and rain are required.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Latitude or longitude is out of range.")
        if any(value < 0 or value > 500 for value in (et0, rain, next3)):
            raise ValueError("Weather values must be between 0 and 500.")
        window = weather.manual(et0, rain, next3)
        key = f"{lat:.3f},{lon:.3f}"
        connection = self.app.connection()
        try:
            db.setting_set(connection, "manual:" + key, window.to_dict())
        finally:
            connection.close()
        return self._send(200, window.to_dict())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="treetrack - street tree watering scheduler")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--demo", action="store_true", help="seed six trees on one street")
    parser.add_argument("--offline", action="store_true", help="never call Open-Meteo")
    parser.add_argument("--base-url", default="", help="public URL used in the QR sign")
    args = parser.parse_args(argv)

    app = App(args.db, offline=args.offline, base_url=args.base_url)
    added = app.setup(demo=args.demo)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.app = app  # type: ignore[attr-defined]
    print(f"treetrack on http://{args.host}:{args.port} (database {args.db})")
    if added:
        print(f"Seeded {added} demo trees.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())