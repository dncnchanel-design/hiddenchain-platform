"""Immutable, reproducible enterprise-side synthetic data for the v2 seed."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any


GENERATOR_VERSION = "hiddenchain-demo-seed-v2"
PERIOD_START = date(2021, 1, 1)
PERIOD_END = date(2026, 9, 30)
REGIONS = ("东部片区", "西部片区", "南部片区", "北部片区")
REGION_FACTORS = (1.08, 0.91, 1.00, 1.03)
UNITS = {
    "electricity": {"generation": "MWh", "supply": "MWh", "load": "MW", "price": "元/MWh"},
    "coal": {"production": "吨", "supply": "吨", "consumption": "吨", "inventory": "吨", "transport": "吨", "price": "元/吨"},
    "heat": {"supply": "GJ", "load": "MW", "fuel": "吨标准煤", "loss": "%", "supply_temperature": "℃", "return_temperature": "℃", "price": "元/GJ"},
    "gas": {"supply": "万立方米", "consumption": "万立方米", "storage": "万立方米", "pipeline_flow": "万立方米/日", "pressure": "MPa", "price": "元/立方米"},
    "oil": {"production": "吨", "refining": "吨", "inventory": "吨", "transport": "吨", "sales": "吨", "price": "元/吨"},
}
HOURLY_RESOURCES = frozenset({("electricity", "supply"), ("electricity", "load"), ("heat", "supply"), ("heat", "load"), ("gas", "supply")})
SyntheticRow = tuple[str, str, int | None, str, str, float, str]


def _validate(domain: str, resource: str, unit: str) -> None:
    if UNITS.get(domain, {}).get(resource) != unit:
        raise ValueError("Synthetic resource/unit is not part of the fixed catalog")


def record_count(domain: str, resource: str, start: date = PERIOD_START, end: date = PERIOD_END) -> int:
    if resource not in UNITS.get(domain, {}) or not PERIOD_START <= start <= end <= PERIOD_END:
        raise ValueError("Synthetic resource or period is outside the immutable seed")
    return ((end - start).days + 1) * len(REGIONS) * (25 if (domain, resource) in HOURLY_RESOURCES else 1)


def manifest(connector_id: str, organization_label: str, domain: str, resource: str, unit: str) -> dict[str, Any]:
    _validate(domain, resource, unit)
    return {
        "generator_version": GENERATOR_VERSION,
        "connector_id": connector_id,
        "organization_label": organization_label,
        "energy_domain": domain,
        "resource_id": resource,
        "unit": unit,
        "period_start": PERIOD_START.isoformat(),
        "period_end": PERIOD_END.isoformat(),
        "regions": list(REGIONS),
        "daily_rows_per_day": len(REGIONS),
        "hourly_available": (domain, resource) in HOURLY_RESOURCES,
        "hourly_semantics": "daily_mean" if unit == "MW" else "daily_total",
        "value_decimals": 6,
        "record_count": record_count(domain, resource),
    }


def fingerprint(description: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(description, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_bytes(row: SyntheticRow) -> bytes:
    """Canonical content hash input, independent of SQLite's float formatting."""
    resource, day, hour, region, organization, value, unit = row
    return (json.dumps([resource, day, hour, region, organization, f"{value:.6f}", unit], ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _daily_values(domain: str, current: date, source_factor: float, phase: float, region: int) -> dict[str, float]:
    days_in_year = (date(current.year + 1, 1, 1) - date(current.year, 1, 1)).days
    day = (current - date(current.year, 1, 1)).days
    years = current.year - 2021 + day / days_in_year
    winter = math.cos(math.tau * (day - 14) / days_in_year)
    summer = math.cos(math.tau * (day - 198) / days_in_year)
    cold = max(0.0, winter)
    noise = 1 + 0.018 * math.sin((current.toordinal() + phase) * math.tau / 17) + 0.009 * math.cos(day * math.tau / 43)
    workday = 1.025 if current.weekday() < 5 else 0.9375
    scale = source_factor * REGION_FACTORS[region]
    growth = 1.022 ** years
    if domain == "electricity":
        demand = 1320 * scale * growth * workday * noise * (1 + 0.10 * winter + 0.13 * max(0.0, summer))
        supply = demand * 24
        return {"load": demand, "supply": supply, "generation": supply * (0.96 + 0.025 * math.sin(day * math.tau / 91)), "price": 410 * (1.012 ** years) * (0.98 + region * 0.015) * noise * (1 + 0.12 * cold + 0.08 * max(0.0, summer))}
    if domain == "coal":
        production = 10400 * scale * growth * workday * noise * (1 + 0.09 * winter)
        return {"production": production, "supply": production * 0.97, "consumption": production * (0.94 + 0.025 * winter), "inventory": 178000 * scale * growth * (1 - 0.08 * winter + 0.025 * math.sin(day * math.tau / 93)), "transport": production * 0.985, "price": 835 * (1.009 ** years) * noise * (1 + 0.16 * winter) * (0.98 + region * 0.015)}
    if domain == "heat":
        load = 1020 * scale * growth * (0.18 + 0.82 * cold) * noise * (0.99 + 0.01 * workday)
        supply = load * 86.4  # MW average × 86.4 = GJ/day.
        loss = 5.2 + 2.3 * (1 - cold) + 0.35 * math.sin(day * math.tau / 31)
        return {"load": load, "supply": supply, "fuel": supply / (29.3076 * 0.9) * (1 + loss / 100), "loss": loss, "supply_temperature": 62 + 30 * cold + region * 0.4, "return_temperature": 38 + 18 * cold + region * 0.3, "price": 63 * (1.008 ** years) * (1 + 0.035 * winter) * (0.99 + region * 0.01)}
    if domain == "gas":
        supply = 185 * scale * growth * workday * noise * (1 + 0.32 * winter)
        return {"supply": supply, "consumption": supply * 0.965, "storage": 8700 * scale * growth * (1 - 0.17 * winter + 0.025 * math.sin(day * math.tau / 73)), "pipeline_flow": supply * 0.94, "pressure": 4.7 + 0.45 * cold + 0.12 * math.sin(day * math.tau / 29) + region * 0.06, "price": 2.85 * (1.009 ** years) * (1 + 0.18 * winter) * (0.99 + region * 0.01)}
    production = 8300 * scale * growth * workday * noise * (1 + 0.045 * winter)
    refining = production * 1.48 * (1 + 0.035 * summer)
    return {"production": production, "refining": refining, "inventory": 213000 * scale * growth * (1 + 0.06 * math.sin(day * math.tau / 97)), "transport": refining * 0.96, "sales": refining * 0.915, "price": 4860 * (1.011 ** years) * noise * (1 + 0.08 * winter + 0.06 * math.sin(years * math.tau / 2.7))}


def _hourly_values(daily: float, current: date, *, mean: bool) -> Iterator[float]:
    weights = [0.68 + 0.30 * math.exp(-((hour - 9) / 3.0) ** 2) + 0.48 * math.exp(-((hour - 19) / 3.2) ** 2) for hour in range(24)]
    if current.weekday() >= 5:
        weights = [weight * (0.96 if 7 <= hour <= 16 else 1.03) for hour, weight in enumerate(weights)]
    target = round(daily * (24 if mean else 1), 6)
    total_weight = sum(weights)
    used = 0.0
    for hour, weight in enumerate(weights):
        value = round(target - used, 6) if hour == 23 else round(target * weight / total_weight, 6)
        used += value
        yield value


def iter_records(
    connector_id: str,
    organization_label: str,
    domain: str,
    resource: str,
    unit: str,
    *,
    start: date = PERIOD_START,
    end: date = PERIOD_END,
) -> Iterator[SyntheticRow]:
    """Yield bounded-memory rows; energy hours sum to the day, MW hours average to it."""
    _validate(domain, resource, unit)
    record_count(domain, resource, start, end)
    source_seed = int(hashlib.sha256(f"{GENERATOR_VERSION}:{connector_id}".encode()).hexdigest()[:12], 16)
    source_factor = 0.94 + source_seed % 1200 / 10000
    phase = source_seed % 997
    current = start
    while current <= end:
        for index, region in enumerate(REGIONS):
            value = round(_daily_values(domain, current, source_factor, phase, index)[resource], 6)
            organization = f"{organization_label}{region}"
            yield resource, current.isoformat(), None, region, organization, value, unit
            if (domain, resource) in HOURLY_RESOURCES:
                for hour, hourly in enumerate(_hourly_values(value, current, mean=unit == "MW")):
                    yield resource, current.isoformat(), hour, region, organization, hourly, unit
        current += timedelta(days=1)
