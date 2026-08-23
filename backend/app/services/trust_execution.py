from __future__ import annotations

import json
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import DataUpload, DidIdentity, Signature, TrustedExecutionReview, User, utc_now
from ..security import sha256_json, sign_value
from .adapters import LocalEvidenceLedgerAdapter
from .common import add_audit_log, trace_id
from .credentials import JsonLdCredentialAdapter
from .lineage import emit_run_event, input_dataset
from .vault import LocalDomainVault


class PolicyAction(StrEnum):
    PROHIBIT = "PROHIBIT"
    DELAY = "DELAY"
    AGGREGATE = "AGGREGATE"
    COMPUTE_ONLY = "COMPUTE_ONLY"
    ALLOW = "ALLOW"


SENSITIVITY_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
METRIC_QUANTUM = Decimal("0.0001")


def _execution_profile(action: PolicyAction, permitted: bool, rule: dict[str, Any]) -> dict[str, Any]:
    """Map a usage decision to an honest execution profile.

    The local adapter can aggregate and reconcile synthetic/test-node data, but
    it cannot prove cross-domain non-export. COMPUTE_ONLY therefore records the
    local fallback and the external protocols required before a production claim.
    """
    if not permitted:
        return {
            "execution_method": "BLOCKED",
            "implementation_status": "NOT_EXECUTED",
            "requires_external_runtime": False,
            "candidate_methods": [],
        }

    explicit_method = str(rule.get("execution_method", "")).strip()
    if explicit_method:
        return {
            "execution_method": explicit_method,
            "implementation_status": str(rule.get("implementation_status", "NOT_CONFIGURED")),
            "requires_external_runtime": bool(rule.get("requires_external_runtime", True)),
            "candidate_methods": [str(item) for item in rule.get("candidate_methods", [])],
        }

    profiles: dict[PolicyAction, dict[str, Any]] = {
        PolicyAction.ALLOW: {
            "execution_method": "DIRECT_CONTROLLED_API",
            "implementation_status": "AVAILABLE_IN_LOCAL_ADAPTER",
            "requires_external_runtime": False,
            "candidate_methods": [],
        },
        PolicyAction.DELAY: {
            "execution_method": "DELAYED_CONTROLLED_RELEASE",
            "implementation_status": "AVAILABLE_IN_LOCAL_ADAPTER",
            "requires_external_runtime": False,
            "candidate_methods": [],
        },
        PolicyAction.AGGREGATE: {
            "execution_method": "LOCAL_CONTROLLED_AGGREGATION",
            "implementation_status": "AVAILABLE_IN_LOCAL_ADAPTER",
            "requires_external_runtime": False,
            "candidate_methods": [],
        },
        PolicyAction.COMPUTE_ONLY: {
            "execution_method": "LOCAL_CONTROLLED_COMPUTE",
            "implementation_status": "TEST_FIXTURE_ONLY",
            "requires_external_runtime": True,
            "candidate_methods": ["PSI_MPC", "TEE_CONFIDENTIAL_COMPUTE"],
        },
        PolicyAction.PROHIBIT: {
            "execution_method": "BLOCKED",
            "implementation_status": "NOT_EXECUTED",
            "requires_external_runtime": False,
            "candidate_methods": [],
        },
    }
    profile = dict(profiles[action])
    if rule.get("candidate_methods"):
        profile["candidate_methods"] = [str(item) for item in rule["candidate_methods"]]
    if "requires_external_runtime" in rule:
        profile["requires_external_runtime"] = bool(rule["requires_external_runtime"])
    return profile


def _round_metric(value: float | Decimal) -> float:
    """Use a documented decimal rounding rule and reject non-finite metrics."""
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("NON_FINITE_METRIC")
    return float(Decimal(str(numeric)).quantize(METRIC_QUANTUM, rounding=ROUND_HALF_UP))


TARGET_CATALOG: dict[str, dict[str, Any]] = {
    "POWER_THERMAL_OUTPUT": {
        "provider": "ELECTRICITY",
        "sensitivity": "L3",
        "granularity": "AGGREGATE",
        "tags": ["POWER", "THERMAL", "GENERATION"],
        "unit": "MWh",
    },
    "GRID_LOAD": {
        "provider": "ELECTRICITY",
        "sensitivity": "L3",
        "granularity": "AGGREGATE",
        "tags": ["POWER", "LOAD", "BALANCE"],
        "unit": "MWh",
    },
    "PUBLIC_ENERGY_STAT": {
        "provider": "ELECTRICITY",
        "sensitivity": "L1",
        "granularity": "AGGREGATE",
        "tags": ["POWER", "PUBLIC", "STATISTICS"],
        "unit": "MWh",
    },
    "POWER_DISPATCH": {
        "provider": "ELECTRICITY",
        "sensitivity": "L4",
        "granularity": "DETAIL",
        "tags": ["POWER", "DISPATCH", "REAL_TIME"],
        "unit": "%",
    },
    "POWER_TRADING": {
        "provider": "ELECTRICITY",
        "sensitivity": "L4",
        "granularity": "DETAIL",
        "tags": ["POWER", "TRADING", "REAL_TIME"],
        "unit": "MWh",
    },
    "COAL_INVENTORY": {
        "provider": "COAL",
        "sensitivity": "L3",
        "granularity": "DETAIL",
        "tags": ["COAL", "INVENTORY", "FUEL"],
        "unit": "tons",
    },
    "OIL_GAS_SUPPLY": {
        "provider": "OIL_GAS",
        "sensitivity": "L3",
        "granularity": "DETAIL",
        "tags": ["OIL_GAS", "SUPPLY", "FUEL"],
        "unit": "million_m3",
    },
    "USER_DETAIL": {
        "provider": "ELECTRICITY",
        "sensitivity": "L4",
        "granularity": "DETAIL",
        "tags": ["POWER", "USER", "DETAIL"],
        "unit": "MW",
    },
}


def _previous_month(reference: date) -> tuple[date, date]:
    first = reference.replace(day=1)
    last = first - timedelta(days=1)
    return last.replace(day=1), last


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


@dataclass(frozen=True)
class QueryIntent:
    question: str
    purpose: str
    consumer_role: str
    period_start: date
    period_end: date
    target_data_types: tuple[str, ...]
    group_by: tuple[str, ...]
    requested_fields: tuple[str, ...]
    statistics: tuple[str, ...]
    output_mode: str
    requested_granularity: str
    spatial_scope: str
    function_code: str

    def context_for(self, target_type: str) -> dict[str, Any]:
        target = TARGET_CATALOG.get(target_type, {})
        return {
            "data_type": target_type,
            "provider": target.get("provider"),
            "sensitivity": target.get("sensitivity", "L4"),
            "granularity": target.get("granularity", "DETAIL"),
            "tags": target.get("tags", []),
            "consumer_role": self.consumer_role,
            "purpose": self.purpose,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "group_by": list(self.group_by),
            "requested_fields": list(self.requested_fields),
            "requested_granularity": self.requested_granularity,
            "spatial_scope": self.spatial_scope,
            "function": self.function_code,
        }


