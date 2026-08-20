import { Check, FileSignature, LockKeyhole, MessageSquareText, Paperclip, ShieldCheck } from "lucide-react";
import { demoAssets } from "../types";
import { Badge, Button, Card, CardContent, CardHeader, Divider, StatusBadge, SurfaceHeader, Timeline } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";

const negotiationEvents = [
  { id: "request", label: "数据申请", detail: "提供方已收到用途申请", time: "2026-05-18 09:10", state: "done" as const },
  { id: "catalog", label: "Catalog Review", detail: "目录规则与敏感等级复核", time: "2026-05-18 09:11", state: "done" as const },
  { id: "offer", label: "Contract Offer", detail: "提供方提出受控计算条件", time: "2026-05-18 09:12", state: "done" as const },
  { id: "negotiation", label: "Contract Negotiation", detail: "等待申请方确认保留期限", time: "2026-05-18 09:18", state: "current" as const },
  { id: "agreement", label: "Agreement", detail: "合同签署后进入任务创建", time: "待执行", state: "pending" as const },
];

export function ContractPage() {
  return <PageFrame title="合同协商" description="围绕用途、处理方式、结果范围和存证口径保留完整协商轨迹。" action={<Button variant="primary"><MessageSquareText size={14} />回复协商</Button>}>
    <Card className="trusted-contract-meta"><CardContent><div><small>协商资产</small><strong>{demoAssets[0].name} <Badge tone="brand">{demoAssets[0].id}</Badge></strong></div><div><small>提供方</small><strong>东部绿能企业</strong><code>did:energy:generator001</code></div><div><small>申请方</small><strong>东部电力交易中心</strong><code>did:energy:trading001</code></div><div><small>协商状态</small><StatusBadge value="进行中" /></div></CardContent></Card>
    <div className="trusted-contract-grid"><Card><CardHeader><SurfaceHeader title="协商时间轴" description="节点状态与时间戳由本地协商样例提供" action={<LockKeyhole size={16} />} /></CardHeader><CardContent><Timeline events={negotiationEvents} /></CardContent></Card><Card><CardHeader><SurfaceHeader title="合同基本信息" description="当前合同草案尚未签署" action={<FileSignature size={16} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>Contract ID</dt><dd><code>CON-202605-001</code></dd></div><div><dt>Negotiation ID</dt><dd><code>NEG-202605-001</code></dd></div><div><dt>用途</dt><dd>结算分析 / 聚合结果</dd></div><div><dt>结果范围</dt><dd>100.00 MWh、320.00 元/MWh</dd></div><div><dt>数据保留</dt><dd>结果 30 日</dd></div><div><dt>合同状态</dt><dd><Badge tone="warning" dot>待申请方确认</Badge></dd></div></dl><Divider /><div className="trusted-contract-attachments"><div><Paperclip size={14} /><span>受控计算使用规则 v1.0</span><Button variant="link" size="sm">查看</Button></div><div><ShieldCheck size={14} /><span>数据质量摘要 2026-05-18</span><Button variant="link" size="sm">查看</Button></div></div></CardContent></Card></div>
    <Card><CardHeader><SurfaceHeader title="对方提出的条件" description="确认后会写入协商结果，不会自动执行任务" /></CardHeader><CardContent><div className="trusted-contract-conditions"><div><span><Check size={14} />用途范围</span><strong>仅限 5 月新能源出力结算分析</strong></div><div><span><Check size={14} />计算方式</span><strong>聚合结果，不返回单场站明细</strong></div><div><span><Check size={14} />存证方式</span><strong>本地摘要留痕；FISCO BCOS 标记为 DEMO</strong></div></div></CardContent></Card>
  </PageFrame>;
}
