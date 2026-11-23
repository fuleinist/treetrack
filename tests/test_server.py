import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from treetrack.server import App, Handler


@pytest.fixture()
def server(tmp_path):
    app = App(tmp_path / "treetrack.db", offline=True)
    app.setup(demo=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.app = app
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, app
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.status, json.loads(response.read())


def post_json(base, path, body):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def get_text(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.status, response.read().decode("utf-8"), response.headers.get("Content-Type", "")


def test_demo_has_six_trees_with_plans(server):
    base, _ = server
    status, data = get_json(base, "/api/trees")
    assert status == 200
    assert len(data["trees"]) == 6
    assert all(tree["plan"] is not None for tree in data["trees"])
    assert any(tree["plan"]["status"] == "water" for tree in data["trees"])


def test_pages_render(server):
    base, _ = server
    status, html, content_type = get_text(base, "/t/the-lilly-pilly-on-wattle-street")
    assert status == 200
    assert "text/html" in content_type
    assert "tree-page" in html

    status, sign, _ = get_text(base, "/t/the-lilly-pilly-on-wattle-street/sign")
    assert status == 200
    assert "Adopt this street tree" in sign
    assert '<svg' in sign
    assert "/t/the-lilly-pilly-on-wattle-street" in sign


def test_calendar_export(server):
    base, _ = server
    status, body, content_type = get_text(base, "/t/the-lilly-pilly-on-wattle-street/reminder.ics")
    assert status == 200
    assert "text/calendar" in content_type
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert "RRULE:FREQ=WEEKLY;COUNT=12" in body
    assert body.endswith("END:VCALENDAR\r\n")


def test_logging_a_watering_changes_the_plan(server):
    base, _ = server
    _, before = get_json(base, "/api/trees/the-lilly-pilly-on-wattle-street")
    status, data = post_json(
        base,
        "/api/trees/the-lilly-pilly-on-wattle-street/waterings",
        {"litres": 10, "by_name": "Test", "note": "Unit test"},
    )
    assert status == 201
    after = data["tree"]
    assert after["waterings"][0]["litres"] == 10
    assert after["plan"]["logged_l"] >= before["plan"]["logged_l"] + 10
    assert after["plan"]["dose_l"] <= before["plan"]["dose_l"]


def test_create_and_adopt(server):
    base, _ = server
    status, data = post_json(
        base,
        "/api/trees",
        {
            "name": "Test fig",
            "address": "1 Test Lane",
            "lat": -33.7305,
            "lon": 151.0521,
            "species": "fig",
            "planted_on": "2025-01-15",
            "bed_m2": 1.2,
            "bucket_l": 10,
        },
    )
    assert status == 201
    assert data["slug"] == "test-fig"
    assert data["plan"]["status"] in {"water", "wait", "rain", "watch", "established"}

    status, adopted = post_json(base, "/api/trees/test-fig/adopt", {"adopter": "A neighbour"})
    assert status == 200
    assert adopted["tree"]["adopter"] == "A neighbour"


def test_invalid_tree_is_rejected(server):
    base, _ = server
    status, data = post_json(base, "/api/trees", {"name": ""})
    assert status == 400
    assert "name" in data["error"].lower()


def test_manual_weather_unblocks_a_new_tree(server):
    base, _ = server
    status, data = post_json(
        base,
        "/api/trees",
        {
            "name": "Weatherless tree",
            "lat": -34.0,
            "lon": 151.0,
            "planted_on": "2026-01-01",
        },
    )
    assert status == 201
    assert data["plan"] is None

    status, window = post_json(
        base,
        "/api/weather/manual",
        {"lat": -34.0, "lon": 151.0, "et0_7d": 30, "rain_7d": 2, "rain_next_3d": 0},
    )
    assert status == 200
    assert window["source"] == "manual"

    status, tree = get_json(base, "/api/trees/weatherless-tree")
    assert status == 200
    assert tree["plan"] is not None
    assert tree["plan"]["status"] == "water"


def test_missing_tree_returns_404(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(base + "/api/trees/not-a-tree", timeout=10)
    assert error.value.code == 404