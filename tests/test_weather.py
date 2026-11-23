from datetime import date

from treetrack import weather


def payload():
    return {
        "daily": {
            "time": [
                "2026-11-17",
                "2026-11-18",
                "2026-11-19",
                "2026-11-20",
                "2026-11-21",
                "2026-11-22",
                "2026-11-23",
                "2026-11-24",
                "2026-11-25",
                "2026-11-26",
                "2026-11-27",
            ],
            "et0_fao_evapotranspiration": [3, 4, 5, 2, 3, 4, 5, 6, 7, 8, 9],
            "precipitation_sum": [0, 0, 2, 10, 1, 0, 0, 4, 3, 0, 0],
            "temperature_2m_max": [24] * 11,
            "temperature_2m_min": [14] * 11,
        }
    }


def test_window_sums_the_last_seven_days():
    window = weather.from_payload(payload(), date(2026, 11, 24))
    assert window.et0_7d == 29.0
    assert window.rain_7d == 17.0
    assert window.rain_next_3d == 3.0


def test_window_keeps_the_forecast_days():
    window = weather.from_payload(payload(), date(2026, 11, 24))
    dates = [day["date"] for day in window.days]
    assert dates[0] == "2026-11-18"
    assert dates[-1] == "2026-11-27"


def test_missing_values_are_treated_as_zero():
    data = payload()
    data["daily"]["precipitation_sum"][3] = None
    window = weather.from_payload(data, date(2026, 11, 24))
    assert window.rain_7d == 7.0


def test_manual_window_is_marked_manual():
    window = weather.manual(31.5, 3.2, 0.0, date(2026, 11, 24))
    assert window.source == "manual"
    assert window.et0_7d == 31.5
    assert window.to_dict()["rain_next_3d"] == 0.0


def test_round_trip_to_dict():
    window = weather.manual(12.0, 4.0, 1.0)
    copied = weather.Window.from_dict(window.to_dict())
    assert copied.et0_7d == 12.0
    assert copied.rain_7d == 4.0
    assert copied.source == "manual"