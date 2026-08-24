import { useEffect, useMemo, useState } from "react";
import { Calculator, CheckCircle2, FileSignature, Search, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PageFrame } from "../components/PageFrame";
import { QueryResultChart } from "../components/QueryResultChart";
import { Badge, Button, Card, CardContent, CardHeader, FieldLabel, Input, Select, SurfaceHeader, Textarea } from "../components/ui-primitives";
import { confirmTrustedQuery, executeTrustedQuery, loadAccessRules, loadUsageRequests, parseTrustedQuery, type AccessRule, type ControlledQueryResult, type QueryIntent, type UsageRequest } from "../trusted-space-api";
import { useTrustedSpaceContext } from "../trusted-space-context";

const domainOptions = [
  { value: "", label: "请选择能源种类" },
  { value: "electricity", label: "电力" },
  { value: "coal", label: "煤炭" },
  { value: "heat", label: "热能" },
  { value: "gas", label: "天然气" },
  { value: "oil", label: "石油" },
];

const resourceOptions: Record<string, Array<{ value: string; label: string }>> = {
  electricity: [{ value: "generation", label: "发电量" }, { value: "supply", label: "供电量" }, { value: "load", label: "用电负荷" }, { value: "price", label: "交易价格" }],
  coal: [{ value: "production", label: "煤炭产量" }, { value: "supply", label: "煤炭供应量" }, { value: "consumption", label: "煤炭消费量" }, { value: "inventory", label: "煤炭库存" }, { value: "transport", label: "煤炭运输量" }, { value: "price", label: "煤炭价格" }],
  heat: [{ value: "supply", label: "供热量" }, { value: "load", label: "热负荷" }, { value: "fuel", label: "燃料消耗" }, { value: "loss", label: "管网损耗率" }, { value: "supply_temperature", label: "供水温度" }, { value: "return_temperature", label: "回水温度" }, { value: "price", label: "供热价格" }],
  gas: [{ value: "supply", label: "天然气供应量" }, { value: "consumption", label: "天然气消费量" }, { value: "storage", label: "天然气储量" }, { value: "pipeline_flow", label: "管道流量" }, { value: "pressure", label: "管网压力" }, { value: "price", label: "天然气价格" }],
  oil: [{ value: "production", label: "石油产量" }, { value: "refining", label: "石油炼化量" }, { value: "inventory", label: "石油库存" }, { value: "transport", label: "石油运输量" }, { value: "sales", label: "石油销售量" }, { value: "price", label: "石油价格" }],
};

const functionOptions = [
  { value: "", label: "请选择固定函数" },
  { value: "sum", label: "求和" },
  { value: "average", label: "平均值" },
  { value: "max", label: "最大值" },
  { value: "min", label: "最小值" },
  { value: "count", label: "计数" },
  { value: "median", label: "中位数" },
  { value: "growth_rate", label: "增长率" },
  { value: "yoy", label: "同比" },
  { value: "mom", label: "环比" },
  { value: "group_by", label: "分组汇总" },
  { value: "threshold", label: "阈值判断" },
  { value: "trend", label: "趋势" },
  { value: "psi", label: "PSI" },
  { value: "mpc_aggregation", label: "MPC 聚合" },
];

function resultEntries(value: ControlledQueryResult["result"]) {
  if (value && typeof value === "object") return Object.entries(value);
  return [["计算结果", value]];
}

function resourceLabel(domain: string | null | undefined, resource: string | null | undefined) {
  return resourceOptions[domain || ""]?.find((item) => item.value === resource)?.label || "待补充";
}

