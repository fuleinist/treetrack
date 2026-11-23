from datetime import date

from treetrack import model

TODAY = date(2026, 11, 24)
YOUNG = date(2026, 6, 1)  # about six months


def plan(**overrides):
    values = dict(
        today=TODAY,
        planted_on=YOUNG,
        et0_7d_mm=35.0,
        rain_7d_mm=0.0,
        rain_next_3d_mm=0.0,
        bed_m2=1.0,
        species="generic",
        mulch="none",
        bucket_l=10.0,
        logged_l=0.0,
    )
    values.update(overrides)
    return model.weekly_plan(**values)


def test_base_dose_rounds_up_to_buckets():
    result = plan()
    assert result.demand_l == 35.0
    assert result.dose_l == 40.0
    assert result.buckets == 4
    assert result.status == "water"
    assert "40 L" in result.reason


def test_logged_water_reduces_the_dose():
    result = plan(logged_l=10.0)
    assert result.net_l == 25.0
    assert result.dose_l == 30.0
    assert result.buckets == 3


def test_rain_covers_the_demand():
    result = plan(et0_7d_mm=10.0, rain_7d_mm=40.0)
    assert result.status == "rain"
    assert result.dose_l == 0
    assert round(result.rain_credit_l, 1) == 30.4


def test_forecast_rain_holds_the_watering():
    result = plan(rain_next_3d_mm=20.0)
    assert result.status == "wait"
    assert result.dose_l == 0


def test_small_gap_is_a_watch():
    result = plan(et0_7d_mm=2.0)
    assert result.status == "watch"
    assert result.dose_l == 0


def test_established_tree_needs_no_water_in_a_small_gap():
    result = plan(planted_on=date(2018, 3, 1), et0_7d_mm=20.0)
    assert result.status == "established"
    assert result.dose_l == 0


def test_age_factor_steps_down():
    assert model.age_factor(0.4) == 1.0
    assert model.age_factor(1.5) == 0.8
    assert model.age_factor(2.5) == 0.55
    assert model.age_factor(4.0) == 0.3
    assert model.age_factor(9.0) == 0.15


def test_mulch_reduces_demand():
    bare = plan(mulch="none")
    covered = plan(mulch="woodchip")
    assert covered.demand_l < bare.demand_l
    assert covered.demand_l == 31.5


def test_species_factor_changes_demand():
    gum = plan(species="eucalyptus")
    plane = plan(species="plane")
    assert gum.demand_l < plane.demand_l
    assert gum.demand_l == 21.0
    assert plane.demand_l == 36.75


def test_unknown_species_falls_back_to_generic():
    result = plan(species="mystery tree")
    assert result.species_factor == 1.0


def test_cap_limits_a_huge_dose():
    result = plan(bed_m2=10.0, et0_7d_mm=200.0)
    assert result.capped is True
    assert result.dose_l == 450.0


def test_litres_in_window_counts_recent_entries_only():
    entries = [
        {"on_date": TODAY.isoformat(), "litres": 10},
        {"on_date": "2026-11-20", "litres": 5},
        {"on_date": "2026-11-01", "litres": 50},
    ]
    assert model.litres_in_window(entries, TODAY) == 15.0


def test_plan_is_json_ready():
    data = plan().to_dict()
    assert data["dose_l"] == 40.0
    assert data["status"] == "water"
    assert data["next_check"] == "2026-12-01"