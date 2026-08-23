import { useEffect, useMemo, useState } from "react";
import { Calculator, CheckCircle2, FileSignature, Search, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PageFrame } from "../components/PageFrame";
import { QueryResultChart } from "../components/QueryResultChart";
import { Badge, Button, Card, CardContent, CardHeader, FieldLabel, Input, Select, SurfaceHeader, Textarea } from "../components/ui-primitives";
import { executeTrustedQuery, loadUsageRequests, parseTrustedQuery, type ControlledQueryResult, type QueryIntent, type UsageRequest } from "../trusted-space-api";

const domainOptions = [
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

export function QueryPage() {
  const navigate = useNavigate();
  const [question, setQuestion] = useState("查询2026年8月煤炭库存平均值");
  const [intent, setIntent] = useState<QueryIntent | null>(null);
  const [authorizations, setAuthorizations] = useState<UsageRequest[]>([]);
  const [authorizationId, setAuthorizationId] = useState("");
  const [domain, setDomain] = useState("coal");
  const [resource, setResource] = useState("inventory");
  const [fixedFunction, setFixedFunction] = useState("average");
  const [startDate, setStartDate] = useState("2026-08-01");
  const [endDate, setEndDate] = useState("2026-08-23");
  const [region, setRegion] = useState("");
  const [busy, setBusy] = useState(false);
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

  const resources = useMemo(() => resourceOptions[domain] || [], [domain]);

  async function parseQuestion() {
    setBusy(true);
    setError("");
    try {
      const parsed = await parseTrustedQuery(question);
      setIntent(parsed);
      if (parsed.energy_domain) {
        setDomain(parsed.energy_domain);
        const nextResources = resourceOptions[parsed.energy_domain] || [];
        setResource(parsed.resource && nextResources.some((item) => item.value === parsed.resource) ? parsed.resource : nextResources[0]?.value || "");
      }
      if (parsed.function) setFixedFunction(parsed.function);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "查询意图解析失败");
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    if (!authorizationId) {
      setError("请先取得数据提供企业的批准授权");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await executeTrustedQuery({
        authorization_id: authorizationId,
        energy_domain: domain,
        resource,
        function: fixedFunction,
        start_date: startDate,
        end_date: endDate,
        region: region || undefined,
        decimals: 2,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "计算任务执行失败");
    } finally {
      setBusy(false);
    }
  }

  return <PageFrame title="智能数据查询" description="用中文描述需求，系统只负责解析意图；授权核验和正式计算由固定规则完成。">
    <div className="trusted-query-layout">
      <div className="trusted-query-main">
        <Card className="trusted-query-question">
          <CardHeader><SurfaceHeader title="描述查询需求" description="不会把自然语言直接变成任意代码或任意数据库语句" /></CardHeader>
          <CardContent>
            <FieldLabel htmlFor="trusted-question">查询内容</FieldLabel>
            <Textarea id="trusted-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：查询2026年8月煤炭库存平均值" />
            <div className="trusted-query-actions"><Button variant="primary" busy={busy} onClick={parseQuestion}><Search size={15} />解析查询</Button><span>行业缩写可直接使用 DID、CSV、API、PSI、MPC</span></div>
            {intent && <div className="trusted-intent-summary"><CheckCircle2 size={16} /><span>{intent.notice}</span><Badge tone={intent.ready ? "success" : "warning"}>{intent.ready ? "已识别" : "需要补充"}</Badge></div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><SurfaceHeader title="确认固定计算条件" description="企业授权范围与连接器隐私下限会在执行前再次核验" /></CardHeader>
          <CardContent className="trusted-query-form">
            <div><FieldLabel>能源种类</FieldLabel><Select value={domain} onChange={(event) => { const next = event.target.value; setDomain(next); setResource(resourceOptions[next]?.[0]?.value || ""); }} options={domainOptions} /></div>
            <div><FieldLabel>数据资源</FieldLabel><Select value={resource} onChange={(event) => setResource(event.target.value)} options={resources} /></div>
            <div><FieldLabel>固定函数</FieldLabel><Select value={fixedFunction} onChange={(event) => setFixedFunction(event.target.value)} options={functionOptions} /></div>
            <div className="trusted-query-wide"><FieldLabel>企业授权</FieldLabel><Select value={authorizationId} onChange={(event) => setAuthorizationId(event.target.value)} options={authorizations.length ? authorizations.map((item) => ({ value: item.request_id, label: `${item.asset.asset_name || "未命名数据资源"}，由${item.provider.org_name}批准` })) : [{ value: "", label: "暂无已批准授权" }]} /></div>
            <div><FieldLabel htmlFor="query-start">开始日期</FieldLabel><Input id="query-start" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></div>
            <div><FieldLabel htmlFor="query-end">结束日期</FieldLabel><Input id="query-end" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></div>
            <div><FieldLabel htmlFor="query-region" hint="可不填">地区</FieldLabel><Input id="query-region" value={region} onChange={(event) => setRegion(event.target.value)} placeholder="全部已授权地区" /></div>
            <div className="trusted-query-wide trusted-execute-row"><div><ShieldCheck size={17} /><span>原始数据不会进入平台，平台只接收企业连接器签名后的受控结果。</span></div><Button variant="primary" busy={busy} onClick={execute}><Calculator size={15} />创建计算任务</Button></div>
          </CardContent>
        </Card>
      </div>

      <aside className="trusted-query-side">
        <Card>
          <CardHeader><SurfaceHeader title="授权前置条件" /></CardHeader>
          <CardContent className="trusted-query-rule-list">
            <div><FileSignature size={16} /><span><strong>必须先申请</strong><small>数据提供企业批准后才能计算</small></span></div>
            <div><ShieldCheck size={16} /><span><strong>范围不能扩大</strong><small>字段、期间、粒度、用途和次数均受授权约束</small></span></div>
            <div><Calculator size={16} /><span><strong>只运行固定函数</strong><small>不执行任意代码、任意 SQL 或 AI 脚本</small></span></div>
          </CardContent>
        </Card>
        {!authorizations.length && <div className="trusted-query-empty-auth"><strong>当前没有已批准授权</strong><p>请先在数据目录选择资源，向提供企业提交授权申请。</p><Button variant="secondary" onClick={() => navigate("/trusted-space/catalog")}>前往数据目录</Button></div>}
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
