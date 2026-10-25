"""Intent extraction only. Authority and returned facts belong to local services."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..config import settings
from .llm import DeepSeekUnavailable, translate_assistant_intent

DESCRIPTIONS = {
    "LIST_DATA_ASSETS": "默认数据盘点：当前账号所属主体登记的数据、资产清单、数量；不要求已有使用授权",
    "LIST_VISIBLE_DATA_ASSETS": "明确询问他方发布或当前可浏览的资源目录；可见不表示已获使用权",
    "LIST_AUTHORIZED_DATA_ASSETS": "仅明确询问已获授权、能使用或能用于计算的资源时选择；不替代本方登记的数据清单",
    "CHECK_ASSET_INTEGRITY": "检查某项数据的版本、护照、质量和完整性",
    "LIST_AUTHORIZATIONS": "列出本方申请或收到的授权申请及其状态",
    "QUERY_AUTHORIZATION_STATUS": "查询某一条授权申请的状态",
    "LIST_TASKS": "列出可见的结算和隐私计算任务及其状态",
    "CHECK_TTC_STATUS": "查询某一个任务的状态或执行进度",
    "LIST_AUDIT_REPORTS": "列出当前监管审计范围内的报告",
    "EXPLAIN_AUDIT": "解释某份报告或某个任务的审计事实",
    "VERIFY_EVIDENCE_SUMMARY": "核验某个任务的证据与摘要",
    "LIST_NOTIFICATIONS": "查看当前账号已有的通知、提醒和待办",
    "SYSTEM_OVERVIEW": "管理员查询系统健康、组织账号数量、能力配置等技术状态",
    "ASSISTANT_HELP": "问候、了解可用功能、询问操作方法，或需要澄清",
    "NAVIGATE_QUERY": "查询能源数值、求和平均趋势等，转到受控数据查询流程",
    "NAVIGATE_ELECTRICITY": "测算电价电费、报价、发电成本，转到电力计算窗口",
    "SUBMIT_USAGE_REQUEST": "明确要求起草某资产的数据使用申请，需人工复核",
    "APPROVE_USAGE_REQUEST": "明确要求通过某条授权申请，需人工复核",
    "REJECT_USAGE_REQUEST": "明确要求拒绝某条授权申请，需人工复核",
    "REVOKE_USAGE_AUTHORIZATION": "明确要求撤销某条授权，需人工复核",
    "ADVANCE_TTC_STATE": "明确要求推进某结算任务状态，需人工复核",
    "UNKNOWN_INTENT": "不支持、无法确定或一条消息要求多个独立操作",
}
CANONICAL = {
    "检查资产完整性": "CHECK_ASSET_INTEGRITY", "查询授权申请状态": "QUERY_AUTHORIZATION_STATUS",
    "检查可信任务状态": "CHECK_TTC_STATUS", "核验证据摘要": "VERIFY_EVIDENCE_SUMMARY",
    "解释审计报告": "EXPLAIN_AUDIT", "我有哪些数据": "LIST_DATA_ASSETS",
    "查看授权列表": "LIST_AUTHORIZATIONS", "查看任务列表": "LIST_TASKS",
    "查看通知": "LIST_NOTIFICATIONS", "系统运行情况": "SYSTEM_OVERVIEW",
    "我能用哪些数据": "LIST_AUTHORIZED_DATA_ASSETS", "查看可见数据": "LIST_VISIBLE_DATA_ASSETS",
    "查看审计报告": "LIST_AUDIT_REPORTS",
    "你能做什么": "ASSISTANT_HELP",
}
WRITE_WORDS = {
    "SUBMIT_USAGE_REQUEST": ("提交", "申请使用", "申请一下", "发起申请", "借用", "submit", "apply"),
    "APPROVE_USAGE_REQUEST": ("批准", "同意", "通过", "approve", "accept"),
    "REJECT_USAGE_REQUEST": ("拒绝", "驳回", "不通过", "reject", "deny"),
    "REVOKE_USAGE_AUTHORIZATION": ("撤销", "收回", "终止授权", "取消授权", "revoke"),
    "ADVANCE_TTC_STATE": ("推进", "下一步", "下一阶段", "advance"),
}
DATA_LIST_ACTIONS = frozenset({"LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS", "LIST_AUTHORIZED_DATA_ASSETS"})
TASK_WORDS = ("任务", "作业", "计算工作", "计算活", "活儿", "ttc", "transaction capsule")


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _positive_text(text: str) -> str:
    clauses = re.split(r"[，,。；;\n]|(?:而是|改为|但是|不过|只要|只想|只需|仅需|只查询|只查)", text)
    return "，".join(c for c in clauses if c.strip() and not re.search(r"不要|别(?=(?:再|先|帮我|给我)?(?:查|看|批准|同意|通过|拒绝|驳回|撤|收回|推进|提交|申请|执行|运行|删除|导出|上传))|不用|不想|不需要|不打算|勿|\bdo not\b|\bdon't\b|\bnever\b", c, re.I))


def _question(text: str) -> bool:
    return bool(re.search(r"(?:了吗|了没|没有|是否|是不是|怎么样|批下来|到哪|怎么|如何|哪些|谁|多少|几条|几份|列出|查看|查询|看看|显示|盘点|清单|列表|[?？吗]|\bhow\b)", text))


def _write_requested(text: str, action: str) -> bool:
    """A historical verb mention cannot authorize even a review request."""
    if _question(text):
        return False
    command = re.sub(r"^(?:(?:请|麻烦|帮我|替我|给我|你帮我|我想要|我想|我希望|我要|我需要|先|现在|直接|只|仅)|please\s+)+", "", text).strip()
    return any(command.startswith(word) for word in WRITE_WORDS[action]) or bool(re.match(r"^(?:把|将)", command) and _has(command, WRITE_WORDS[action]))


def _owned_inventory_question(text: str) -> bool:
    """Neutral ownership questions default to registration, never usage rights."""
    return (_has(text, ("数据", "资产", "资源", "资料", "dataset", "asset"))
            and bool(re.search(r"(?:我(?:们)?|我方|本方|本公司|本机构|本单位|咱们)(?:(?:现在|目前|当前|现有|名下|这边|手头|手上|的|这家|公司|都|自己)){0,4}(?:有|持有|拥有|登记|存|挂|数据|资产|资源|资料|哪些|什么|多少|几[项份条])", text))
            and bool(re.search(r"哪些|什么|多少|几[项份条]|清单|列表|盘点", text))
            and not _has(text, ("授权", "可用", "能用", "可以用", "使用", "计算", "可见", "能看到", "浏览", "别家", "别人", "其他", "对方", "他方", "他们", "外部", "合作公司", "合作方", "供应商", "供应方", "质量", "完整", "护照", "版本", "哈希")))


def _specific_read(text: str, local: str, action: str, entity_type: str | None) -> str:
    if local in {"LIST_TASKS", "CHECK_TTC_STATUS"} and action in DATA_LIST_ACTIONS and _has(text, TASK_WORDS):
        return local
    pairs = {"CHECK_ASSET_INTEGRITY": {"LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS", "LIST_AUTHORIZED_DATA_ASSETS"},
             "QUERY_AUTHORIZATION_STATUS": {"LIST_AUTHORIZATIONS"}, "CHECK_TTC_STATUS": {"LIST_TASKS"},
             "EXPLAIN_AUDIT": {"LIST_AUDIT_REPORTS"}}
    if _has(text, ("哪些", "全部", "所有", "列表", "清单", "列出", "多少", "几个", "几条", "几份", "这些", "那些", "各个", "每个", "都", "未完成", "失败的")):
        return action
    if action in pairs.get(local, set()):
        return local
    if _has(text, ("这批", "这项", "这个", "该", "眼前", "刚才", "上一条")):
        if action == "LIST_TASKS" and entity_type in {"settlement_task", "privacy_compute_job"}:
            return "CHECK_TTC_STATUS"
        if action == "LIST_AUTHORIZATIONS" and entity_type == "data_usage_request":
            return "QUERY_AUTHORIZATION_STATUS"
    return action


def _local_action(text: str) -> str:
    if _has(text, ("你好", "您好", "能做什么", "会做什么", "怎么用", "如何使用", "帮助", "help", "hello")) or re.search(r"能.{0,5}做什么", text) or re.match(r"^(?:怎么|如何)", text):
        return "ASSISTANT_HELP"
    if _has(text, ("系统", "平台", "服务", "节点", "组织", "账号", "能力配置")) and _has(text, ("运行", "健康", "状态", "正常", "数量", "多少", "统计", "配置", "概况")):
        return "SYSTEM_OVERVIEW"
    if _has(text, ("通知", "消息", "提醒", "待办", "待我", "等我处理", "notification")):
        return "LIST_NOTIFICATIONS"
    if _has(text, ("电费", "报价", "发电成本", "lmp", "smp", "网损分摊", "固定成本", "电价测算", "峰平谷")) or ("电" in text and _has(text, ("多少钱", "交多少", "费用"))):
        return "NAVIGATE_ELECTRICITY"
    # Writes must be requested, rather than merely mentioned in a status question.
    if not _question(text) and (not _has(text, ("状态", "进度", "status")) or _has(text, WRITE_WORDS["ADVANCE_TTC_STATE"])):
        for action in ("REVOKE_USAGE_AUTHORIZATION", "REJECT_USAGE_REQUEST", "APPROVE_USAGE_REQUEST", "SUBMIT_USAGE_REQUEST", "ADVANCE_TTC_STATE"):
            if _write_requested(text, action):
                return action
    if _has(text, ("数据", "资产", "资源")) and _has(text, ("可申请", "可以申请", "别人", "别家", "其他", "可见", "能看到", "浏览")):
        return "LIST_VISIBLE_DATA_ASSETS"
    if _has(text, ("数据", "资产", "资源")) and _has(text, ("已获准", "已授权", "能用", "可用", "可以用", "能让我用", "跑计算")):
        return "LIST_AUTHORIZED_DATA_ASSETS"
    if _has(text, ("统计", "汇总", "求和", "平均", "走势", "趋势")) and _has(text, ("数据", "按月", "按日", "按年", "数量")):
        return "NAVIGATE_QUERY"
    if _has(text, ("数据", "资产", "资源")) and _has(text, ("完整", "质量", "校验", "缺失", "缺字段", "护照", "版本", "哈希", "integrity", "passport")):
        return "CHECK_ASSET_INTEGRITY"
    if _has(text, ("证据", "存证", "哈希", "evidence")):
        return "VERIFY_EVIDENCE_SUMMARY"
    if _has(text, ("审计", "报告", "audit", "report")):
        return "LIST_AUDIT_REPORTS" if _has(text, ("有哪些", "列表", "清单", "列出", "所有", "全部", "多少", "几份")) else "EXPLAIN_AUDIT"
    if _has(text, ("申请", "授权", "许可", "审批", "批下来", "access request", "authorization")):
        return "LIST_AUTHORIZATIONS" if _has(text, ("哪些", "列表", "清单", "那些", "列出", "全部", "所有", "多少", "几条", "待审核", "待审批")) else "QUERY_AUTHORIZATION_STATUS"
    if _has(text, ("负荷", "发电量", "供气", "供热", "库存", "供应量", "产量", "风电", "光伏", "用电量")) and (_has(text, ("平均", "总和", "合计", "趋势", "最大", "最小", "统计", "求和")) or re.search(r"\d+月|\d{4}年", text)):
        return "NAVIGATE_QUERY"
    if _has(text, TASK_WORDS):
        return "LIST_TASKS" if _has(text, ("哪些", "列表", "清单", "列出", "全部", "所有", "多少", "几个", "未完成", "失败的", "捋一遍", "梳理", "盘点")) else "CHECK_TTC_STATUS"
    if _has(text, ("数据", "资产", "资源", "dataset", "asset")):
        if _has(text, ("完整", "质量", "校验", "缺失", "缺字段", "护照", "integrity", "passport")):
            return "CHECK_ASSET_INTEGRITY"
        return "LIST_AUTHORIZED_DATA_ASSETS" if _has(text, ("已获准", "已授权", "能用", "可用", "可以用", "能让我用")) else "LIST_DATA_ASSETS"
    return "UNKNOWN_INTENT"


def _selection(text: str) -> int | None:
    match = re.search(r"第\s*([一二三四五六七八九十\d]+)\s*(?:个|项|条|份)?", text)
    if not match:
        return 1 if re.fullmatch(r"(?:选|选中|就)?第一(?:个|项|条)", text) else None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw) if 1 <= int(raw) <= 20 else None
    numbers = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}
    return 10 + numbers[raw[1:]] if raw.startswith("十") and raw[1:] in numbers and len(raw) == 2 else 20 if raw == "二十" else numbers.get(raw)


def understand(content: str, *, available_actions: list[str], previous_action: str | None = None, entity_type: str | None = None, history: list[str] | None = None) -> dict[str, Any]:
    original = unicodedata.normalize("NFKC", content).strip()
    text = original.lower()
    effective = _positive_text(original)
    positive = effective.lower()
    status_filter = next((status for words, status in [(("未读", "没看过"), "UNREAD"), (("已读",), "READ"), (("失败", "出错", "被拒", "未通过"), "FAILED"), (("已经批准", "已批准", "审批通过"), "APPROVED"), (("未完成", "没跑完", "还没结束"), "NOT_FINISHED"), (("待审批", "待审核", "待处理", "排队"), "PENDING"), (("运行中", "正在执行", "执行中"), "RUNNING"), (("已完成", "成功", "已结束"), "SUCCEEDED")] if _has(positive, words)), None)
    base: dict[str, Any] = {"source": "LOCAL", "model_used": False, "search": None, "selection": _selection(positive), "effective_text": effective, "status_filter": status_filter}
    if not positive:
        return {**base, "action": "ASSISTANT_HELP", "clarify": True, "message": "好的，未执行该操作。你希望查询哪一项内容？"}
    if len(set(re.findall(r"第\s*([一二三四五六七八九十\d]+)", positive))) > 1:
        return {**base, "action": "ASSISTANT_HELP", "clarify": True, "message": "你选择了多个序号，请先选择本次要处理的一项。"}
    if _has(positive, ("忽略权限", "绕过权限", "绕过授权", "关闭审计", "所有账号密码", "系统密钥", "直接执行sql", "原始数据", "原始明细", "原始记录", "删除", "清空", "抹掉", "修改密码", "导出", "上传", "delete ", "drop table")):
        return {**base, "action": "UNKNOWN_INTENT", "clarify": True, "blocked": True, "message": "这项操作不能由助手执行。可以查询当前账号范围内的目录、授权、任务或系统状态。"}
    parts = [part for part in re.split(r"然后|并且|同时|以及|顺便|并(?=批准|拒绝|撤销|删除|推进)|再(?:帮我)?(?=批准|拒绝|撤销|推进)", positive) if part]
    actions = {_local_action(part) for part in parts} - {"UNKNOWN_INTENT", "ASSISTANT_HELP"}
    if len(actions) > 1:
        return {**base, "action": "ASSISTANT_HELP", "clarify": True, "message": "这句话包含多个操作，请先选择一项查询或复核动作。"}
    local = _local_action(positive)
    if base["selection"] is not None or re.fullmatch(r"(?:这个|那个|刚才那个|刚才的|上一条|这条|它|再查一次)(?:呢|怎么样|的状态)?[?？]?", positive):
        action = local if local != "UNKNOWN_INTENT" else previous_action
        return {**base, "action": action or "ASSISTANT_HELP", "clarify": not bool(action), "reference": True}
    if positive in CANONICAL:
        return {**base, "action": CANONICAL[positive], "clarify": False}
    quoted = re.search(r'[“"《]([^”"》]{1,96})[”"》]', effective)
    if quoted:
        base["search"] = quoted.group(1)
    if settings.deepseek_enabled and settings.deepseek_api_key:
        try:
            # Classification must not change with an actor's permissions. The
            # caller's available_actions remain enforced by the local executor.
            result = translate_assistant_intent(question=content, context={"action_catalog": DESCRIPTIONS, "previous_action": previous_action, "entity_type": entity_type, "recent_user_questions": [s[:1000] for s in (history or [])[-4:]]})
            payload = result["payload"]
            if not isinstance(payload, dict) or set(payload) - {"action", "target_text", "choice_index", "clarify"}:
                raise ValueError("invalid fields")
            action = payload.get("action")
            if action not in DESCRIPTIONS or not isinstance(payload.get("clarify"), bool):
                raise ValueError("invalid action")
            choice = payload.get("choice_index")
            if choice is not None and (isinstance(choice, bool) or not isinstance(choice, int) or not 1 <= choice <= 20):
                raise ValueError("invalid choice")
            if choice is not None and choice != base["selection"]:
                raise ValueError("choice not explicitly requested")
            target = payload.get("target_text")
            if target is not None and (not isinstance(target, str) or len(target) > 96 or target not in effective):
                raise ValueError("invented target")
            if action in WRITE_WORDS and not _write_requested(positive, action):
                action = local if local not in WRITE_WORDS else "ASSISTANT_HELP"
            if action in DATA_LIST_ACTIONS and _owned_inventory_question(positive):
                base["scope_rule"] = "OWNED_REGISTRATION_INVENTORY"
                base["model_action"] = action
                action = "LIST_DATA_ASSETS"
            specific = _specific_read(positive, local, action, entity_type)
            if specific != action:
                base["model_action"] = action
                base["selection_rule"] = "DETAIL_TARGET_SELECTED_BY_SERVER"
                action = specific
            if action == "UNKNOWN_INTENT" and local != "UNKNOWN_INTENT":
                return {**base, "action": local, "clarify": False, "source": "FALLBACK", "model_used": False, "fallback_reason": "MODEL_INTENT_UNRESOLVED", "model": result.get("model")}
            return {**base, "action": action, "search": target or base["search"], "selection": choice or base["selection"], "clarify": payload["clarify"], "source": "MODEL", "model_used": True, "model": result.get("model")}
        except (DeepSeekUnavailable, ValueError, TypeError, KeyError):
            base["source"] = "FALLBACK"
            base["fallback_reason"] = "MODEL_UNAVAILABLE_OR_INVALID"
    return {**base, "action": local, "clarify": local == "UNKNOWN_INTENT"}