@dataclass(frozen=True)
class CallerIdentity:
    user_id: str
    username: str
    organization_id: str
    role: str
    requested_role: str
    did: str
    credential_status: str
    did_verified: bool
    credential_hash: str | None
    credential_canonicalization: str

    @classmethod
    def from_user(cls, db: Session, user: User, requested_role: str) -> "CallerIdentity":
        did_record = db.scalar(
            select(DidIdentity)
            .where(DidIdentity.owner_id == user.org_id, DidIdentity.owner_type == "ORG")
            .order_by(DidIdentity.created_at.desc())
        )
        credential_status = did_record.credential_status if did_record else "MISSING"
        credential_evidence = (
            JsonLdCredentialAdapter.fingerprint(did_record.credential_json)
            if did_record
            else {"status": "MISSING"}
        )
        return cls(
            user_id=user.user_id,
            username=user.username,
            organization_id=user.org_id,
            role=user.role_code,
            requested_role=requested_role,
            did=did_record.did_id if did_record else f"did:hiddenchain:org:{user.org_id}",
            credential_status=credential_status,
            did_verified=credential_status == "VALID",
            credential_hash=credential_evidence.get("credential_hash"),
            credential_canonicalization=str(credential_evidence.get("status", "UNKNOWN")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyDecision:
    target_type: str
    action: PolicyAction
    permitted: bool
    rule_id: str
    reason: str
    policy_version: str
    policy_hash: str
    output_fields: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    delay_days: int = 0
    release_at: str | None = None
    min_group_size: int = 1
    execution_method: str = "BLOCKED"
    implementation_status: str = "NOT_EXECUTED"
    requires_external_runtime: bool = False
    candidate_methods: tuple[str, ...] = ()

    @property
    def release_mode(self) -> str:
        if self.action == PolicyAction.AGGREGATE:
            return "AGGREGATED"
        if self.action == PolicyAction.COMPUTE_ONLY:
            return "COMPUTE_ONLY"
        if self.action == PolicyAction.DELAY:
            return "DELAYED" if self.permitted else "WAIT_FOR_RELEASE"
        if self.action == PolicyAction.ALLOW:
            return "DIRECT"
        return "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_data_type": self.target_type,
            "action": self.action.value,
            "decision": "PERMIT" if self.permitted else "DENY",
            "rule_id": self.rule_id,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "output_fields": list(self.output_fields),
            "group_by": list(self.group_by),
            "delay_days": self.delay_days,
            "release_at": self.release_at,
            "release_mode": self.release_mode,
            "min_group_size": self.min_group_size,
            "execution_method": self.execution_method,
            "implementation_status": self.implementation_status,
            "requires_external_runtime": self.requires_external_runtime,
            "candidate_methods": list(self.candidate_methods),
        }


class DynamicPolicyEngine:
    """Configuration-driven five-way data classification policy engine."""

    def __init__(self, policy_path: str | None = None) -> None:
        configured_path = Path(policy_path or settings.execution_policy_path)
        self.policy_path = self._resolve_policy_path(configured_path)
        self.document = self._load_document()
        self.version = str(self.document.get("version", "energy-execution/unknown"))
        self.policy_hash = sha256_json(self.document)
        self.rules = sorted(
            self.document.get("rules", []), key=lambda item: int(item.get("priority", 1000))
        )

    @staticmethod
    def _resolve_policy_path(configured_path: Path) -> Path:
        """Resolve policy paths across local, source-tree, and container layouts."""
        candidates = [configured_path]
        filename = configured_path.name or "energy_execution_policy.json"
        module_path = Path(__file__).resolve()
        for root in (module_path.parents[2], module_path.parents[3]):
            candidates.append(root / "policy" / filename)

        seen: set[Path] = set()
        for candidate in candidates:
            normalized = candidate if candidate.is_absolute() else candidate.resolve()
            if normalized in seen:
                continue
            seen.add(normalized)
            if normalized.is_file():
                return normalized
        return configured_path

    def _load_document(self) -> dict[str, Any]:
        try:
            return json.loads(self.policy_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {
                "version": "energy-execution/fail-closed",
                "default_action": PolicyAction.PROHIBIT.value,
                "rules": [],
            }

    @staticmethod
    def _matches(rule_match: dict[str, Any], context: dict[str, Any]) -> bool:
        for key, expected in rule_match.items():
            context_key = {
                "data_types": "data_type",
                "consumer_roles": "consumer_role",
                "purposes": "purpose",
            }.get(key, key)
            actual = context.get(context_key)
            expected_values = _as_list(expected)
            if key == "sensitivity":
                if actual not in expected_values:
                    return False
            elif key == "sensitivity_min":
                if SENSITIVITY_RANK.get(str(actual), 0) < SENSITIVITY_RANK.get(str(expected), 99):
                    return False
            elif key in {"data_types", "consumer_roles", "purposes", "granularity", "provider"}:
                if actual not in expected_values:
                    return False
            elif key == "tags_any":
                if not set(expected_values).intersection(set(context.get("tags", []))):
                    return False
            elif key == "group_by_contains":
                if not set(expected_values).issubset(set(context.get("group_by", []))):
                    return False
            elif key == "requested_fields_any":
                if not set(expected_values).intersection(set(context.get("requested_fields", []))):
                    return False
            else:
                if actual not in expected_values:
                    return False
        return True

    def decide(self, intent: QueryIntent, target_type: str, *, now: datetime | None = None) -> PolicyDecision:
        context = intent.context_for(target_type)
        matched = next(
            (
                rule
                for rule in self.rules
                if self._matches(rule.get("match", {}), context)
            ),
            None,
        )
        rule = matched or {
            "id": "default-prohibit",
            "description": "未命中显式规则，默认拒绝",
            "action": self.document.get("default_action", PolicyAction.PROHIBIT.value),
        }
        action = PolicyAction(str(rule.get("action", PolicyAction.PROHIBIT.value)))
        current = now or utc_now()
        delay_days = int(rule.get("delay_days", 0))
        release_at: str | None = None
        permitted = action not in {PolicyAction.PROHIBIT}
        reason = str(rule.get("description", "policy decision"))
        if action == PolicyAction.DELAY:
            release_datetime = datetime.combine(
                intent.period_end + timedelta(days=delay_days), datetime_time.min
            )
            release_at = release_datetime.isoformat()
            permitted = current >= release_datetime
            if not permitted:
                reason = f"数据需延迟 {delay_days} 天，最早可用时间为 {release_at}"
            else:
                reason = f"已达到延迟窗口 {delay_days} 天，允许以延迟结果交付"
        execution_profile = _execution_profile(action, permitted, rule)
        return PolicyDecision(
            target_type=target_type,
            action=action,
            permitted=permitted,
            rule_id=str(rule.get("id", "default-prohibit")),
            reason=reason,
            policy_version=self.version,
            policy_hash=self.policy_hash,
            output_fields=tuple(rule.get("output_fields", [])),
            group_by=tuple(rule.get("group_by", intent.group_by)),
            delay_days=delay_days,
            release_at=release_at,
            min_group_size=int(rule.get("min_group_size", 1)),
            execution_method=str(execution_profile["execution_method"]),
            implementation_status=str(execution_profile["implementation_status"]),
            requires_external_runtime=bool(execution_profile["requires_external_runtime"]),
            candidate_methods=tuple(execution_profile["candidate_methods"]),
        )

    def catalog(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "policy_hash": self.policy_hash,
            "path": str(self.policy_path),
            "default_action": self.document.get("default_action", PolicyAction.PROHIBIT.value),
            "rules": self.document.get("rules", []),
        }


class AgenticQueryOrchestrator:
    """Resolve natural language into a structured, policy-checkable query intent."""

    TARGET_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("COAL_INVENTORY", ("煤炭", "库存")),
        ("POWER_THERMAL_OUTPUT", ("火电", "热电", "出力")),
        ("GRID_LOAD", ("电网负荷", "负荷", "用电")),
        ("POWER_DISPATCH", ("调度", "实时出力")),
        ("POWER_TRADING", ("交易", "成交", "电价")),
        ("OIL_GAS_SUPPLY", ("油气", "天然气", "原油")),
    )

    @staticmethod
    def _periods(payload: dict[str, Any]) -> tuple[date, date]:
        start_value = payload.get("period_start")
        end_value = payload.get("period_end")
        if isinstance(start_value, str):
            start_value = date.fromisoformat(start_value)
        if isinstance(end_value, str):
            end_value = date.fromisoformat(end_value)
        if start_value and end_value:
            return start_value, end_value
        return _previous_month(utc_now().date())

    def resolve(self, payload: dict[str, Any], *, require_translation: bool = False) -> QueryIntent:
        question = str(payload.get("question", "")).strip()
        normalized = question.lower()
        translation = payload.get("translation")
        if require_translation and not isinstance(translation, dict):
            raise ValueError("TRANSLATION_REQUIRED")

        if isinstance(translation, dict):
            explicit_targets = [str(item).upper() for item in translation.get("target_data_types", [])]
            targets = list(dict.fromkeys(explicit_targets))
            period_start, period_end = self._periods(translation)
            function_code = str(translation.get("function") or "").upper()
        else:
            explicit_targets = [str(item).upper() for item in payload.get("target_data_types", [])]
            targets = list(dict.fromkeys(explicit_targets)) if explicit_targets else []
            if not targets:
                for target, keywords in self.TARGET_PATTERNS:
                    if all(keyword.lower() in normalized for keyword in keywords):
                        targets.append(target)
            if not targets:
                for target, keywords in self.TARGET_PATTERNS:
                    if any(keyword.lower() in normalized for keyword in keywords):
                        targets.append(target)
            if not targets:
                targets = ["POWER_THERMAL_OUTPUT", "GRID_LOAD"]
            targets = list(dict.fromkeys(targets))
            period_start, period_end = self._periods(payload)
            function_code = "TREND"
        purpose = str(payload.get("purpose") or "").strip() or (
            "CROSS_ENERGY_TREND" if len(targets) > 1 or "跨能源" in question else "ENERGY_ANALYSIS"
        )
        group_by = tuple((translation or payload).get("group_by") or ["region", "period"])
        requested_fields = tuple(payload.get("requested_fields") or [])
        statistics: list[str] = [function_code] if isinstance(translation, dict) else []
        if not statistics and any(word in question for word in ("趋势", "变化", "走势")):
            statistics.append("TREND")
        if not statistics and any(word in question for word in ("引起", "相关", "关联")):
            statistics.append("CORRELATION")
        if not statistics and any(word in question for word in ("平衡", "缺口", "供需")):
            statistics.append("BALANCE")
        if not statistics:
            statistics.append("SUMMARY")
        requested_granularity = str((translation or payload).get("requested_granularity") or "").strip().upper()
        if not requested_granularity:
            if "15分钟" in question or "15 分钟" in question:
                requested_granularity = "15_MINUTE"
            elif "日" in question:
                requested_granularity = "DAY"
            elif "明细" in question or "原始" in question:
                requested_granularity = "DETAIL"
            else:
                requested_granularity = "MONTH"
        spatial_scope = str((translation or payload).get("spatial_scope") or "REGION").strip().upper()
        return QueryIntent(
            question=question,
            purpose=purpose,
            consumer_role=str(payload.get("consumer_role") or "ENERGY_BUREAU"),
            period_start=period_start,
            period_end=period_end,
            target_data_types=tuple(targets),
            group_by=group_by,
            requested_fields=requested_fields,
            statistics=tuple(dict.fromkeys(statistics)),
            output_mode=str((translation or payload).get("output_mode") or payload.get("output_mode") or "SUMMARY"),
            requested_granularity=requested_granularity,
            spatial_scope=spatial_scope,
            function_code=function_code,
        )

    @staticmethod
    def build_plan(intent: QueryIntent, decisions: list[PolicyDecision]) -> dict[str, Any]:
        items = []
        for decision in decisions:
            descriptor = TARGET_CATALOG.get(decision.target_type, {})
            items.append(
                {
                    "target_data_type": decision.target_type,
                    "provider_node": f"{descriptor.get('provider', 'UNKNOWN')}_NODE",
                    "policy_action": decision.action.value,
                    "decision": "PERMIT" if decision.permitted else "DENY",
                    "release_mode": decision.release_mode,
                    "group_by": list(decision.group_by),
                    "output_fields": list(decision.output_fields),
                    "requested_granularity": intent.requested_granularity,
                    "spatial_scope": intent.spatial_scope,
                    "execution_method": decision.execution_method,
                    "implementation_status": decision.implementation_status,
                    "requires_external_runtime": decision.requires_external_runtime,
                    "candidate_methods": list(decision.candidate_methods),
                    "raw_data_allowed": False,
                }
            )
        plan = {
            "orchestration": "DETERMINISTIC_AGENTIC_INGESTION_V1",
            "purpose": intent.purpose,
            "period": {"start": intent.period_start.isoformat(), "end": intent.period_end.isoformat()},
            "statistics": list(intent.statistics),
            "requested_granularity": intent.requested_granularity,
            "spatial_scope": intent.spatial_scope,
            "items": items,
            "raw_data_allowed": False,
        }
        return {**plan, "plan_hash": sha256_json(plan)}


class EnergyDataNode(Protocol):
    code: str

    def query(
        self, target_type: str, intent: QueryIntent, decision: PolicyDecision
    ) -> list[dict[str, Any]]: ...


class ElectricityNode:
    code = "ELECTRICITY_NODE"
    interface_version = "ENERGY-NODE-1.0"
    region = "EAST-CHINA"

    ASSET_MAP = {
        "POWER_THERMAL_OUTPUT": "GENERATION_DATA",
        "GRID_LOAD": "RETAIL_DATA",
        "PUBLIC_ENERGY_STAT": "RETAIL_DATA",
        "POWER_TRADING": "RETAIL_DATA",
        "POWER_DISPATCH": "GRID_CONSTRAINT",
    }

    DEFAULTS = {
        "POWER_THERMAL_OUTPUT": (12680.0, "MWh"),
        "GRID_LOAD": (12490.0, "MWh"),
        "PUBLIC_ENERGY_STAT": (12490.0, "MWh"),
        "POWER_TRADING": (12490.0, "MWh"),
        "POWER_DISPATCH": (14.2, "%"),
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def _uploads(self, asset_type: str, period: str) -> list[DataUpload]:
        records = self.db.scalars(
            select(DataUpload)
            .where(DataUpload.asset_type == asset_type, DataUpload.validation_status == "PASSED")
            .order_by(DataUpload.created_at.desc())
        ).all()
        matching: list[DataUpload] = []
        for record in records:
            if (record.summary_json or {}).get("period") == period:
                matching.append(record)
        return matching or records[:1]

    def query(
        self, target_type: str, intent: QueryIntent, decision: PolicyDecision
    ) -> list[dict[str, Any]]:
        period = intent.period_end.strftime("%Y-%m")
        asset_type = self.ASSET_MAP.get(target_type)
        value, unit = self.DEFAULTS.get(target_type, (0.0, TARGET_CATALOG[target_type]["unit"]))
        aggregate_values: list[float] = []
        commitments: list[str] = []
        if asset_type:
            for upload in self._uploads(asset_type, period):
                try:
                    payload = LocalDomainVault.read(upload.data_ref)
                except (OSError, KeyError, TypeError):
                    continue
                if target_type in {"POWER_THERMAL_OUTPUT", "GRID_LOAD", "POWER_TRADING", "PUBLIC_ENERGY_STAT"}:
                    aggregate_values.append(float(payload.get("energy_mwh", value)))
                    unit = "MWh"
                elif target_type == "POWER_DISPATCH":
                    value = float(payload.get("congestion_margin_pct", value))
                    unit = "%"
                commitments.append(upload.commitment)
                period = str(payload.get("period", period))
        if aggregate_values:
            value = sum(aggregate_values)
        return [
            {
                "node": self.code,
                "interface_version": self.interface_version,
                "data_type": target_type,
                "period": period,
                "region": self.region,
                "value": _round_metric(value),
                "unit": unit,
                "aggregation": "SUM" if decision.action == PolicyAction.AGGREGATE else decision.release_mode,
                "group_size": max(1, len(commitments)),
                "source_commitments": commitments,
                "raw_data_exposed": False,
            }
        ]


class CoalNode:
    code = "COAL_NODE"
    interface_version = "ENERGY-NODE-1.0"
    schema = "coal:InventoryAggregate/v1"
    DEFAULT_RECORDS = (
        {"period": "2026-07", "region": "EAST-CHINA", "value": 820000.0},
        {"period": "2026-07", "region": "NORTH-CHINA", "value": 610000.0},
        {"period": "2026-06", "region": "EAST-CHINA", "value": 850000.0},
        {"period": "2026-06", "region": "NORTH-CHINA", "value": 635000.0},
    )

    def __init__(self, records: tuple[dict[str, Any], ...] | None = None) -> None:
        self.records = records or self.DEFAULT_RECORDS

    def query(
        self, target_type: str, intent: QueryIntent, decision: PolicyDecision
    ) -> list[dict[str, Any]]:
        period = intent.period_end.strftime("%Y-%m")
        records = [item for item in self.records if item["period"] == period]
        if not records:
            records = list(self.records[-2:])
        grouped: dict[tuple[str, str], float] = {}
        group_sizes: dict[tuple[str, str], int] = {}
        for item in records:
            key = (str(item["period"]), str(item["region"]))
            grouped[key] = grouped.get(key, 0.0) + float(item["value"])
            group_sizes[key] = group_sizes.get(key, 0) + 1
        return [
            {
                "node": self.code,
                "interface_version": self.interface_version,
                "schema": self.schema,
                "data_type": target_type,
                "period": key[0],
                "region": key[1],
                "value": _round_metric(value),
                "unit": "tons",
                "aggregation": "GROUP_BY_SUM",
                "group_by": list(decision.group_by),
                "group_size": group_sizes[key],
                "raw_data_exposed": False,
            }
            for key, value in sorted(grouped.items())
        ]


class OilGasNode:
    code = "OIL_GAS_NODE"
    interface_version = "ENERGY-NODE-1.0"
    schema = "oilgas:SupplyAggregate/v1"
    DEFAULT_RECORDS = (
        {"period": "2026-07", "region": "EAST-CHINA", "value": 410.0},
        {"period": "2026-07", "region": "NORTH-CHINA", "value": 275.0},
    )

    def __init__(self, records: tuple[dict[str, Any], ...] | None = None) -> None:
        self.records = records or self.DEFAULT_RECORDS

    def query(
        self, target_type: str, intent: QueryIntent, decision: PolicyDecision
    ) -> list[dict[str, Any]]:
        period = intent.period_end.strftime("%Y-%m")
        records = [item for item in self.records if item["period"] == period] or list(self.records)
        grouped: dict[tuple[str, str], float] = {}
        group_sizes: dict[tuple[str, str], int] = {}
        for item in records:
            key = (str(item["period"]), str(item["region"]))
            grouped[key] = grouped.get(key, 0.0) + float(item["value"])
            group_sizes[key] = group_sizes.get(key, 0) + 1
        return [
            {
                "node": self.code,
                "interface_version": self.interface_version,
                "schema": self.schema,
                "data_type": target_type,
                "period": key[0],
                "region": key[1],
                "value": _round_metric(value),
                "unit": "million_m3",
                "aggregation": "GROUP_BY_SUM",
                "group_by": list(decision.group_by),
                "group_size": group_sizes[key],
                "raw_data_exposed": False,
            }
            for key, value in sorted(grouped.items())
        ]


class EnergyNodeRegistry:
    def __init__(self, db: Session) -> None:
        self.nodes: dict[str, EnergyDataNode] = {
            "ELECTRICITY": ElectricityNode(db),
            "COAL": CoalNode(),
            "OIL_GAS": OilGasNode(),
        }

    def query(
        self, target_type: str, intent: QueryIntent, decision: PolicyDecision
    ) -> list[dict[str, Any]]:
        descriptor = TARGET_CATALOG.get(target_type)
        if descriptor is None:
            raise ValueError(f"Unsupported target data type: {target_type}")
        node = self.nodes.get(str(descriptor["provider"]))
        if node is None:
            raise ValueError(f"No node registered for {descriptor['provider']}")
        return node.query(target_type, intent, decision)

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "node_code": node.code,
                "interface_version": getattr(node, "interface_version", "ENERGY-NODE-1.0"),
                "provider_type": provider,
                "supported_data_types": [
                    target for target, descriptor in TARGET_CATALOG.items() if descriptor["provider"] == provider
                ],
            }
            for provider, node in self.nodes.items()
        ]


