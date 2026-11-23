"""Open-Meteo client and weather windows.

The app needs two numbers: ET0 over the last seven days, and rain over the
same window plus the next three days. A cached copy keeps the app usable when
the network is down. A manual reading is the last fallback.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

API = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = (
    "et0_fao_evapotranspiration",
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
)


class WeatherError(RuntimeError):
    pass


@dataclass(frozen=True)
class Day:
    date: str
    et0: float
    rain: float
    tmax: float | None
    tmin: float | None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "et0": self.et0,
            "rain": self.rain,
            "tmax": self.tmax,
            "tmin": self.tmin,
        }


@dataclass(frozen=True)
class Window:
    et0_7d: float
    rain_7d: float
    rain_next_3d: float
    days: tuple[dict, ...]
    source: str
    fetched_at: str

    def to_dict(self) -> dict:
        return {
            "et0_7d": round(self.et0_7d, 2),
            "rain_7d": round(self.rain_7d, 2),
            "rain_next_3d": round(self.rain_next_3d, 2),
            "days": list(self.days),
            "source": self.source,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Window":
        return cls(
            et0_7d=float(data.get("et0_7d") or 0),
            rain_7d=float(data.get("rain_7d") or 0),
            rain_next_3d=float(data.get("rain_next_3d") or 0),
            days=tuple(data.get("days") or ()),
            source=str(data.get("source") or "cache"),
            fetched_at=str(data.get("fetched_at") or ""),
        )


def _parse_days(payload: dict) -> list[Day]:
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    columns = {name: daily.get(name) or [] for name in DAILY_FIELDS}

    def value(name: str, index: int) -> float | None:
        column = columns[name]
        if index >= len(column):
            return None
        raw = column[index]
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    days: list[Day] = []
    for index, label in enumerate(times):
        et0 = value("et0_fao_evapotranspiration", index)
        rain = value("precipitation_sum", index)
        days.append(
            Day(
                date=str(label)[:10],
                et0=et0 or 0.0,
                rain=rain or 0.0,
                tmax=value("temperature_2m_max", index),
                tmin=value("temperature_2m_min", index),
            )
        )
    return days


def window_from_days(days: Iterable[Day], today: date, source: str, fetched_at: str | None = None) -> Window:
    rows = list(days)
    start = today - timedelta(days=6)
    end = today
    rain_end = today + timedelta(days=3)
    et0_total = 0.0
    rain_total = 0.0
    rain_next = 0.0
    kept: list[dict] = []
    for row in rows:
        try:
            when = date.fromisoformat(row.date)
        except ValueError:
            continue
        if start <= when <= rain_end:
            kept.append(row.to_dict())
        if start <= when <= end:
            et0_total += max(0.0, row.et0)
            rain_total += max(0.0, row.rain)
        elif end < when <= rain_end:
            rain_next += max(0.0, row.rain)
    return Window(
        et0_7d=et0_total,
        rain_7d=rain_total,
        rain_next_3d=rain_next,
        days=tuple(kept),
        source=source,
        fetched_at=fetched_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )


def from_payload(payload: dict, today: date, source: str = "open-meteo") -> Window:
    return window_from_days(_parse_days(payload), today, source)


def fetch(lat: float, lon: float, today: date, timeout: float = 8.0) -> Window:
    query = urllib.parse.urlencode(
        {
            "latitude": f"{float(lat):.4f}",
            "longitude": f"{float(lon):.4f}",
            "daily": ",".join(DAILY_FIELDS),
            "past_days": 7,
            "forecast_days": 7,
            "timezone": "auto",
        }
    )
    request = urllib.request.Request(
        f"{API}?{query}",
        headers={"User-Agent": "treetrack/1.0 (street tree watering)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network, DNS, HTTP, JSON
        raise WeatherError(f"Open-Meteo request failed: {exc}") from exc
    if not payload.get("daily"):
        raise WeatherError("Open-Meteo returned no daily data.")
    return from_payload(payload, today)


def manual(et0_7d: float, rain_7d: float, rain_next_3d: float, today: date | None = None) -> Window:
    today = today or date.today()
    return Window(
        et0_7d=max(0.0, float(et0_7d)),
        rain_7d=max(0.0, float(rain_7d)),
        rain_next_3d=max(0.0, float(rain_next_3d)),
        days=(),
        source="manual",
        fetched_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )