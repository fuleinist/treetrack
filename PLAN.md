# treetrack — PLAN

## Cycle 1 — core model

1. Write `treetrack/model.py`. Add species presets, age factor, mulch factor and the weekly plan.
2. Write `tests/test_model.py`. Cover the four acceptance cases.

## Cycle 2 — data and weather

3. Write `treetrack/db.py`. Add the schema, tree records, watering log and weather cache.
4. Write `treetrack/weather.py`. Add the Open-Meteo client, the three-hour cache and the manual fallback.
5. Add tests with a fake weather window.

## Cycle 3 — QR and pages

6. Write `treetrack/qr.py`. Byte mode, versions 1 to 5, error correction L.
7. Validate the QR with OpenCV. Decode a rendered PNG and compare the payload.
8. Write `treetrack/server.py`. Add JSON routes, the sign page and the ICS export.
9. Write the dashboard, tree page and styles.

## Cycle 4 — proof

10. Run the demo seed. Check the dashboard, tree page and sign page in a browser.
11. Capture screenshots. Add the logo.
12. Write the README. Commit and push.