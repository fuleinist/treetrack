"""Weekly water balance for a young street tree.

The model is deliberately small and auditable. Every input is visible in the
API response, so a resident can see why the dose changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

# One millimetre of water over one square metre is one litre.
RAIN_INTERCEPTION_MM = 2.0
RAIN_CAPTURE = 0.8
MIN_DOSE_FRACTION = 0.25
ESTABLISHED_YEARS = 5.0
MAX_WEEKLY_L_PER_M2 = 45.0


@dataclass(frozen=True)
class Species:
    key: str
    label: str
    factor: float
    note: str


SPECIES: tuple[Species, ...] = (
    Species("generic", "Generic street tree", 1.0, "A safe default when the species is unknown."),
    Species("plane", "London plane", 1.05, "Thirsty in summer. Wide crown."),
    Species("eucalyptus", "Eucalyptus", 0.6, "Drought tolerant after establishment."),
    Species("lilly-pilly", "Lilly pilly", 0.85, "Evergreen. Keep water steady in the first summer."),
    Species("crepe-myrtle", "Crepe myrtle", 0.8, "Heat tolerant. Avoid wet feet."),
    Species("jacaranda", "Jacaranda", 0.9, "Needs water while young."),
    Species("citrus", "Citrus", 0.9, "Steady moisture. Never let the root ball dry out."),
    Species("fig", "Port Jackson fig", 1.1, "Large tree. Water well in the first two years."),
)

MULCH_FACTOR = {
    "none": 1.0,
    "compost": 0.95,
    "woodchip": 0.9,
    "gravel": 1.0,
}


def get_species(value: str | None) -> Species:
    """Resolve a species key or label. Fall back to the generic tree."""
    if not value:
        return SPECIES[0]
    needle = value.strip().lower().replace("_", "-")
    for item in SPECIES:
        if needle in (item.key, item.label.lower()):
            return item
    for item in SPECIES:
        if needle and (needle in item.key or needle in item.label.lower()):
            return item
    return SPECIES[0]


def age_years(planted_on: date, today: date) -> float:
    """Years since planting, never negative."""
    return max(0.0, (today - planted_on).days / 365.25)


def age_factor(years: float) -> float:
    """Young trees need more water. An established tree needs little."""
    if years < 1:
        return 1.0
    if years < 2:
        return 0.8
    if years < 3:
        return 0.55
    if years < ESTABLISHED_YEARS:
        return 0.3
    return 0.15


def mulch_factor(mulch: str | None) -> float:
    return MULCH_FACTOR.get((mulch or "none").strip().lower(), 1.0)


@dataclass(frozen=True)
class WaterPlan:
    demand_l: float
    rain_credit_l: float
    logged_l: float
    net_l: float
    dose_l: float
    buckets: int
    status: str
    reason: str
    next_check: date
    age_years: float
    age_factor: float
    species_factor: float
    mulch_factor: float
    capped: bool

    def to_dict(self) -> dict:
        return {
            "demand_l": round(self.demand_l, 1),
            "rain_credit_l": round(self.rain_credit_l, 1),
            "logged_l": round(self.logged_l, 1),
            "net_l": round(self.net_l, 1),
            "dose_l": round(self.dose_l, 1),
            "buckets": self.buckets,
            "status": self.status,
            "reason": self.reason,
            "next_check": self.next_check.isoformat(),
            "age_years": round(self.age_years, 2),
            "age_factor": self.age_factor,
            "species_factor": self.species_factor,
            "mulch_factor": self.mulch_factor,
            "capped": self.capped,
        }


def weekly_plan(
    *,
    today: date,
    planted_on: date,
    et0_7d_mm: float,
    rain_7d_mm: float,
    rain_next_3d_mm: float,
    bed_m2: float,
    species: str | None = None,
    mulch: str = "none",
    bucket_l: float = 10.0,
    logged_l: float = 0.0,
) -> WaterPlan:
    """Return this week's dose and the one action to take."""
    kind = get_species(species)
    years = age_years(planted_on, today)
    young = age_factor(years)
    mulch_use = mulch_factor(mulch)
    bed = max(0.1, float(bed_m2))
    bucket = max(1.0, float(bucket_l))

    demand = max(0.0, float(et0_7d_mm)) * bed * kind.factor * young * mulch_use
    rain_credit = max(0.0, float(rain_7d_mm) - RAIN_INTERCEPTION_MM) * bed * RAIN_CAPTURE
    logged = max(0.0, float(logged_l))
    net = demand - rain_credit - logged

    if net <= 0.5:
        return WaterPlan(
            demand_l=demand,
            rain_credit_l=rain_credit,
            logged_l=logged,
            net_l=net,
            dose_l=0.0,
            buckets=0,
            status="rain",
            reason="Rain and logged water cover this week's demand.",
            next_check=today + timedelta(days=7),
            age_years=years,
            age_factor=young,
            species_factor=kind.factor,
            mulch_factor=mulch_use,
            capped=False,
        )

    if years >= ESTABLISHED_YEARS and net < bucket:
        return WaterPlan(
            demand_l=demand,
            rain_credit_l=rain_credit,
            logged_l=logged,
            net_l=net,
            dose_l=0.0,
            buckets=0,
            status="established",
            reason="This tree is established. Deep water only in a long dry spell.",
            next_check=today + timedelta(days=14),
            age_years=years,
            age_factor=young,
            species_factor=kind.factor,
            mulch_factor=mulch_use,
            capped=False,
        )

    if net < MIN_DOSE_FRACTION * bucket:
        return WaterPlan(
            demand_l=demand,
            rain_credit_l=rain_credit,
            logged_l=logged,
            net_l=net,
            dose_l=0.0,
            buckets=0,
            status="watch",
            reason="The gap is small. Check again in three days.",
            next_check=today + timedelta(days=3),
            age_years=years,
            age_factor=young,
            species_factor=kind.factor,
            mulch_factor=mulch_use,
            capped=False,
        )

    if float(rain_next_3d_mm) >= max(4.0, net / bed / 2.0):
        return WaterPlan(
            demand_l=demand,
            rain_credit_l=rain_credit,
            logged_l=logged,
            net_l=net,
            dose_l=0.0,
            buckets=0,
            status="wait",
            reason="Rain is forecast in three days. Hold the water.",
            next_check=today + timedelta(days=3),
            age_years=years,
            age_factor=young,
            species_factor=kind.factor,
            mulch_factor=mulch_use,
            capped=False,
        )

    cap = MAX_WEEKLY_L_PER_M2 * bed * max(0.5, kind.factor)
    raw = ceil(net / bucket) * bucket
    capped = raw > cap
    dose = min(raw, cap)
    buckets = max(1, int(round(dose / bucket)))
    return WaterPlan(
        demand_l=demand,
        rain_credit_l=rain_credit,
        logged_l=logged,
        net_l=net,
        dose_l=dose,
        buckets=buckets,
        status="water",
        reason=f"Give {dose:.0f} L in {buckets} bucket{'s' if buckets != 1 else ''} before the week ends.",
        next_check=today + timedelta(days=7),
        age_years=years,
        age_factor=young,
        species_factor=kind.factor,
        mulch_factor=mulch_use,
        capped=capped,
    )


def litres_in_window(waterings: list[dict], today: date, days: int = 7) -> float:
    """Sum waterings from the last `days` days, including today."""
    start = today - timedelta(days=days - 1)
    total = 0.0
    for item in waterings:
        raw = item.get("on_date") or item.get("date")
        if not raw:
            continue
        try:
            when = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if start <= when <= today:
            total += float(item.get("litres") or 0)
    return total