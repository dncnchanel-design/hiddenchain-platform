from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DidIdentity, Organization, utc_now
from ..trust_models import AgentPermission, AgentTool
from .adapters import AGENT_DEFINITIONS


CONTROLLED_TOOL_BINDINGS: tuple[dict[str, Any], ...] = (
    {
        "tool_code": "WorkflowEngine",
        "tool_name": "TTC workflow orchestration",
        "service_code": "TTC_STATE_MACHINE_V1",
        "capability_label": "LOCAL_REAL",
        "agents": ["ORCHESTRATOR"],
    },
    {
        "tool_code": "EDCAdapter+OPAAdapter",
        "tool_name": "Data-space negotiation and policy decision",
        "service_code": "HCDS_CONNECTOR_WITH_OPA_V1",
        "capability_label": "ADAPTER",
        "agents": ["DATA_ACCESS"],
    },
    {
        "tool_code": "RuleRAG+DSLValidator+SigningGate",
        "tool_name": "Rule package validation and freeze preparation",
        "service_code": "SIGNED_RULE_PACKAGE_V1",
        "capability_label": "LOCAL_REAL",
        "agents": ["RULE_CONTRACT"],
    },
    {
        "tool_code": "GridBoundaryAdapter+SecurityGate",
        "tool_name": "Grid boundary security gate",
        "service_code": "PANDAPOWER_GRID_GATE_V1",
        "capability_label": "LOCAL_REAL",
        "agents": ["AUDIT_RISK"],
    },
    {
        "tool_code": "CommitmentJoin+LocalControlledCompute+DeterministicEngine",
        "tool_name": "Deterministic commitment-referenced settlement",
        "service_code": "LOCAL_CONTROLLED_SETTLEMENT_V1",
        "capability_label": "LOCAL_REAL",
        "agents": ["SECURE_SETTLEMENT"],
    },
    {
        "tool_code": "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
        "tool_name": "Evidence verification and risk classification",
        "service_code": "LOCAL_EVIDENCE_LEDGER_V1",
        "capability_label": "DEMO",
        "agents": ["AUDIT_RISK"],
    },
    {
        "tool_code": "ReportTemplate+CitationRAG+CredentialService",
        "tool_name": "Evidence-grounded audit report",
        "service_code": "AUDIT_REPORT_V1",
        "capability_label": "LOCAL_REAL",
        "agents": ["REPORT_EXPLAIN"],
    },
    {
        "tool_code": "DeepSeekChatCompletions",
        "tool_name": "Optional evidence-grounded explanation",
        "service_code": "DEEPSEEK_CHAT_ADAPTER",
        "capability_label": "ADAPTER",
        "agents": [item["code"] for item in AGENT_DEFINITIONS],
    },
    {
        "tool_code": "TemplateAuditFallback",
        "tool_name": "Deterministic audit explanation fallback",
        "service_code": "TEMPLATE_AUDIT_V1",
        "capability_label": "LOCAL_REAL",
        "agents": ["AUDIT_RISK"],
    },
)


def _permission_is_current(permission: AgentPermission) -> bool:
    now = utc_now()
    return (
        permission.status == "ACTIVE"
        and permission.valid_from <= now
        and (permission.expires_at is None or permission.expires_at > now)
        and bool({"INVOKE", "*"} & {str(item).upper() for item in permission.operations_json})
        and bool((permission.scope_json or {}).get("allow_all_tasks"))
    )