export function QueryPage() {
  const navigate = useNavigate();
  const { context } = useTrustedSpaceContext();
  const isRegulator = context?.actor.role_code === "REGULATOR";
  const [question, setQuestion] = useState("查询2026年8月煤炭库存平均值");
  const [intent, setIntent] = useState<QueryIntent | null>(null);
  const [authorizations, setAuthorizations] = useState<UsageRequest[]>([]);
  const [accessRules, setAccessRules] = useState<AccessRule[]>([]);
  const [authorizationId, setAuthorizationId] = useState("");
  const [providerOrgId, setProviderOrgId] = useState("");
  const [domain, setDomain] = useState("coal");
  const [resource, setResource] = useState("inventory");
  const [fixedFunction, setFixedFunction] = useState("average");
  const [startDate, setStartDate] = useState("2026-08-01");
  const [endDate, setEndDate] = useState("2026-08-23");
  const [region, setRegion] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ControlledQueryResult | null>(null);

  useEffect(() => {
    loadUsageRequests({ status: "APPROVED", mine: true, pageSize: 100 })
      .then((payload) => {
        setAuthorizations(payload.items);
        setAuthorizationId((current) => current || payload.items[0]?.request_id || "");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "授权记录加载失败"));
  }, []);

  useEffect(() => {
    if (!isRegulator) return;
    loadAccessRules()
      .then((payload) => setAccessRules(payload.items))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "主体规则加载失败"));
  }, [isRegulator]);

  const matchingAutoRules = useMemo(
    () => accessRules.filter((rule) => rule.mode === "AUTO_CALL" && rule.energy_domain === domain && rule.resource_id === resource && rule.function_code === fixedFunction),
    [accessRules, domain, resource, fixedFunction],
  );

  useEffect(() => {
    if (!isRegulator) return;
    setProviderOrgId((current) => matchingAutoRules.some((rule) => rule.owner_org_id === current) ? current : matchingAutoRules[0]?.owner_org_id || "");
  }, [isRegulator, matchingAutoRules]);

  const resources = useMemo(() => [
    { value: "", label: domain ? "请选择数据资源" : "请先选择能源种类" },
    ...(resourceOptions[domain] || []),
  ], [domain]);

  async function parseQuestion() {
    setBusy(true);
    setError("");
    setConfirmed(false);
    try {
      const parsed = await parseTrustedQuery(question);
      setIntent(parsed);
      if (parsed.energy_domain) {
        setDomain(parsed.energy_domain);
        const nextResources = resourceOptions[parsed.energy_domain] || [];
        setResource(parsed.resource && nextResources.some((item) => item.value === parsed.resource) ? parsed.resource : "");
      } else {
        setDomain("");
        setResource("");
      }
      setFixedFunction(parsed.function || "");
      setStartDate(parsed.start_date || "");
      setEndDate(parsed.end_date || "");
      setRegion(parsed.region || "");
      setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "查询意图解析失败");
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    const autoRule = matchingAutoRules.find((rule) => rule.owner_org_id === providerOrgId) || matchingAutoRules[0];
    if (!authorizationId && !autoRule) {
      setError(isRegulator ? "当前条件没有命中主体预先批准规则，请先发起企业授权申请" : "请先取得数据提供企业的批准授权");
      return;
    }
    if (!confirmed) {
      setError("请先勾选已核对查询条件，再创建计算任务");
      return;
    }
    if (!domain || !resource || !fixedFunction || !startDate || !endDate) {
      setError("能源种类、数据资源、固定函数和时间范围都必须填写");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const query = {
        authorization_id: authorizationId || undefined,
        provider_org_id: authorizationId ? undefined : autoRule?.owner_org_id,
        energy_domain: domain,
        resource,
        function: fixedFunction,
        start_date: startDate,
        end_date: endDate,
        region: region || undefined,
        decimals: 2,
      };
      const confirmation = await confirmTrustedQuery(query);
      setResult(await executeTrustedQuery({ ...query, confirmation_token: confirmation.confirmation_token }));
      setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "计算任务执行失败");
    } finally {
      setBusy(false);
    }
  }

  return <PageFrame title="智能数据查询" description={isRegulator ? "Agent 只负责拆解需求；能源局确认后，系统按主体规则或企业审批执行，原始数据不会离开主体节点。" : "DeepSeek 只把人话翻译成固定查询条件；授权核验、计算和图表数据都来自后端确定性链路。"}>
    <div className="trusted-query-layout">
      <div className="trusted-query-main">
        <Card className="trusted-query-question">
          <CardHeader><SurfaceHeader title="描述查询需求" description="不会把自然语言直接变成任意代码或任意数据库语句" /></CardHeader>
          <CardContent>
            <FieldLabel htmlFor="trusted-question">查询内容</FieldLabel>
            <Textarea id="trusted-question" value={question} onChange={(event) => { setQuestion(event.target.value); setIntent(null); setConfirmed(false); }} placeholder="例如：查询2026年8月煤炭库存平均值" />
            <div className="trusted-query-actions"><Button variant="primary" busy={busy} onClick={parseQuestion}><Search size={15} />翻译查询</Button><span>DeepSeek 不读取数据，只返回固定字段；不可用时可手动选择。</span></div>
            {intent && <div className={`trusted-intent-summary ${intent.provider === "manual_rules" ? "is-manual" : ""}`}><CheckCircle2 size={16} /><span>{intent.notice}</span><Badge tone={intent.ready ? "success" : "warning"}>{intent.ready ? (intent.provider === "manual_rules" ? "手动预览" : "待确认") : "需要补充"}</Badge></div>}
            {intent && <div className="trusted-query-preview" aria-label="翻译预览">
              <div><span>能源种类</span><strong>{intent.energy_domain_name || "待补充"}</strong></div>
              <div><span>数据资源</span><strong>{resourceLabel(intent.energy_domain, intent.resource)}</strong></div>
              <div><span>固定函数</span><strong>{intent.function_name}</strong></div>
              <div><span>开始日期</span><strong>{intent.start_date || "待补充"}</strong></div>
              <div><span>结束日期</span><strong>{intent.end_date || "待补充"}</strong></div>
              <div><span>地区</span><strong>{intent.region || "全部已授权地区"}</strong></div>
            </div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><SurfaceHeader title="确认固定计算条件" description="企业授权范围与连接器隐私下限会在执行前再次核验" /></CardHeader>
          <CardContent className="trusted-query-form">
            <div><FieldLabel>能源种类</FieldLabel><Select value={domain} onChange={(event) => { const next = event.target.value; setDomain(next); setResource(""); setConfirmed(false); }} options={domainOptions} /></div>
            <div><FieldLabel>数据资源</FieldLabel><Select value={resource} onChange={(event) => { setResource(event.target.value); setConfirmed(false); }} options={resources} /></div>
            <div><FieldLabel>固定函数</FieldLabel><Select value={fixedFunction} onChange={(event) => { setFixedFunction(event.target.value); setConfirmed(false); }} options={functionOptions} /></div>
            <div className="trusted-query-wide"><FieldLabel>{isRegulator ? "主体规则 / 企业授权" : "企业授权"}</FieldLabel>{isRegulator && !authorizationId ? <Select value={providerOrgId} onChange={(event) => { setProviderOrgId(event.target.value); setConfirmed(false); }} options={matchingAutoRules.length ? matchingAutoRules.map((rule) => ({ value: rule.owner_org_id, label: `${rule.owner_org_id} · ${rule.version} · 可自动调用` })) : [{ value: "", label: "当前条件未命中自动规则" }]} /> : <Select value={authorizationId} onChange={(event) => { setAuthorizationId(event.target.value); setConfirmed(false); }} options={authorizations.length ? authorizations.map((item) => ({ value: item.request_id, label: `${item.asset.asset_name || "未命名数据资源"}，由${item.provider.org_name}批准` })) : [{ value: "", label: "暂无已批准授权" }]} />}</div>
            <div><FieldLabel htmlFor="query-start">开始日期</FieldLabel><Input id="query-start" type="date" value={startDate} onChange={(event) => { setStartDate(event.target.value); setConfirmed(false); }} /></div>
            <div><FieldLabel htmlFor="query-end">结束日期</FieldLabel><Input id="query-end" type="date" value={endDate} onChange={(event) => { setEndDate(event.target.value); setConfirmed(false); }} /></div>
            <div><FieldLabel htmlFor="query-region" hint="可不填">地区</FieldLabel><Input id="query-region" value={region} onChange={(event) => { setRegion(event.target.value); setConfirmed(false); }} placeholder="全部已授权地区" /></div>
            <div className="trusted-query-wide trusted-confirmation-row"><label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={busy} /><span>我已核对能源种类、数据资源、固定函数、时间范围和地区，确认按这些条件创建任务。</span></label></div>
            <div className="trusted-query-wide trusted-execute-row"><div><ShieldCheck size={17} /><span>{isRegulator && !authorizationId && matchingAutoRules.length ? "已命中主体批准规则；只返回规则允许的聚合结果。" : "原始数据不会进入平台，平台只接收企业连接器签名后的受控结果。"}</span></div><Button variant="primary" busy={busy} disabled={!confirmed} onClick={execute}><Calculator size={15} />确认并创建任务</Button></div>
          </CardContent>
        </Card>
      </div>

      <aside className="trusted-query-side">
        <Card>
          <CardHeader><SurfaceHeader title="授权前置条件" /></CardHeader>
          <CardContent className="trusted-query-rule-list">
            <div><FileSignature size={16} /><span><strong>{isRegulator ? "规则或申请" : "必须先申请"}</strong><small>{isRegulator ? "命中主体预设规则可直接调用，否则需要企业批准" : "数据提供企业批准后才能计算"}</small></span></div>
            <div><ShieldCheck size={16} /><span><strong>范围不能扩大</strong><small>字段、期间、粒度、用途和次数均受授权约束</small></span></div>
            <div><Calculator size={16} /><span><strong>只运行固定函数</strong><small>不执行任意代码、任意 SQL 或 AI 脚本</small></span></div>
          </CardContent>
        </Card>
        {!authorizations.length && (!isRegulator || !matchingAutoRules.length) && <div className="trusted-query-empty-auth"><strong>{isRegulator ? "当前没有可直接调用的主体规则" : "当前没有已批准授权"}</strong><p>请先在数据目录选择资源，向提供企业提交授权申请。</p><Button variant="secondary" onClick={() => navigate("/trusted-space/catalog")}>前往数据目录</Button></div>}
      </aside>
    </div>

    {error && <div className="trusted-query-error" role="alert"><strong>任务未执行</strong><span>{error}</span></div>}
    {result && <Card className="trusted-query-result">
      <CardHeader><SurfaceHeader title={`${result.resource_name}计算结果`} description={`${result.function_name}，数据可用不可见`} action={<Badge tone="success" dot>数字签名已验证</Badge>} /></CardHeader>
      <CardContent>
        <div className="trusted-result-values">{resultEntries(result.result).map(([label, value]) => <div key={label}><span>{label}</span><strong>{String(value)}</strong><small>{result.unit}</small></div>)}</div>
        <QueryResultChart result={result} />
        <div className="trusted-result-provenance"><span>任务编号：{result.task_id}</span><span>生成时间：{new Date(result.generated_at).toLocaleString("zh-CN")}</span><span>授权范围：已核验</span><span>审计记录：已写入</span></div>
      </CardContent>
    </Card>}
  </PageFrame>;
}
