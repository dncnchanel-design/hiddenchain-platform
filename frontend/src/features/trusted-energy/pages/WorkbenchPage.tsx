import { ArrowUpRight, Database, FileCheck2, FilePlus2, Fingerprint, Network, Plus, ScanSearch, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { demoAssets, demoTasks, identityProfile, routeForView } from "../types";
import { Badge, Button, Card, CardContent, CardHeader, MetricBand, Progress, StatusBadge, SurfaceHeader, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";

const quickActions = [
  { label: "发布数据资产", detail: "登记元数据与授权规则", icon: Database, path: "/data/upload" },
  { label: "申请数据使用", detail: "从目录选择受控用途", icon: FilePlus2, path: routeForView("catalog") },
  { label: "查看计算任务", detail: "追踪状态机与日志", icon: Network, path: routeForView("ttc") },
  { label: "核验审计链", detail: "复核凭证与来源", icon: ScanSearch, path: routeForView("audit") },
];

export function WorkbenchPage() {
  const navigate = useNavigate();
  return <PageFrame title="工作台" description="按主体、数据授权、受控计算和证据留痕组织当前工作。" action={<Button variant="primary" onClick={() => navigate(routeForView("catalog"))}><Plus size={15} />申请数据使用</Button>}>
    <section className="trusted-subject-strip"><div className="trusted-subject-identity"><span className="trusted-subject-avatar"><ShieldCheck size={18} /></span><div><strong>您好，东部绿能企业</strong><span>数据提供方 · 当前工作主体</span></div></div><div className="trusted-subject-facts"><span><small>主体 DID</small><code>{identityProfile.did}</code></span><span><small>权限范围</small><b>数据资产 · 受控计算</b></span><span><small>运行边界</small><Badge tone="warning" dot>本地演示数据</Badge></span></div></section>
    <MetricBand items={[{ label: "我的数据资产", value: "36", detail: "+4 本月登记", tone: "brand" }, { label: "使用申请", value: "8", detail: "2 待确认", tone: "info" }, { label: "计算任务", value: "4", detail: "1 运行中", tone: "warning" }, { label: "审计报告", value: "12", detail: "全部可追溯", tone: "success" }]} />
    <div className="trusted-workbench-grid">
      <Card className="trusted-table-surface"><CardHeader><SurfaceHeader title="最近数据资产" description="按最近更新时间排序 · 仅展示当前主体可见范围" action={<Button variant="link" size="sm" onClick={() => navigate(routeForView("catalog"))}>查看全部 <ArrowUpRight size={14} /></Button>} /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>资产名称</TableHead><TableHead>版本</TableHead><TableHead>敏感等级</TableHead><TableHead>质量评分</TableHead><TableHead>更新时间</TableHead></TableRow></TableHeader><TableBody>{demoAssets.slice(0, 4).map((asset) => <TableRow key={asset.id} onClick={() => navigate(routeForView("asset", asset.id))}><TableCell><div className="trusted-table-primary"><strong>{asset.name}</strong><small>{asset.type} · {asset.domain}</small></div></TableCell><TableCell><code>{asset.version}</code></TableCell><TableCell><Badge tone={asset.sensitivity === "L4" ? "danger" : asset.sensitivity === "L3" ? "warning" : "neutral"}>{asset.sensitivity}</Badge></TableCell><TableCell><span className="trusted-number">{asset.quality.toFixed(1)}</span></TableCell><TableCell className="trusted-muted">{asset.updatedAt}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card>
      <Card className="trusted-task-surface"><CardHeader><SurfaceHeader title="近期任务动态" description="状态变化与责任主体" action={<Button variant="link" size="sm" onClick={() => navigate(routeForView("ttc"))}>查看全部 <ArrowUpRight size={14} /></Button>} /></CardHeader><CardContent><div className="trusted-task-list">{demoTasks.map((task) => <button className="trusted-task-row" key={task.id} type="button" onClick={() => navigate(routeForView("ttc", task.id.toLowerCase()))}><span className="trusted-task-icon"><Network size={15} /></span><span className="trusted-task-copy"><strong>{task.title}</strong><small><code>{task.id}</code> · {task.updatedAt}</small></span><span className="trusted-task-state"><StatusBadge value={task.status} /><Progress value={task.progress} /></span></button>)}</div></CardContent></Card>
    </div>
    <div className="trusted-lower-grid"><Card><CardHeader><SurfaceHeader title="快捷入口" description="常用动作会保留在当前本地会话" /></CardHeader><CardContent><div className="trusted-quick-grid">{quickActions.map(({ label, detail, icon: Icon, path }) => <button type="button" className="trusted-quick-action" key={label} onClick={() => navigate(path)}><span><Icon size={16} /></span><b>{label}</b><small>{detail}</small><ArrowUpRight size={13} /></button>)}</div></CardContent></Card><Card><CardHeader><SurfaceHeader title="可信执行边界" description="当前环境能力清单" /></CardHeader><CardContent><div className="trusted-boundary-list"><div><span><ShieldCheck size={14} />受控执行</span><Badge tone="success" dot>LOCAL_REAL</Badge></div><div><span><Fingerprint size={14} />身份凭证</span><Badge tone="success" dot>已绑定</Badge></div><div><span><FileCheck2 size={14} />链上存证</span><Badge tone="warning" dot>DEMO</Badge></div></div></CardContent></Card></div>
  </PageFrame>;
}
