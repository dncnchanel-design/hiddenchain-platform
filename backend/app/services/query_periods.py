"""Calendar comparison periods derived by the platform, never by the caller."""
from __future__ import annotations

from calendar import monthrange
from datetime import date


def comparison_period(function: str, start: date, end: date) -> tuple[date, date] | None:
    if function not in {"yoy", "mom"}:
        return None
    months = 12 if function == "yoy" else 1

    def shift(day: date, *, month_end: bool = False) -> date:
        year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
        month += 1
        last = monthrange(year, month)[1]
        return date(year, month, last if month_end else min(day.day, last))

    full_months = start.day == 1 and end.day == monthrange(end.year, end.month)[1]
    return shift(start), shift(end, month_end=full_months)


def comparison_fields(function: str, start: date, end: date) -> dict[str, str]:
    period = comparison_period(function, start, end)
    return {"comparison_start_date": period[0].isoformat(), "comparison_end_date": period[1].isoformat()} if period else {}
