import { Cable, CheckCircle2, Database, FileSpreadsheet, KeyRound, Plus, RefreshCw, ServerCog, ShieldCheck, X } from "lucide-react";
import { useRef, useState } from "react";
import { ApiError, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { DOMAIN_LABELS } from "../../../types";
import { PageFrame } from "../components/PageFrame";
import { Badge, Button, Card, CardContent, CardHeader, FieldLabel, Input, RemoteState, Select, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { createAccessRule, loadAccessRules, revokeAccessRule, type AccessRule } from "../trusted-space-api";

const sourceTypes = ["Excel", "CSV", "PostgreSQL", "MySQL", "SQL Server", "SQLite"];
const fixedFunctions = ["求和", "平均值", "最大值", "最小值", "计数", "中位数", "增长率", "同比", "环比", "分组汇总", "阈值判断", "趋势", "PSI", "MPC 聚合份额"];
const fixedFunctionOptions = [
  { value: "sum", label: "求和" }, { value: "average", label: "平均值" }, { value: "max", label: "最大值" },
  { value: "min", label: "最小值" }, { value: "count", label: "计数" }, { value: "median", label: "中位数" },
  { value: "growth_rate", label: "增长率" }, { value: "yoy", label: "同比" }, { value: "mom", label: "环比" },
  { value: "group_by", label: "分组汇总" }, { value: "threshold", label: "阈值判断" }, { value: "trend", label: "趋势" },
  { value: "psi", label: "PSI" }, { value: "mpc_aggregation", label: "MPC 聚合份额" },
];

export function ConnectorPage() {
  const { context } = useTrustedSpaceContext();
  const domain = context?.current_subject.energy_domain || "";
  const domainLabel = DOMAIN_LABELS[domain] || "未配置能源范围";
  const configured = context?.capabilities.data_space_connector?.readiness === "CONFIGURED";
  const canManageRules = context?.actor.permissions?.includes("MANAGE_RULES") === true;
  const rulesRemote = useRemote((signal) => loadAccessRules({}, signal), []);
  const [ruleCode, setRuleCode] = useState("DAILY_STATS");
  const [resourceId, setResourceId] = useState("generation");
  const [functionCode, setFunctionCode] = useState("average");
  const [mode, setMode] = useState<"AUTO_CALL" | "ENTERPRISE_APPROVAL" | "FORBIDDEN">("AUTO_CALL");
  const [ruleBusy, setRuleBusy] = useState(false);
  const [ruleError, setRuleError] = useState("");
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});

  async function saveRule() {
    if (!ruleCode.trim() || !resourceId || !functionCode) {
      setRuleError("规则编号、资源和固定函数不能为空。");
      return;
    }
    setRuleBusy(true);
    setRuleError("");
    try {
      const fingerprint = `${ruleCode}:${resourceId}:${functionCode}:${mode}`;
      const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], "access-rule", fingerprint);
      idempotencyKeys.current[fingerprint] = key;
      await createAccessRule({
        rule_code: ruleCode.trim(),
        energy_domain: domain || undefined,
        resource_id: resourceId,
        function_code: functionCode,
        mode,
        scope: { output_mode: "AGGREGATE_ONLY", granularity: "DAY" },
        limits: { minimum_record_count: 3, max_duration_days: 31, output_mode: "AGGREGATE_ONLY" },
      }, { idempotencyKey: key.key });
      await rulesRemote.reload();
    } catch (error) {
      setRuleError(error instanceof ApiError ? error.message : "规则保存失败，请重试。");
    } finally {
      setRuleBusy(false);
    }
  }

  async function revokeRule(rule: AccessRule) {
    setRuleBusy(true);
    setRuleError("");
    try {
      const key = prepareIdempotencyKey(idempotencyKeys.current[rule.rule_id], "revoke-access-rule", rule.rule_id);
      idempotencyKeys.current[rule.rule_id] = key;
      await revokeAccessRule(rule.rule_id, { idempotencyKey: key.key });
      await rulesRemote.reload();
    } catch (error) {
      setRuleError(error instanceof ApiError ? error.message : "规则撤销失败，请重试。");
    } finally {
      setRuleBusy(false);
    }
  }

  return <PageFrame title="数据连接" description="企业侧连接器读取本企业允许的数据范围，平台不接收也不保存原始数据。">
    <div className="trusted-connector-hero">
      <div className="trusted-connector-symbol"><Cable size={27} /></div>
      <div><h2>{domainLabel}企业连接器</h2><p>当前企业范围：{domainLabel}。连接器在企业侧执行授权核验、固定函数计算和结果签名。</p></div>
      <Badge tone={configured ? "success" : "warning"} dot>{configured ? "已登记" : "待配置"}</Badge>
    </div>

    <div className="trusted-connector-grid">
      <Card>
        <CardHeader><SurfaceHeader title="可信数据空间边界" description="平台侧与企业侧的职责分开" /></CardHeader>
        <CardContent className="trusted-boundary-steps">
          <div><span><Database size={17} /></span><strong>原始数据留在企业</strong><p>文件和数据库记录只存在企业内网或本演示连接器的独立数据存储中。</p></div>
          <div><span><ShieldCheck size={17} /></span><strong>企业决定公布范围</strong><p>目录、字段、期间、粒度、用途、对象、期限和次数由企业策略控制。</p></div>
          <div><span><ServerCog size={17} /></span><strong>计算在连接器内完成</strong><p>平台发送已签名任务，连接器验证授权后运行固定函数，只返回受控结果。</p></div>
          <div><span><KeyRound size={17} /></span><strong>结果使用真实数字签名</strong><p>企业私钥只配置在连接器密钥存储中，平台仅登记公钥并验证 Ed25519 签名。</p></div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><SurfaceHeader title="可连接的数据源" description="交付企业后可按内网环境启用" /></CardHeader>
        <CardContent className="trusted-source-list">{sourceTypes.map((item) => <div key={item}><FileSpreadsheet size={15} /><span>{item}</span><CheckCircle2 size={14} /></div>)}</CardContent>
      </Card>
    </div>

    <Card className="trusted-functions-card">
      <CardHeader><SurfaceHeader title="固定函数白名单" description="行为接近 Excel 公式，不允许任意代码、任意 SQL 或 AI 脚本" /></CardHeader>
      <CardContent><div className="trusted-function-chips">{fixedFunctions.map((item) => <span key={item}>{item}</span>)}</div></CardContent>
    </Card>

    <Card>
      <CardHeader><SurfaceHeader title="本主体调用规则" description="规则由本主体制定和批准；修改会生成新版本，撤销只影响未来调用。" action={<Button variant="secondary" size="sm" onClick={() => void rulesRemote.reload()} busy={rulesRemote.refreshing}><RefreshCw size={14} />刷新</Button>} /></CardHeader>
      <CardContent>
        <RemoteState loading={rulesRemote.loading} error={rulesRemote.error} onRetry={() => void rulesRemote.reload()} empty={!rulesRemote.loading && !rulesRemote.error && !rulesRemote.data?.items.length} emptyLabel="当前没有已发布规则" />
        {rulesRemote.data?.items.length ? <div className="trusted-task-list">{rulesRemote.data.items.map((rule) => <div className="trusted-task-row" key={rule.rule_id}><span className="trusted-task-icon"><ShieldCheck size={15} /></span><span className="trusted-task-copy"><strong>{rule.rule_code} · {rule.version}</strong><small>{rule.resource_id} / {rule.function_code} · {rule.mode === "AUTO_CALL" ? "命中后可自动调用" : rule.mode === "FORBIDDEN" ? "禁止外部调用" : "需要企业审批"}</small></span><StatusBadge value={rule.status} />{canManageRules && rule.status === "ACTIVE" && <Button variant="ghost" size="icon" aria-label={`撤销规则 ${rule.rule_code}`} onClick={() => void revokeRule(rule)} disabled={ruleBusy}><X size={14} /></Button>}</div>)}</div> : null}
        {canManageRules && <div className="trusted-option-grid"><FieldLabel htmlFor="rule-code">规则编号</FieldLabel><Input id="rule-code" value={ruleCode} onChange={(event) => setRuleCode(event.target.value)} /><FieldLabel htmlFor="rule-resource">资源</FieldLabel><Input id="rule-resource" value={resourceId} onChange={(event) => setResourceId(event.target.value)} /><FieldLabel>固定函数</FieldLabel><Select value={functionCode} onChange={(event) => setFunctionCode(event.target.value)} options={fixedFunctionOptions} /><FieldLabel>调用方式</FieldLabel><Select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} options={[{ value: "AUTO_CALL", label: "命中规则自动调用" }, { value: "ENTERPRISE_APPROVAL", label: "必须企业审批" }, { value: "FORBIDDEN", label: "禁止外部调用" }]} /><Button variant="primary" size="sm" onClick={() => void saveRule()} busy={ruleBusy}><Plus size={14} />发布新版本</Button></div>}
        {ruleError && <p className="trusted-query-error" role="alert">{ruleError}</p>}
      </CardContent>
    </Card>

    <div className="trusted-connector-note"><ShieldCheck size={16} /><div><strong>公开环境是演示部署</strong><p>正式交付后，每家企业在自己的内网部署连接器与私钥，平台只负责目录协调、授权流转、任务编排和审计追溯。</p></div></div>
  </PageFrame>;
}
