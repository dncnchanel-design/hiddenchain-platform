import { Cable, CheckCircle2, Database, FileSpreadsheet, KeyRound, ServerCog, ShieldCheck } from "lucide-react";
import { DOMAIN_LABELS } from "../../../types";
import { PageFrame } from "../components/PageFrame";
import { Badge, Card, CardContent, CardHeader, SurfaceHeader } from "../components/ui-primitives";
import { useTrustedSpaceContext } from "../trusted-space-context";

const sourceTypes = ["Excel", "CSV", "PostgreSQL", "MySQL", "SQL Server", "SQLite"];
const fixedFunctions = ["求和", "平均值", "最大值", "最小值", "计数", "中位数", "增长率", "同比", "环比", "分组汇总", "阈值判断", "趋势", "PSI", "MPC 聚合份额"];

export function ConnectorPage() {
  const { context } = useTrustedSpaceContext();
  const domain = context?.current_subject.energy_domain || "";
  const domainLabel = DOMAIN_LABELS[domain] || "未配置能源范围";
  const configured = context?.capabilities.data_space_connector?.readiness === "CONFIGURED";

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

    <div className="trusted-connector-note"><ShieldCheck size={16} /><div><strong>公开环境是演示部署</strong><p>正式交付后，每家企业在自己的内网部署连接器与私钥，平台只负责目录协调、授权流转、任务编排和审计追溯。</p></div></div>
  </PageFrame>;
}