class ResultAuditor:
    FIELD_MAP = {
        "POWER_THERMAL_OUTPUT": "thermal_output_mwh",
        "GRID_LOAD": "grid_load_mwh",
        "PUBLIC_ENERGY_STAT": "public_energy_stat_mwh",
        "COAL_INVENTORY": "coal_inventory_tons",
        "OIL_GAS_SUPPLY": "oil_gas_supply_million_m3",
        "POWER_TRADING": "trading_energy_mwh",
        "POWER_DISPATCH": "dispatch_margin_pct",
    }
    FORBIDDEN_KEYS = {
        "raw_payload",
        "raw_records",
        "load_curve",
        "meter_point",
        "customer_group",
        "password_hash",
    }

    @classmethod
    def inspect(cls, result: dict[str, Any], decisions: list[PolicyDecision]) -> dict[str, Any]:
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        forbidden = [key for key in cls.FORBIDDEN_KEYS if key in serialized]
        if result.get("raw_data_returned") is True or forbidden:
            return {
                "passed": False,
                "reasons": ["RAW_OR_REIDENTIFICATION_RISK"],
                "forbidden_keys": forbidden,
            }
        min_group_size = max((decision.min_group_size for decision in decisions), default=1)
        small_groups = [
            item
            for item in result.get("series", [])
            if item.get("group_size") is not None and item["group_size"] < min_group_size
        ]
        if small_groups:
            return {
                "passed": False,
                "reasons": ["MIN_GROUP_SIZE_NOT_MET"],
                "small_groups": small_groups,
            }
        return {
            "passed": True,
            "reasons": [],
            "raw_data_returned": False,
            "anti_inference": "PASSED",
        }

    @classmethod
    def verify_calculation(
        cls, result: dict[str, Any], source_snapshot: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Recompute safe arithmetic and reconcile it with node aggregates.

        This never asks the execution layer for raw provider records. It checks
        the aggregate values and commitments/attestations that the nodes are
        allowed to expose.
        """

        errors: list[dict[str, Any]] = []
        function = result.get("function") if isinstance(result.get("function"), dict) else {}
        function_code = str(function.get("code") or "")
        operands = function.get("operands") if isinstance(function.get("operands"), list) else []
        series_by_key = {
            (str(item.get("period")), str(item.get("region"))): item
            for item in result.get("series", [])
        }
        for item in result.get("series", []):
            thermal = item.get("thermal_output_mwh")
            load = item.get("grid_load_mwh")
            balance = item.get("grid_balance_margin_mwh")
            if thermal is None or load is None:
                continue
            expected = _round_metric(float(thermal) - float(load))
            if balance is None or not math.isclose(float(balance), expected, abs_tol=0.0001):
                errors.append(
                    {
                        "check": "BALANCE_FORMULA",
                        "period": item.get("period"),
                        "region": item.get("region"),
                        "expected": expected,
                        "actual": balance,
                    }
                )
            expected_status = "SURPLUS" if expected >= 0 else "GAP"
            if item.get("balance_status") != expected_status:
                errors.append(
                    {
                        "check": "BALANCE_STATUS",
                        "period": item.get("period"),
                        "region": item.get("region"),
                        "expected": expected_status,
                        "actual": item.get("balance_status"),
                    }
                )
            if function_code == "SUM" and operands:
                operand_fields = [cls.FIELD_MAP.get(str(target)) for target in operands]
                if all(field and field in item for field in operand_fields):
                    expected_sum = _round_metric(sum(float(item[field]) for field in operand_fields))
                    actual_sum = item.get("function_result")
                    if actual_sum is None or not math.isclose(float(actual_sum), expected_sum, abs_tol=0.0001):
                        errors.append(
                            {
                                "check": "FUNCTION_SUM",
                                "period": item.get("period"),
                                "region": item.get("region"),
                                "expected": expected_sum,
                                "actual": actual_sum,
                            }
                        )

        source_aggregates: dict[tuple[str, str, str], float] = {}
        for source in source_snapshot:
            field = cls.FIELD_MAP.get(str(source.get("data_type")))
            if field is None:
                errors.append(
                    {
                        "check": "SOURCE_RESULT_MAPPING",
                        "source": {
                            "data_type": source.get("data_type"),
                            "period": source.get("period"),
                            "region": source.get("region"),
                        },
                    }
                )
                continue
            key = (str(source.get("period")), str(source.get("region")), field)
            source_aggregates[key] = _round_metric(
                source_aggregates.get(key, 0.0) + float(source.get("value", 0))
            )

        for (period, region, field), expected in source_aggregates.items():
            result_row = series_by_key.get((period, region))
            if result_row is None:
                errors.append(
                    {
                        "check": "SOURCE_RESULT_MAPPING",
                        "source": {"data_type": field, "period": period, "region": region},
                    }
                )
                continue
            actual = result_row.get(field)
            if actual is None or not math.isclose(float(actual), expected, abs_tol=0.0001):
                errors.append(
                    {
                        "check": "SOURCE_AGGREGATE_RECONCILIATION",
                        "data_type": field,
                        "period": period,
                        "region": region,
                        "expected": expected,
                        "actual": actual,
                    }
                )

        checks = {
            "balance_formula": not any(item["check"] == "BALANCE_FORMULA" for item in errors),
            "balance_status": not any(item["check"] == "BALANCE_STATUS" for item in errors),
            "function_sum": not any(item["check"] == "FUNCTION_SUM" for item in errors),
            "source_aggregate_reconciliation": not any(
                item["check"] == "SOURCE_AGGREGATE_RECONCILIATION" for item in errors
            ),
            "source_result_mapping": not any(
                item["check"] == "SOURCE_RESULT_MAPPING" for item in errors
            ),
            "raw_data_boundary": result.get("raw_data_returned") is False,
        }
        if not checks["raw_data_boundary"]:
            errors.append({"check": "RAW_DATA_BOUNDARY"})
        return {
            "passed": not errors,
            "status": "PASSED" if not errors else "FAILED",
            "checks": checks,
            "errors": errors,
            "source_rows_checked": len(source_snapshot),
        }


class TrustedExecutionReviewService:
    """Persist and confirm human-reviewable accuracy checks."""

    @staticmethod
    def _copy_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @classmethod
    def create(
        cls,
        db: Session,
        *,
        request_id: str,
        trace_id_value: str,
        execution_status: str,
        result_hash: str,
        result: dict[str, Any],
        source_snapshot: list[dict[str, Any]],
        identity: CallerIdentity,
        target_data: list[str],
        policy_hits: list[dict[str, Any]],
        execution_plan_hash: str | None,
    ) -> tuple[TrustedExecutionReview, dict[str, Any]]:
        result_copy = cls._copy_json(result)
        source_copy = cls._copy_json(source_snapshot)
        if execution_status == "SUCCEEDED":
            checks = ResultAuditor.verify_calculation(result_copy, source_copy)
            automatic_status = checks["status"]
            verification_status = "PENDING" if checks["passed"] else "REJECTED"
        else:
            checks = {"passed": False, "status": "NOT_RUN", "checks": {}, "errors": []}
            automatic_status = "NOT_RUN"
            verification_status = "NOT_APPLICABLE"
        review = TrustedExecutionReview(
            request_id=request_id,
            trace_id=trace_id_value,
            execution_status=execution_status,
            result_hash=result_hash,
            result_json=result_copy,
            source_snapshot_json=source_copy,
            caller_identity_json=cls._copy_json(identity.to_dict()),
            target_data_json=cls._copy_json(target_data),
            policy_hits_json=cls._copy_json(policy_hits),
            execution_plan_hash=execution_plan_hash,
            automatic_status=automatic_status,
            checks_json=checks,
            verification_status=verification_status,
        )
        db.add(review)
        db.flush()
        return review, checks

    @staticmethod
    def summary(review: TrustedExecutionReview, *, include_snapshot: bool = False) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "review_id": review.review_id,
            "request_id": review.request_id,
            "trace_id": review.trace_id,
            "execution_status": review.execution_status,
            "result_hash": review.result_hash,
            "automatic_status": review.automatic_status,
            "verification_status": review.verification_status,
            "checks": review.checks_json,
            "target_data": review.target_data_json,
            "reviewer_user_id": review.reviewer_user_id,
            "reviewer_org_id": review.reviewer_org_id,
            "reviewer_did": review.reviewer_did,
            "reviewer_note": review.reviewer_note,
            "confirmed_at": review.confirmed_at.isoformat() if review.confirmed_at else None,
        }
        if include_snapshot:
            summary.update(
                {
                    "caller_identity": review.caller_identity_json,
                    "target_data": review.target_data_json,
                    "policy_hits": review.policy_hits_json,
                    "execution_plan_hash": review.execution_plan_hash,
                    "result": review.result_json,
                    "source_snapshot": review.source_snapshot_json,
                }
            )
        return summary

    @classmethod
    def confirm(
        cls,
        db: Session,
        review: TrustedExecutionReview,
        *,
        user: User,
        reviewer_did: str,
        opinion: str,
        accept: bool,
    ) -> tuple[dict[str, Any], str | None]:
        if review.verification_status == "CONFIRMED":
            existing = db.scalar(
                select(Signature)
                .where(
                    Signature.target_type == "TRUSTED_EXECUTION_REVIEW",
                    Signature.target_id == review.review_id,
                    Signature.target_hash == review.result_hash,
                    Signature.verify_status == "VALID",
                )
                .order_by(Signature.created_at.desc())
            )
            return cls.summary(review, include_snapshot=True), existing.signature_value if existing else None

        recalculated_hash = sha256_json(review.result_json)
        if recalculated_hash != review.result_hash:
            raise ValueError("RESULT_HASH_MISMATCH")
        checks = ResultAuditor.verify_calculation(review.result_json, review.source_snapshot_json)
        review.checks_json = checks
        review.automatic_status = checks["status"]
        if accept and not checks["passed"]:
            raise ValueError("ACCURACY_CHECK_FAILED")
        review.verification_status = "CONFIRMED" if accept else "REJECTED"
        review.reviewer_user_id = user.user_id
        review.reviewer_org_id = user.org_id
        review.reviewer_did = reviewer_did
        review.reviewer_note = opinion
        review.confirmed_at = utc_now()
        signature_value: str | None = None
        if accept:
            signature_payload = {
                "request_id": review.request_id,
                "result_hash": review.result_hash,
                "opinion": opinion,
                "verification_status": review.verification_status,
            }
            signature_value = sign_value(signature_payload, user.user_id)
            db.add(
                Signature(
                    task_id=None,
                    signer_org_id=user.org_id,
                    signer_did=reviewer_did,
                    target_type="TRUSTED_EXECUTION_REVIEW",
                    target_id=review.review_id,
                    target_hash=review.result_hash,
                    signature_value=signature_value,
                    verify_status="VALID",
                )
            )
        return cls.summary(review, include_snapshot=True), signature_value


class EvidenceAuditLogger:
    """Asynchronously append the required audit summary to the local evidence ledger."""

    _executor = ThreadPoolExecutor(
        max_workers=max(settings.execution_audit_workers, 1),
        thread_name_prefix="hiddenchain-audit",
    )

    @classmethod
    def _anchor(cls, task_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        db = SessionLocal()
        try:
            evidence = LocalEvidenceLedgerAdapter().anchor(
                db,
                task_id=task_id,
                stage="TRUST_EXECUTION",
                biz_type="TRUSTED_EXECUTION",
                biz_id=str(payload["Request_ID"]),
                payload=payload,
            )
            db.commit()
            return {
                "status": "CONFIRMED",
                "evidence_id": evidence.evidence_id,
                "tx_hash": evidence.tx_hash,
                "block_height": evidence.block_height,
            }
        except Exception as exc:
            db.rollback()
            return {"status": "FAILED", "error_type": type(exc).__name__}
        finally:
            db.close()

    @classmethod
    def enqueue(cls, *, task_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        cls._executor.submit(cls._anchor, task_id, payload)
        return {
            "status": "QUEUED",
            "biz_type": "TRUSTED_EXECUTION",
            "request_id": payload["Request_ID"],
        }


class TrustworthyExecutionController:
    """Eight-step trusted execution controller for cross-energy requests."""

    def __init__(
        self,
        db: Session,
        *,
        policy_engine: DynamicPolicyEngine | None = None,
        orchestrator: AgenticQueryOrchestrator | None = None,
        registry: EnergyNodeRegistry | None = None,
    ) -> None:
        self.db = db
        self.policy_engine = policy_engine or DynamicPolicyEngine()
        self.orchestrator = orchestrator or AgenticQueryOrchestrator()
        self.registry = registry or EnergyNodeRegistry(db)

    @staticmethod
    def _step(
        steps: list[dict[str, Any]], number: int, code: str, status: str, details: dict[str, Any]
    ) -> None:
        steps.append({"step": number, "code": code, "status": status, "details": details})

    @staticmethod
    def _allowed_role(user: User, requested_role: str) -> bool:
        allowed = {
            "ENERGY_BUREAU": {"EXCHANGE", "REGULATOR", "ADMIN"},
            "REGULATOR": {"REGULATOR", "ADMIN"},
            "PUBLIC": {"EXCHANGE", "REGULATOR", "ADMIN"},
        }
        return user.role_code in allowed.get(requested_role, set())

    @staticmethod
    def _compose_result(
        intent: QueryIntent,
        rows: list[dict[str, Any]],
        decisions: list[PolicyDecision],
    ) -> dict[str, Any]:
        by_period_region: dict[tuple[str, str], dict[str, Any]] = {}
        field_map = {
            "POWER_THERMAL_OUTPUT": ("thermal_output_mwh", "MWh"),
            "GRID_LOAD": ("grid_load_mwh", "MWh"),
            "PUBLIC_ENERGY_STAT": ("public_energy_stat_mwh", "MWh"),
            "COAL_INVENTORY": ("coal_inventory_tons", "tons"),
            "OIL_GAS_SUPPLY": ("oil_gas_supply_million_m3", "million_m3"),
            "POWER_TRADING": ("trading_energy_mwh", "MWh"),
            "POWER_DISPATCH": ("dispatch_margin_pct", "%"),
        }
        decision_map = {decision.target_type: decision for decision in decisions}
        for row in rows:
            key = (str(row["period"]), str(row["region"]))
            entry = by_period_region.setdefault(
                key,
                {
                    "period": key[0],
                    "region": key[1],
                    "group_size": None,
                    "raw_data_exposed": False,
                },
            )
            row_group_size = max(1, int(row.get("group_size", 1)))
            entry["group_size"] = (
                row_group_size
                if entry["group_size"] is None
                else min(int(entry["group_size"]), row_group_size)
            )
            field_name, _ = field_map.get(row["data_type"], (row["data_type"].lower(), row["unit"]))
            if field_name in entry and decision_map.get(row["data_type"], None) is not None:
                entry[field_name] = _round_metric(float(entry[field_name]) + float(row["value"]))
            else:
                entry[field_name] = _round_metric(float(row["value"]))
            entry.setdefault("units", {})[field_name] = row["unit"]
            entry.setdefault("source_nodes", []).append(row["node"])
        series = []
        for entry in sorted(by_period_region.values(), key=lambda item: (item["period"], item["region"])):
            thermal = entry.get("thermal_output_mwh")
            load = entry.get("grid_load_mwh")
            if thermal is not None and load is not None:
                entry["grid_balance_margin_mwh"] = _round_metric(thermal - load)
                entry["balance_status"] = "SURPLUS" if thermal >= load else "GAP"
            series.append(entry)

        function_result_field = "function_result"
        function_unit = None
        if intent.function_code == "SUM":
            operand_fields = [field_map[target][0] for target in intent.target_data_types if target in field_map]
            function_unit = field_map[intent.target_data_types[0]][1]
            for entry in series:
                if all(field in entry for field in operand_fields):
                    entry[function_result_field] = _round_metric(
                        sum(float(entry[field]) for field in operand_fields)
                    )
                    entry["function_unit"] = function_unit
        elif intent.function_code == "BALANCE":
            function_unit = "MWh"
            for entry in series:
                if "grid_balance_margin_mwh" in entry:
                    entry[function_result_field] = entry["grid_balance_margin_mwh"]
                    entry["function_unit"] = function_unit

        def change(field: str) -> float | None:
            values = [item[field] for item in series if field in item]
            if len(values) < 2 or values[0] == 0:
                return None
            return _round_metric((values[-1] - values[0]) / abs(values[0]) * 100)

        thermal_change = change("thermal_output_mwh")
        load_change = change("grid_load_mwh")
        coal_change = change("coal_inventory_tons")
        if thermal_change is None:
            trend = "INSUFFICIENT_PERIODS"
        elif thermal_change > 0.5:
            trend = "UP"
        elif thermal_change < -0.5:
            trend = "DOWN"
        else:
            trend = "STABLE"
        source_items: list[dict[str, Any]] = []
        seen_sources: set[tuple[str, str, str]] = set()
        for row in rows:
            source_key = (str(row["node"]), str(row["interface_version"]), str(row["data_type"]))
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            source_items.append(
                {
                    "node": row["node"],
                    "interface_version": row["interface_version"],
                    "data_type": row["data_type"],
                    "raw_data_exposed": False,
                }
            )
        selected_methods = [
            {
                "target_data_type": decision.target_type,
                "action": decision.action.value,
                "method": decision.execution_method,
                "implementation_status": decision.implementation_status,
                "requires_external_runtime": decision.requires_external_runtime,
                "candidate_methods": list(decision.candidate_methods),
            }
            for decision in decisions
        ]
        candidate_methods = sorted(
            {
                method
                for decision in decisions
                for method in decision.candidate_methods
            }
        )
        return {
            "purpose": intent.purpose,
            "function": {
                "code": intent.function_code,
                "label": {"SUM": "求和", "BALANCE": "平衡计算", "TREND": "趋势分析"}.get(intent.function_code, intent.function_code),
                "operands": list(intent.target_data_types),
                "result_field": function_result_field,
                "unit": function_unit,
            },
            "period": {"start": intent.period_start.isoformat(), "end": intent.period_end.isoformat()},
            "statistics": list(intent.statistics),
            "series": series,
            "analysis": {
                "trend": trend,
                "thermal_output_change_pct": thermal_change,
                "grid_load_change_pct": load_change,
                "coal_inventory_change_pct": coal_change,
                "causal_interpretation": "仅基于区域/月度聚合信号生成关联趋势，不输出原始明细或因果断言",
            },
            "calculation_contract": {
                "aggregation_key": ["period", "region", "data_type"],
                "aggregation_method": "SUM_PER_SOURCE_GROUP",
                "rounding_scale": 4,
                "rounding_mode": "HALF_UP",
                "balance_formula": "thermal_output_mwh - grid_load_mwh",
            },
            "sources": sorted(source_items, key=lambda item: (item["node"], item["data_type"])),
            "policy_actions": sorted({decision.action.value for decision in decisions}),
            "output_mode": "AGGREGATED_AND_COMPUTE_ONLY",
            "privacy_controls": {
                "cross_domain_non_export_verified": False,
                "compute_environment": "APPLICATION_PROCESS",
                "attestation_status": "NOT_PROVIDED",
                "anti_inference_check": "LOCAL_OUTPUT_CHECK_PASSED",
                "topology_coordinate_offset": {
                    "status": "APPLIED_WHEN_TOPOLOGY_FIELDS_ARE_REQUESTED",
                    "coordinates_returned": False,
                },
            },
            "execution_routing": {
                "policy_driven": True,
                "selected_methods": selected_methods,
                "actual_runtime": "APPLICATION_PROCESS",
                "actual_method": "LOCAL_CONTROLLED_COMPUTE",
                "implementation_status": "TEST_FIXTURE_ONLY",
                "candidate_methods": candidate_methods,
                "external_runtime_required": bool(candidate_methods),
                "cross_domain_non_export_verified": False,
                "raw_data_returned": False,
            },
            "raw_data_returned": False,
        }

    @staticmethod
    def _source_snapshot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        snapshot: list[dict[str, Any]] = []
        for row in rows:
            safe_row = {
                "node": row.get("node"),
                "interface_version": row.get("interface_version"),
                "schema": row.get("schema"),
                "data_type": row.get("data_type"),
                "period": row.get("period"),
                "region": row.get("region"),
                "value": row.get("value"),
                "unit": row.get("unit"),
                "aggregation": row.get("aggregation"),
                "group_by": row.get("group_by", []),
                "group_size": row.get("group_size", 1),
                "source_commitments": row.get("source_commitments", []),
                "raw_data_exposed": False,
            }
            safe_row["source_attestation"] = sha256_json(safe_row)
            snapshot.append(safe_row)
        return snapshot

    def _finalize(
        self,
        *,
        request_id: str,
        current_trace_id: str,
        identity: CallerIdentity,
        intent: QueryIntent | None,
        policy_hits: list[PolicyDecision],
        plan: dict[str, Any] | None,
        steps: list[dict[str, Any]],
        status: str,
        result: dict[str, Any],
        user: User,
        source_snapshot: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source_snapshot = source_snapshot or []
        result_for_review = TrustedExecutionReviewService._copy_json(result)
        result_hash = sha256_json(result_for_review)
        result["result_hash"] = result_hash
        policy_payload = [decision.to_dict() for decision in policy_hits]
        review, review_checks = TrustedExecutionReviewService.create(
            self.db,
            request_id=request_id,
            trace_id_value=current_trace_id,
            execution_status=status,
            result_hash=result_hash,
            result=result_for_review,
            source_snapshot=source_snapshot,
            identity=identity,
            target_data=list(intent.target_data_types) if intent else [],
            policy_hits=policy_payload,
            execution_plan_hash=plan.get("plan_hash") if plan else None,
        )
        workflow_for_receipt = [
            *steps,
            {
                "step": 8,
                "code": "LOG",
                "status": "QUEUED",
                "details": {"destination": "LOCAL_EVIDENCE_LEDGER_V1"},
            },
        ]
        payload = {
            "Request_ID": request_id,
            "Caller_Identity": identity.to_dict(),
            "Target_Data": list(intent.target_data_types) if intent else [],
            "Policy_Hit": policy_payload,
            "Execution_Status": status,
            "Result_Hash": result_hash,
            "Trace_ID": current_trace_id,
            "Workflow_Steps": workflow_for_receipt,
            "Execution_Plan_Hash": plan.get("plan_hash") if plan else None,
            "Review_ID": review.review_id,
            "Source_Attestations": [item["source_attestation"] for item in source_snapshot if item.get("source_attestation")],
        }
        add_audit_log(
            self.db,
            action="TRUSTED_EXECUTION_CLOSED_LOOP",
            target_type="TRUSTED_EXECUTION",
            target_id=request_id,
            result=status,
            user=user,
            current_trace_id=current_trace_id,
            details={
                "workflow_steps": steps,
                "policy_hits": payload["Policy_Hit"],
                "result_hash": result_hash,
                "accuracy_review_id": review.review_id,
                "accuracy_review_status": review.verification_status,
                "accuracy_checks": review_checks,
                "query_function": intent.function_code if intent else None,
                "translated_target_data": list(intent.target_data_types) if intent else [],
                "raw_data_returned": False,
            },
        )
        self.db.commit()
        lineage_inputs = [
            input_dataset(
                namespace=f"hiddenchain://node/{item.get('node', 'unknown')}",
                name=(
                    f"data-product/{item.get('data_type', 'UNKNOWN')}/"
                    f"{item.get('period', 'UNKNOWN')}/{item.get('region', 'UNKNOWN')}"
                ),
                data_product_id=(
                    f"{item.get('data_type', 'UNKNOWN')}"
                    f"@{item.get('node', 'unknown')}"
                ),
                asset_type=str(item.get("data_type", "UNKNOWN")),
                data_hash=item.get("source_attestation"),
                commitment=sha256_json(item.get("source_commitments", [])),
            )
            for item in source_snapshot
        ]
        lineage = emit_run_event(
            run_id=request_id,
            job_name="trusted-cross-energy-query",
            event_type="COMPLETE" if status == "SUCCEEDED" else "FAIL",
            trace_id=current_trace_id,
            input_datasets=lineage_inputs,
            output_name=f"trusted-execution-result/{request_id}",
            output_hash=result_hash,
            result_status=status,
            policy_hash=plan.get("plan_hash") if plan else None,
            raw_data_exported=False,
        )
        evidence_record = EvidenceAuditLogger.enqueue(task_id=None, payload=payload)
        self._step(steps, 8, "LOG", "QUEUED", evidence_record)
        return {
            "request_id": request_id,
            "trace_id": current_trace_id,
            "execution_status": status,
            "caller_identity": identity.to_dict(),
            "intent": asdict(intent) if intent else None,
            "execution_plan": plan,
            "policy_hits": [decision.to_dict() for decision in policy_hits],
            "workflow_steps": steps,
            "result": result,
            "result_hash": result_hash,
            "accuracy_review": TrustedExecutionReviewService.summary(review),
            "evidence_audit": evidence_record,
            "lineage": lineage,
            "raw_data_returned": False,
        }

    def execute(self, request: Any, user: User) -> dict[str, Any]:
        payload = request.model_dump() if hasattr(request, "model_dump") else dict(request)
        request_id = f"req-{uuid.uuid4().hex}"
        current_trace_id = trace_id()
        steps: list[dict[str, Any]] = []
        identity = CallerIdentity.from_user(self.db, user, str(payload.get("consumer_role", "ENERGY_BUREAU")))
        policy_hits: list[PolicyDecision] = []
        intent: QueryIntent | None = None
        plan: dict[str, Any] | None = None
        source_snapshot: list[dict[str, Any]] = []
        self._step(
            steps,
            1,
            "INGEST",
            "PASSED",
            {"request_id": request_id, "input_type": "NATURAL_LANGUAGE_OR_API", "raw_data_received": False},
        )
        role_allowed = self._allowed_role(user, identity.requested_role)
        if not role_allowed or not identity.did_verified:
            reason = "CALLER_ROLE_NOT_ALLOWED" if not role_allowed else "DID_CREDENTIAL_INVALID"
            self._step(
                steps,
                2,
                "AUTHENTICATE",
                "DENIED",
                {
                    "reason": reason,
                    "actual_role": user.role_code,
                    "did": identity.did,
                    "credential_status": identity.credential_status,
                },
            )
            for number, code in ((3, "RESOLVE"), (4, "ARBITRATE"), (5, "EXECUTE"), (6, "AUDIT"), (7, "DELIVER")):
                self._step(steps, number, code, "SKIPPED", {"reason": "AUTHENTICATION_FAILED"})
            return self._finalize(
                request_id=request_id,
                current_trace_id=current_trace_id,
                identity=identity,
                intent=None,
                policy_hits=[],
                plan=None,
                steps=steps,
                status="DENIED",
                result={"released": False, "reason": reason, "raw_data_returned": False},
                user=user,
            )

        self._step(
            steps,
            2,
            "AUTHENTICATE",
            "PASSED",
            {
                "user_id": user.user_id,
                "organization_id": user.org_id,
                "did": identity.did,
                "credential_status": identity.credential_status,
                "did_verified": identity.did_verified,
                "role": identity.requested_role,
            },
        )
        try:
            intent = self.orchestrator.resolve(payload, require_translation=True)
        except ValueError as exc:
            self._step(steps, 3, "RESOLVE", "DENIED", {"reason": str(exc)})
            for number, code in ((4, "ARBITRATE"), (5, "EXECUTE"), (6, "AUDIT"), (7, "DELIVER")):
                self._step(steps, number, code, "SKIPPED", {"reason": "TRANSLATION_INVALID"})
            return self._finalize(
                request_id=request_id,
                current_trace_id=current_trace_id,
                identity=identity,
                intent=None,
                policy_hits=[],
                plan=None,
                steps=steps,
                status="DENIED",
                result={"released": False, "reason": "TRANSLATION_INVALID", "raw_data_returned": False},
                user=user,
            )
        self._step(
            steps,
            3,
            "RESOLVE",
            "PASSED",
            {
                "target_data_types": list(intent.target_data_types),
                "period": {"start": intent.period_start.isoformat(), "end": intent.period_end.isoformat()},
                "statistics": list(intent.statistics),
            },
        )
        policy_hits = [
            self.policy_engine.decide(intent, target_type)
            for target_type in intent.target_data_types
        ]
        plan = self.orchestrator.build_plan(intent, policy_hits)
        self._step(
            steps,
            4,
            "ARBITRATE",
            "PASSED" if all(item.permitted for item in policy_hits) else "DENIED",
            {"policy_hits": [item.to_dict() for item in policy_hits], "plan_hash": plan["plan_hash"]},
        )
        denied = [item for item in policy_hits if not item.permitted]
        if denied:
            self._step(
                steps,
                5,
                "EXECUTE",
                "BLOCKED",
                {"reason": "POLICY_DENIED", "denied_targets": [item.target_type for item in denied]},
            )
            result = {
                "released": False,
                "reason": "POLICY_DENIED",
                "denied_targets": [item.target_type for item in denied],
                "raw_data_returned": False,
            }
            self._step(steps, 6, "AUDIT", "PASSED", {"raw_data_returned": False, "anti_inference": "NOT_EXECUTED"})
            self._step(steps, 7, "DELIVER", "BLOCKED", {"reason": "NO_RESULT_DELIVERED"})
            return self._finalize(
                request_id=request_id,
                current_trace_id=current_trace_id,
                identity=identity,
                intent=intent,
                policy_hits=policy_hits,
                plan=plan,
                steps=steps,
                status="DENIED",
                result=result,
                user=user,
            )

        try:
            rows: list[dict[str, Any]] = []
            for target_type, decision in zip(intent.target_data_types, policy_hits):
                rows.extend(self.registry.query(target_type, intent, decision))
            source_snapshot = self._source_snapshot(rows)
            result = self._compose_result(intent, rows, policy_hits)
            self._step(
                steps,
                5,
                "EXECUTE",
                "PASSED",
                {
                    "provider_nodes": sorted({row["node"] for row in rows}),
                    "aggregate_rows": len(rows),
                    "raw_data_accessed_by_consumer": False,
                },
            )
            audit_result = ResultAuditor.inspect(result, policy_hits)
            accuracy_result = ResultAuditor.verify_calculation(result, source_snapshot)
            audit_result = {**audit_result, "calculation_accuracy": accuracy_result}
            audit_passed = audit_result["passed"] and accuracy_result["passed"]
            self._step(steps, 6, "AUDIT", "PASSED" if audit_passed else "DENIED", audit_result)
            if not audit_passed:
                result = {"released": False, "reason": "RESULT_AUDIT_FAILED", "audit": audit_result, "raw_data_returned": False}
                self._step(steps, 7, "DELIVER", "BLOCKED", {"reason": "RESULT_AUDIT_FAILED"})
                return self._finalize(
                    request_id=request_id,
                    current_trace_id=current_trace_id,
                    identity=identity,
                    intent=intent,
                    policy_hits=policy_hits,
                    plan=plan,
                    steps=steps,
                    status="DENIED",
                    result=result,
                    user=user,
                    source_snapshot=source_snapshot,
                )
            result["released"] = True
            self._step(
                steps,
                7,
                "DELIVER",
                "PASSED",
                {"output_mode": result["output_mode"], "raw_data_returned": False, "result_fields": list(result)},
            )
            return self._finalize(
                request_id=request_id,
                current_trace_id=current_trace_id,
                identity=identity,
                intent=intent,
                policy_hits=policy_hits,
                plan=plan,
                steps=steps,
                status="SUCCEEDED",
                result=result,
                user=user,
                source_snapshot=source_snapshot,
            )
        except Exception as exc:
            self._step(steps, 5, "EXECUTE", "FAILED", {"error_type": type(exc).__name__})
            self._step(steps, 6, "AUDIT", "SKIPPED", {"reason": "EXECUTION_FAILED"})
            self._step(steps, 7, "DELIVER", "BLOCKED", {"reason": "EXECUTION_FAILED"})
            return self._finalize(
                request_id=request_id,
                current_trace_id=current_trace_id,
                identity=identity,
                intent=intent,
                policy_hits=policy_hits,
                plan=plan,
                steps=steps,
                status="FAILED",
                result={"released": False, "reason": "EXECUTION_FAILED", "error_type": type(exc).__name__, "raw_data_returned": False},
                user=user,
                source_snapshot=source_snapshot,
            )


def trusted_execution_status() -> dict[str, Any]:
    return {
        "controller": "TRUSTWORTHY_EXECUTION_CONTROLLER_V1",
        "availability": "TEST_FIXTURE_ONLY" if settings.app_env in {"development", "test"} else "NOT_CONFIGURED",
        "security_boundary": {
            "api_raw_records_returned": False,
            "cross_domain_non_export_verified": False,
            "anti_inference_check": "LOCAL_OUTPUT_CHECK",
            "topology_coordinates_released": False,
        },
        "audit": {
            "asynchronous_evidence_recording": True,
            "evidence_backend": LocalEvidenceLedgerAdapter.code,
            "result_hash_required": True,
        },
        "workflow_steps": [
            "INGEST",
            "AUTHENTICATE",
            "RESOLVE",
            "ARBITRATE",
            "EXECUTE",
            "AUDIT",
            "DELIVER",
            "LOG",
        ],
        "accuracy_review": {
            "automatic_check": "DETERMINISTIC_RECONCILIATION",
            "manual_confirmation_required": True,
            "states": ["PENDING", "CONFIRMED", "REJECTED", "NOT_APPLICABLE"],
        },
        "policy_engine": DynamicPolicyEngine().catalog(),
    }