def ensure_agent_tool_catalog(db: Session) -> dict[str, int]:
    """Idempotently register controlled Tools and least-privilege grants.

    The catalog never creates identities.  Production Agent DIDs must be
    provisioned through the identity lifecycle before a permission is emitted.
    """

    definitions = {item["code"]: item for item in AGENT_DEFINITIONS}
    tools_created = 0
    tools_updated = 0
    permissions_created = 0
    for binding in CONTROLLED_TOOL_BINDINGS:
        tool = db.scalar(
            select(AgentTool).where(AgentTool.tool_code == binding["tool_code"])
        )
        if tool is None:
            tool = AgentTool(
                tool_code=binding["tool_code"],
                tool_name=binding["tool_name"],
                service_code=binding["service_code"],
                description=(
                    "Repository-controlled Tool. Direct database or arbitrary shell access "
                    "is not part of this permission."
                ),
                input_schema_json={"type": "object", "additionalProperties": False},
                output_schema_json={"type": "object"},
                timeout_seconds=30,
                capability_label=binding["capability_label"],
                enabled=True,
            )
            db.add(tool)
            db.flush()
            tools_created += 1
        else:
            desired = {
                "tool_name": binding["tool_name"],
                "service_code": binding["service_code"],
                "capability_label": binding["capability_label"],
                "enabled": True,
            }
            changed = False
            for field, value in desired.items():
                if getattr(tool, field) != value:
                    setattr(tool, field, value)
                    changed = True
            if changed:
                tools_updated += 1
        for agent_code in binding["agents"]:
            definition = definitions[agent_code]
            identity = db.get(DidIdentity, definition["did"])
            if identity is None or identity.credential_status != "VALID":
                continue
            existing_permissions = db.scalars(
                select(AgentPermission)
                .where(
                    AgentPermission.agent_did == definition["did"],
                    AgentPermission.tool_id == tool.tool_id,
                    AgentPermission.status == "ACTIVE",
                )
                .order_by(AgentPermission.created_at.desc())
            ).all()
            if any(_permission_is_current(item) for item in existing_permissions):
                continue
            db.add(
                AgentPermission(
                    agent_did=definition["did"],
                    agent_role=agent_code,
                    tool_id=tool.tool_id,
                    operations_json=["INVOKE"],
                    scope_json={"allow_all_tasks": True},
                    status="ACTIVE",
                    granted_by_did="did:hiddenchain:org:org-exchange-t01",
                    grant_reason="Repository-controlled least-privilege workflow binding",
                )
            )
            permissions_created += 1
    db.flush()
    return {
        "tools_created": tools_created,
        "tools_updated": tools_updated,
        "permissions_created": permissions_created,
    }


def agent_tool_catalog_readiness(db: Session) -> dict[str, Any]:
    """Verify that every required Agent DID, Tool and grant is executable."""

    definitions = {item["code"]: item for item in AGENT_DEFINITIONS}
    tools = {
        item.tool_code: item
        for item in db.scalars(select(AgentTool)).all()
    }
    identities = {
        item.did_id: item
        for item in db.scalars(select(DidIdentity)).all()
    }
    organizations = {
        item.org_id: item
        for item in db.scalars(select(Organization)).all()
    }
    permissions = db.scalars(select(AgentPermission)).all()

    issues: list[str] = []
    required_bindings = 0
    for binding in CONTROLLED_TOOL_BINDINGS:
        tool = tools.get(binding["tool_code"])
        if tool is None:
            issues.append(f"TOOL_MISSING:{binding['tool_code']}")
        elif not tool.enabled:
            issues.append(f"TOOL_DISABLED:{binding['tool_code']}")
        elif (
            tool.service_code != binding["service_code"]
            or tool.capability_label != binding["capability_label"]
        ):
            issues.append(f"TOOL_DEFINITION_STALE:{binding['tool_code']}")

        for agent_code in binding["agents"]:
            required_bindings += 1
            did = str(definitions[agent_code]["did"])
            identity = identities.get(did)
            if identity is None:
                issues.append(f"AGENT_DID_MISSING:{agent_code}")
                continue
            if identity.credential_status != "VALID":
                issues.append(f"AGENT_DID_INVALID:{agent_code}")
                continue
            if identity.org_id:
                organization = organizations.get(identity.org_id)
                if organization is None or organization.status != "ACTIVE":
                    issues.append(f"AGENT_ORGANIZATION_INACTIVE:{agent_code}")
                    continue
            if tool is None:
                continue
            valid_grant = any(
                permission.agent_did == did
                and permission.tool_id == tool.tool_id
                and _permission_is_current(permission)
                for permission in permissions
            )
            if not valid_grant:
                issues.append(
                    f"AGENT_PERMISSION_MISSING:{agent_code}:{binding['tool_code']}"
                )

    return {
        "status": "READY" if not issues else "NOT_READY",
        "required_agent_count": len(definitions),
        "required_tool_count": len(CONTROLLED_TOOL_BINDINGS),
        "required_permission_count": required_bindings,
        "issue_count": len(issues),
        "issues": issues,
    }
