"""Explicit query date ranges must never collapse to their first date."""
from datetime import date, datetime

import pytest

from app.database import SessionLocal, engine
from app.models import Base, Organization, User
from app.routers import trusted_query


@pytest.fixture(autouse=True)
def reset_test_database(monkeypatch):
    # Date parsing is pure; only the handler regression below needs metadata.
    monkeypatch.setattr(trusted_query, "utc_now", lambda: datetime(2026, 10, 24, 12))


@pytest.fixture
def handler_records():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(Organization(org_id="owner", org_name="owner", org_type="GENERATOR", energy_domain="electricity"))
        db.flush()
        user = User(user_id="owner", username="owner", org_id="owner", display_name="owner", role_code="GENERATOR", permissions_json=["CREATE_COMPUTE_TASK"], password_hash="unused")
        db.add(user)
        db.commit()
        yield db, user
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.mark.parametrize(("text", "start", "end"), [
    ("2026年9月18日至2026年9月20日", "2026-09-18", "2026-09-20"),
    ("2026年9月18日至9月20日", "2026-09-18", "2026-09-20"),
    ("2026年9月18日至20日", "2026-09-18", "2026-09-20"),
    ("2026年9月18到20日", "2026-09-18", "2026-09-20"),
    ("2026 年 9 月 18 日 至 2026 年 9 月 20 日", "2026-09-18", "2026-09-20"),
    ("2026年9月30日至10月2日", "2026-09-30", "2026-10-02"),
    ("2025年12月31日至2026年1月2日", "2025-12-31", "2026-01-02"),
    ("9月18日至20日", "2026-09-18", "2026-09-20"),
    ("9月18日到9月20日", "2026-09-18", "2026-09-20"),
    ("2026-09-18至2026-09-20", "2026-09-18", "2026-09-20"),
    ("2026/09/18到2026/09/20", "2026-09-18", "2026-09-20"),
    ("2026年9月18日—20日", "2026-09-18", "2026-09-20"),
    ("2026年9月18日～20日", "2026-09-18", "2026-09-20"),
    ("2026年9月18日-20日", "2026-09-18", "2026-09-20"),
    ("2021年1月至2026年9月", "2021-01-01", "2026-09-30"),
    ("2026年8月至9月", "2026-08-01", "2026-09-30"),
    ("2024年2月1日至29日", "2024-02-01", "2024-02-29"),
    ("2026年9月18日", "2026-09-18", "2026-09-18"),
    ("2026-09-18", "2026-09-18", "2026-09-18"),
    ("9月18日", "2026-09-18", "2026-09-18"),
    ("2026年9月", "2026-09-01", "2026-09-30"),
    ("6月份", "2026-06-01", "2026-06-30"),
    ("上个月", "2026-09-01", "2026-09-30"),
    ("最近3天", "2026-10-22", "2026-10-24"),
])
def test_explicit_ranges_preserve_every_endpoint(text, start, end):
    assert trusted_query._manual_period(f"查询{text}的电力发电量平均值") == (date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize("text", [
    "2026年9月31日至2026年10月2日",
    "2026年2月28日至29日",
    "2026年9月20日至18日",
    "2026年12月31日至1月2日",
    "2026年9月18日至",
    "2026年9月18日与2026年9月20日",
    "2026年9月至2026年13月",
    "2026年9月18日至20日或22日",
])
def test_invalid_ambiguous_or_unfinished_ranges_require_explicit_input(text):
    assert trusted_query._manual_period(f"查询{text}的电力发电量平均值") == (None, None)


def test_browser_load_question_retains_its_domain_resource_function_and_iso_period():
    parsed = trusted_query._manual_parse("查询2026-09-21至2026-09-23的用电负荷平均值，用于运行监测")
    assert parsed.energy_domain == "electricity" and parsed.resource == "load" and parsed.function == "average"
    assert parsed.start_date == date(2026, 9, 21) and parsed.end_date == date(2026, 9, 23)


@pytest.mark.parametrize(("relative_year", "expected_year"), [("今年", 2026), ("去年", 2025), ("前年", 2024), ("明年", 2027)])
def test_relative_year_words_bind_to_the_reference_year(relative_year, expected_year):
    assert trusted_query._manual_period(f"查询{relative_year}6月的电力发电量平均值") == (date(expected_year, 6, 1), date(expected_year, 6, 30))
    assert trusted_query._manual_period(f"查询{relative_year}9月18日至20日的用电负荷平均值") == (date(expected_year, 9, 18), date(expected_year, 9, 20))


@pytest.mark.parametrize("relative_year", ["往年", "前几年", "去年和今年", "后年", "大前年"])
def test_unsupported_or_multiple_year_words_do_not_guess_the_current_year(relative_year):
    assert trusted_query._manual_period(f"查询{relative_year}6月的电力发电量平均值") == (None, None)


def test_reported_browser_question_reaches_both_dates_in_the_manual_preview(monkeypatch, handler_records):
    def unavailable(**_kwargs):
        raise trusted_query.DeepSeekUnavailable("service unavailable")
    monkeypatch.setattr(trusted_query, "translate_trusted_space_query", unavailable)
    db, user = handler_records
    response = trusted_query.parse_question(trusted_query.ParseRequest(question="查询2026年9月18日至2026年9月20日的本方发电量平均值，用于运行监测"), user, db)
    assert response["provider"] == "manual_rules" and response["ready"] is True
    assert response["start_date"] == "2026-09-18" and response["end_date"] == "2026-09-20"
