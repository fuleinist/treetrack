# treetrack — SPEC

## One line

A weekly water dose for one adopted street tree, with a printable QR sign so neighbours can help.

## Problem

A young street tree needs about 20 litres a week for its first two summers. Nobody tells the resident. The tree dies in year three, and the council counts the loss against its canopy target.

Watering advice is generic. Rain, heat and tree age change the dose every week. A resident needs one number and one action.

## Product boundary

`treecare` is a volunteer roster. It ranks many trees and builds a walking run for a crew.

`treetrack` is a resident adoption page. One person adopts one tree. The app gives that tree a weekly dose, a reminder and a public sign. Neighbours can scan the sign and log a watering.

The shared part is the water balance. The users and the surface are different.

## Users

1. A resident who adopts a street tree near their home.
2. A neighbour who scans the sign and waters the tree once.
3. A community group that runs an adoption program for one street.

## MVP features

- **Tree record.** Name, address, latitude and longitude, species, planting date, trunk size, bed area, mulch and bucket size.
- **Species presets.** A water factor for common street trees. A generic fallback.
- **Weather window.** Seven days of ET0 and rain, plus a three-day rain forecast, from Open-Meteo. Cached for three hours.
- **Manual weather.** The user can enter ET0 and rain when the network is down. The plan still works.
- **Water balance.** Demand is ET0 times bed area times species factor times age factor. Rain and logged waterings are credits. The dose rounds up to whole buckets.
- **Weekly action.** One status: water now, wait for rain, rain covered, watch, or established. Each status has one plain reason.
- **Watering log.** Date, litres, name and note. The log is public.
- **Public tree page.** Dose, status, last watering, adoption form and history.
- **Printable sign.** A4 page with tree name, dose, adoption call and a scannable QR code.
- **Calendar reminder.** An ICS file with a weekly event for 12 weeks.
- **Demo seed.** Six trees on one street, so the app shows value on first run.

## Acceptance criteria

1. `python -m treetrack.server --demo` serves the app on port 8765 with six seeded trees.
2. The dashboard shows each tree with a status chip and a litre dose.
3. A tree with 35 mm ET0 in seven days, a 1 m² bed, factor 1.0 and age under one year returns a 40 L dose before rain.
4. Ten litres logged this week reduces the next dose by 10 L.
5. A tree with rain above demand returns status `rain` and a 0 L dose.
6. The sign page contains an SVG QR code. A standard decoder reads the tree URL from it.
7. The ICS file is valid text with CRLF line endings and one weekly event.
8. All tests pass with `python -m pytest`.
9. No network is required for the demo when manual weather is set.

## Data sources

- Open-Meteo forecast API: `et0_fao_evapotranspiration` and `precipitation_sum`, past 7 days and next 7 days. Free, no key.
- Open-Meteo geocoding is not used. The user enters a label and coordinates.
- Species water factors follow published street-tree establishment guidance. The values are advisory, not a promise of survival.

## Out of scope

- Council tree inventories and OSM import.
- Web push. The ICS file covers reminders.
- Accounts and login. Adoption is a public label, not an identity.
- Irrigation hardware control.

## Risks and limits

- The water balance is an estimate. The app shows every input and lets the user correct the weather.
- Rain is uneven. The app shows the source window and the rain credit.
- A tree may get water from a lawn or a leak. The user can log extra water at any time.
- The app never promises survival. It gives a dose.

## Tech stack

Python 3.11 standard library HTTP server, SQLite, vanilla JavaScript and CSS. No runtime package installs. A pure-Python QR encoder with no dependencies.