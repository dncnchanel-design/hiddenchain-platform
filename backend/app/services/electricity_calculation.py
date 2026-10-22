"""Confirmed, decimal-based teaching calculations; never an official settlement."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AssistantPlan, AssistantSession, User
from ..security import sha256_json
from .common import add_audit_log

INTENT = "ELECTRICITY_CALCULATION"
VERSION = "electricity-example-v1"
SOURCES = [
    {"title": "电力现货市场基本规则（试行）", "reference": "发改能源规〔2023〕1217号", "url": "https://zfxxgk.ndrc.gov.cn/wap/iteminfo.jsp?id=20272", "scope": "现货市场运行与结算框架"},
    {"title": "电力市场运行基本规则", "reference": "国家发展改革委令第20号（2024年）", "url": "https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20379", "scope": "电力市场运行制度"},
]


def _field(key: str, label: str, unit: str, *aliases: str, minimum: str = "0", maximum: str = "1000000000000") -> dict[str, Any]:
    return {"key": key, "label": label, "unit": unit, "aliases": [label, key, *aliases], "min": minimum, "max": maximum}


SCENARIOS = {
    "zhejiang_spot": {
        "title": "浙江分区电费计算",
        "scope": "合同电费与日前电费相加；网损按申报电量加成。",
        "example": "浙江，2026-05-01：系统电价SMP 420元/MWh；浙北阻塞30元/MWh，浙北网损8元/MWh；浙南阻塞-20元/MWh，浙南网损-5元/MWh。机组日前出清180MWh，中长期合约120MWh，合约价360元/MWh；用户申报电量150MWh，网损分摊率3%。求两区LMP、机组电费和用户购电成本。",
        "fields": [
            _field("smp", "系统电价", "元/MWh", "SMP", "系统边际电价", minimum="-1000000"),
            _field("north_congestion", "浙北阻塞", "元/MWh", r"浙北[^;；。\n]{0,16}?阻塞(?:价格)?", minimum="-1000000"),
            _field("north_loss", "浙北网损", "元/MWh", r"浙北[^;；。\n]{0,40}?网损(?:价格)?", minimum="-1000000"),
            _field("south_congestion", "浙南阻塞", "元/MWh", r"浙南[^;；。\n]{0,16}?阻塞(?:价格)?", minimum="-1000000"),
            _field("south_loss", "浙南网损", "元/MWh", r"浙南[^;；。\n]{0,40}?网损(?:价格)?", minimum="-1000000"),
            _field("day_ahead_energy", "日前出清电量", "MWh", "日前出清", "日前出清电量", "日前电量"),
            _field("contract_energy", "中长期合约电量", "MWh", "中长期合约", "中长期电量", "合约电量"),
            _field("contract_price", "合约电价", "元/MWh", "合约价", "合同电价", minimum="-1000000"),
            _field("user_energy", "用户申报电量", "MWh", "申报电量", "日前申报电量"),
            _field("loss_percent", "网损分摊率", "%", "网损率", maximum="100"),
        ],
        "formulas": ["分区 LMP = SMP + 分区阻塞价格 + 分区网损价格", "机组日前电费 = 日前出清电量 × 浙北 LMP", "中长期合约电费 = 合约电量 × 合约电价", "总电费 = 中长期合约电费 + 机组日前电费", "用户含网损电量 = 申报电量 × (1 + 网损分摊率 ÷ 100)", "用户购电成本 = 含网损电量 × 浙南 LMP"],
    },
    "generation_cost": {
        "title": "发电成本与报价测算",
        "scope": "成本按同一周期汇总；报价根据用户提供的利润率和交易单位成本计算。",
        "example": "计算发电成本和报价底线：设备折旧费10000元，人工成本8000元，固定维护费5000元，管理分摊费3000元；燃料成本45000元，材料成本6000元，水费3000元，可变维护费4000元；实际发电量980MWh，目标利润率8%，交易单位成本5元/MWh。",
        "fields": [
            _field("depreciation", "设备折旧费", "元", "设备折旧", "折旧费", "折旧成本"),
            _field("labor", "人工成本", "元", "人工费"),
            _field("fixed_maintenance", "固定维护费", "元", "固定维护成本"),
            _field("management", "管理分摊费", "元", "管理分摊成本", "管理费"),
            _field("fuel", "燃料成本", "元", "燃料费"),
            _field("material", "材料成本", "元", "材料费"),
            _field("water", "水费", "元", "水成本"),
            _field("variable_maintenance", "可变维护费", "元", "可变维护成本"),
            _field("generation", "实际发电量", "MWh", "发电量", minimum="0.000001"),
            _field("profit_percent", "目标利润率", "%", "利润率", maximum="100"),
            _field("transaction_unit_cost", "交易单位成本", "元/MWh", "交易开户单位成本", "交易单位费用"),
        ],
        "formulas": ["固定成本 = 折旧费 + 人工成本 + 固定维护费 + 管理分摊费", "可变成本 = 燃料成本 + 材料成本 + 水费 + 可变维护费", "总发电成本 = 固定成本 + 可变成本", "单位发电成本 = 总发电成本 ÷ 实际发电量", "测算报价底线 = 单位发电成本 × (1 + 目标利润率 ÷ 100) + 交易单位成本"],
    },
}


def catalog() -> dict[str, Any]:
    return {"version": VERSION, "sources": SOURCES, "scenarios": [{"id": key, **{k: v for k, v in value.items() if k != "fields"}, "fields": [{k: v for k, v in field.items() if k != "aliases"} for field in value["fields"]]} for key, value in SCENARIOS.items()]}


def _session(db: Session, session_id: str, user: User) -> AssistantSession:
    session = db.get(AssistantSession, session_id)
    if session is None or session.user_id != user.user_id or session.org_id != user.org_id or session.entity_type != "electricity_calculation":
        raise LookupError("未找到当前账号的电力计算会话，请新建对话。")
    return session


def _plan(db: Session, plan_id: str, user: User) -> AssistantPlan:
    plan = db.get(AssistantPlan, plan_id)
    if plan is None or plan.intent_code != INTENT:
        raise LookupError("未找到该计算记录。")
    _session(db, plan.session_id, user)
    return plan


def _payload(plan: AssistantPlan) -> dict[str, Any]:
    return {"id": plan.plan_id, "session_id": plan.session_id, "status": plan.status, "state_version": plan.state_version, "created_at": plan.created_at.isoformat(), "capability_state": "DEMO", **plan.plan_json}


def history(db: Session, session_id: str, user: User) -> dict[str, Any]:
    _session(db, session_id, user)
    rows = db.scalars(select(AssistantPlan).where(AssistantPlan.session_id == session_id, AssistantPlan.intent_code == INTENT).order_by(AssistantPlan.created_at.asc())).all()
    return {"items": [_payload(row) for row in rows]}


def cases(db: Session, user: User) -> dict[str, Any]:
    rows = db.scalars(select(AssistantPlan).join(AssistantSession).where(AssistantSession.user_id == user.user_id, AssistantSession.org_id == user.org_id, AssistantPlan.intent_code == INTENT, AssistantPlan.status == "SUCCEEDED", AssistantPlan.plan_json["saved"].as_boolean().is_(True)).order_by(AssistantPlan.created_at.desc()).limit(50)).all()
    return {"items": [_payload(row) for row in rows]}


def _decimal(value: str, field: dict[str, Any]) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"[-+]?\d{1,13}(?:\.\d{1,6})?", value.strip()):
        raise ValueError(f"{field['label']}请填写有效数字，最多6位小数。")
    try:
        number = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{field['label']}不是有效数字。") from exc
    if not Decimal(field["min"]) <= number <= Decimal(field["max"]):
        raise ValueError(f"{field['label']}应在 {field['min']} 至 {field['max']} 之间。")
    return number


def _parse(question: str, scenario: str, inherited: dict[str, str]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    text = unicodedata.normalize("NFKC", question).replace("−", "-").replace("、", ";")
    text = re.sub(r"([+-])\s+(?=\d)", r"\1", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    values, origins, warnings = dict(inherited), {key: "沿用上次已确认参数，请复核" for key in inherited}, []
    for field in SCENARIOS[scenario]["fields"]:
        aliases = [alias if "[^" in alias else re.escape(alias) for alias in field["aliases"]]
        pattern = rf"(?:{'|'.join(aliases)})\s*(?:SMP\s*)?(?:(?:改为|调整为|为|是|=|:|\+)\s*)?([-+]?\d+(?:\.\d+)?)(?![\d.eE])\s*(万)?\s*(元\s*/?\s*(?:MWh|kWh|千瓦时|兆瓦时|度)|MWh|kWh|兆瓦时|千瓦时|度|元|%|成)?"
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        candidates: dict[str, str] = {}
        for match in matches:
            number = Decimal(match[1]) * (10000 if match[2] else 1)
            unit = (match[3] or "").lower().replace(" ", "")
            valid_units = {"元": {"", "元"}, "MWh": {"", "mwh", "kwh", "兆瓦时", "千瓦时", "度"}, "%": {"", "%", "成"}, "元/MWh": {"", "元", "元/mwh", "元mwh", "元/兆瓦时", "元兆瓦时", "元/kwh", "元kwh", "元/千瓦时", "元千瓦时", "元/度", "元度"}}
            if unit not in valid_units[field["unit"]] or re.match(r"(?:[A-Za-z/]|千瓦|兆瓦|亿|万|分)", text[match.end():].lstrip()):
                values.pop(field["key"], None)
                origins.pop(field["key"], None)
                warnings.append(f"{field['label']}的单位未识别，请换算为{field['unit']}后填写。")
                continue
            if field["unit"] == "元/MWh" and unit in {"元/kwh", "元kwh", "元/千瓦时", "元千瓦时", "元/度", "元度"}:
                number *= 1000
            elif field["unit"] == "MWh" and unit in {"kwh", "千瓦时", "度"}:
                number /= 1000
            elif field["unit"] == "%" and not unit:
                warnings.append(f"{field['label']}未写百分号，请按百分数确认；例如3%填写3。")
            elif field["unit"] == "%" and unit == "成":
                number *= 10
            normalized = format(number.normalize(), "f")
            candidates[normalized] = match[0]
        if len(candidates) == 1:
            value, origin = next(iter(candidates.items()))
            try:
                _decimal(value, field)
                values[field["key"]], origins[field["key"]] = value, origin
            except ValueError as exc:
                values.pop(field["key"], None)
                origins.pop(field["key"], None)
                warnings.append(str(exc))
        elif len(candidates) > 1:
            values.pop(field["key"], None)
            origins.pop(field["key"], None)
            warnings.append(f"{field['label']}识别到多个数值，请手动确认。")
    return values, origins, list(dict.fromkeys(warnings))


def prepare(db: Session, user: User, session_id: str, question: str, scenario: str | None, based_on: str | None, idempotency_key: str) -> dict[str, Any]:
    _session(db, session_id, user)
    if not question.strip():
        raise ValueError("请输入计算需求。")
    fingerprint = sha256_json({"question": question, "scenario": scenario, "based_on": based_on})
    existing = db.scalar(select(AssistantPlan).where(AssistantPlan.session_id == session_id, AssistantPlan.idempotency_key == idempotency_key))
    if existing:
        if existing.plan_json.get("request_hash") != fingerprint:
            raise ValueError("请求标识已用于其他问题，请重新提交。")
        return _payload(existing)
    base = _plan(db, based_on, user) if based_on else None
    if base and base.status != "SUCCEEDED":
        raise ValueError("只能沿用已完成计算的参数。")
    if scenario is None:
        if any(word in question.lower() for word in ("浙江", "浙北", "浙南", "lmp", "smp", "日前", "合约")):
            scenario = "zhejiang_spot"
        elif any(word in question for word in ("成本", "报价", "折旧", "利润")):
            scenario = "generation_cost"
        elif base:
            scenario = base.plan_json["scenario"]
        else:
            raise ValueError("暂未匹配到计算公式。请选择浙江分区电费或发电成本报价，并补充相关参数。")
    inherited = base.plan_json.get("parameters", {}) if base and base.plan_json["scenario"] == scenario else {}
    parameters, origins, warnings = _parse(question, scenario, inherited)
    missing = [field["key"] for field in SCENARIOS[scenario]["fields"] if field["key"] not in parameters]
    data = {"question": question, "scenario": scenario, "title": SCENARIOS[scenario]["title"], "scope": SCENARIOS[scenario]["scope"], "parameters": parameters, "origins": origins, "missing": missing, "warnings": warnings, "saved": False, "result": None, "rule_version": VERSION, "sources": SOURCES, "formulas": SCENARIOS[scenario]["formulas"], "request_hash": fingerprint}
    plan = AssistantPlan(session_id=session_id, intent_code=INTENT, status="AWAITING_CONFIRMATION", state_version=1, plan_json=data, plan_hash=sha256_json(data), capability_label="DEMO", source_of_truth=VERSION, idempotency_key=idempotency_key)
    db.add(plan)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(select(AssistantPlan).where(AssistantPlan.session_id == session_id, AssistantPlan.idempotency_key == idempotency_key))
        if replay is None:
            raise
        if replay.plan_json.get("request_hash") != fingerprint:
            raise ValueError("请求标识已用于其他问题，请重新提交。")
        return _payload(replay)
    return _payload(plan)


def _compute(scenario: str, parameters: dict[str, str]) -> dict[str, Any]:
    spec = SCENARIOS[scenario]
    if set(parameters) != {field["key"] for field in spec["fields"]}:
        raise ValueError("计算参数不完整或包含未支持字段，请逐项确认。")
    p = {field["key"]: _decimal(parameters[field["key"]], field) for field in spec["fields"]}
    steps: list[dict[str, str]] = []

    def step(key: str, label: str, expression: str, value: Decimal, unit: str) -> Decimal:
        rounded = value.quantize(Decimal("0.000001") if unit == "MWh" else Decimal("0.01"), rounding=ROUND_HALF_UP)
        steps.append({"key": key, "label": label, "expression": expression, "value": format(rounded, "f"), "unit": unit})
        return value

    with localcontext() as ctx:
        ctx.prec = 50
        if scenario == "zhejiang_spot":
            north = step("north_lmp", "浙北 LMP", f"{p['smp']} + ({p['north_congestion']}) + ({p['north_loss']})", p["smp"] + p["north_congestion"] + p["north_loss"], "元/MWh")
            south = step("south_lmp", "浙南 LMP", f"{p['smp']} + ({p['south_congestion']}) + ({p['south_loss']})", p["smp"] + p["south_congestion"] + p["south_loss"], "元/MWh")
            day = step("day_ahead_fee", "机组日前电费", f"{p['day_ahead_energy']} × {north}", p["day_ahead_energy"] * north, "元")
            contract = step("contract_fee", "中长期合约电费", f"{p['contract_energy']} × {p['contract_price']}", p["contract_energy"] * p["contract_price"], "元")
            step("total_fee", "总电费", f"{contract} + {day}", contract + day, "元")
            energy = step("user_loss_energy", "用户含网损电量", f"{p['user_energy']} × (1 + {p['loss_percent']} ÷ 100)", p["user_energy"] * (1 + p["loss_percent"] / 100), "MWh")
            step("purchase_cost", "用户购电成本", f"{energy} × {south}", energy * south, "元")
        else:
            fixed = step("fixed_cost", "固定成本", " + ".join(str(p[key]) for key in ("depreciation", "labor", "fixed_maintenance", "management")), sum(p[key] for key in ("depreciation", "labor", "fixed_maintenance", "management")), "元")
            variable = step("variable_cost", "可变成本", " + ".join(str(p[key]) for key in ("fuel", "material", "water", "variable_maintenance")), sum(p[key] for key in ("fuel", "material", "water", "variable_maintenance")), "元")
            total = step("total_cost", "总发电成本", f"{fixed} + {variable}", fixed + variable, "元")
            unit = step("unit_cost", "单位发电成本", f"{total} ÷ {p['generation']}", total / p["generation"], "元/MWh")
            step("quote_floor", "测算报价底线", f"({total} ÷ {p['generation']}) × (1 + {p['profit_percent']} ÷ 100) + {p['transaction_unit_cost']}", unit * (1 + p["profit_percent"] / 100) + p["transaction_unit_cost"], "元/MWh")
    return {"steps": steps, "summary": steps, "checks": ["参数完整性与数值范围检查通过", "按用户确认数据和已展示公式计算", "内部保留精度，金额展示按四舍五入保留2位小数", "计算记录与规则版本可追溯"], "policy_check": "仅完成公式及参数校验；地区、交易日期和正式结算适用性仍需业务复核。", "input_source": "用户手动提供并确认，未读取企业连接器数据", "result_hash": sha256_json({"rule": VERSION, "parameters": parameters, "steps": steps})}


def calculate(db: Session, user: User, plan_id: str, parameters: dict[str, str], confirmed: bool, state_version: int) -> dict[str, Any]:
    plan = _plan(db, plan_id, user)
    if not confirmed:
        raise ValueError("请先确认计算口径和所有输入数据。")
    if plan.status == "SUCCEEDED":
        if plan.plan_json["parameters"] == parameters:
            return _payload(plan)
        raise ValueError("已完成记录不能改写，请继续提问发起新计算。")
    if plan.state_version != state_version:
        raise ValueError("计算记录已更新，请刷新后重试。")
    result = _compute(plan.plan_json["scenario"], parameters)
    origins = {key: plan.plan_json["origins"].get(key, "用户填写") if value == plan.plan_json["parameters"].get(key) else "用户手动填写并确认" for key, value in parameters.items()}
    data = {**plan.plan_json, "parameters": parameters, "origins": origins, "missing": [], "confirmed": True, "result": result}
    # Atomic version claim prevents concurrent confirmations from overwriting results.
    claimed = db.execute(update(AssistantPlan).where(AssistantPlan.plan_id == plan_id, AssistantPlan.state_version == state_version, AssistantPlan.status == "AWAITING_CONFIRMATION").values(plan_json=data, plan_hash=sha256_json(data), status="SUCCEEDED", state_version=state_version + 1))
    if claimed.rowcount != 1:
        db.rollback()
        raise ValueError("计算记录已更新，请刷新后重试。")
    add_audit_log(db, action="ELECTRICITY_EXAMPLE_CALCULATED", target_type="ASSISTANT_PLAN", target_id=plan_id, result="SUCCESS", user=user, details={"rule_version": VERSION, "result_hash": result["result_hash"], "capability_state": "DEMO"})
    db.commit()
    db.refresh(plan)
    return _payload(plan)


def save_case(db: Session, user: User, plan_id: str) -> dict[str, Any]:
    plan = _plan(db, plan_id, user)
    if plan.status != "SUCCEEDED":
        raise ValueError("请先确认数据并完成计算，再保存案例。")
    if not plan.plan_json.get("saved"):
        plan.plan_json = {**plan.plan_json, "saved": True}
        plan.plan_hash = sha256_json(plan.plan_json)
        plan.state_version += 1
        add_audit_log(db, action="ELECTRICITY_EXAMPLE_SAVED", target_type="ASSISTANT_PLAN", target_id=plan_id, result="SUCCESS", user=user, details={"capability_state": "DEMO"})
        db.commit()
    return _payload(plan)
