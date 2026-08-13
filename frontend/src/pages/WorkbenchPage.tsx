import { ArrowRight, Blocks, Bot, Calculator, ClipboardCheck, Database, FileCheck2, Gavel, Network, ShieldCheck, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { DataTable, ErrorState, LoadingState, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord, RoleCode } from "../types";

const roleConfig: Record<RoleCode, { title: string; focus: string; steps: Array<[string, string, React.ElementType]>; links: Array<[string, string, React.ElementType]> }> = {
  GENERATOR: {
    title: "发电企业工作台",
    focus: "把预测与计量登记为可调用数据产品，在用途授权后参与隐私计算",
    steps: [["登记数据产品", "原始记录留在本域", Database], ["签署调用许可", "限定用途与输出范围", ShieldCheck], ["确认计算结果", "仅查看授权结果", FileCheck2]],
    links: [["发电侧数据", "/data/generation", Database], ["结算结果", "/results", FileCheck2], ["存证核验", "/evidence", Blocks]],
  },
  RETAILER: {
    title: "售电企业工作台",
    focus: "授权用户负荷和虚拟电厂数据，在不暴露单户明细的前提下完成联合分析",
    steps: [["登记数据产品", "形成 DataRef 与承诺", Database], ["发起隐私计算", "单户负荷不可见", Network], ["确认聚合结果", "DID 签名确认", FileCheck2]],
    links: [["售电与用电数据", "/data/retail", Database], ["隐私计算", "/compute", Network], ["结算结果", "/results", FileCheck2]],
  },
  EXCHANGE: {
    title: "交易中心工作台",
    focus: "编排数据调用、用途控制和隐私计算，电力交易作为可运行验证场景",
    steps: [["固化用途与边界", "人工闸门后生成哈希", Gavel], ["组织数据协同", "六 Agent 受控执行", Bot], ["验证计算与回执", "多方签名并存证", Blocks]],
    links: [["规则与合约", "/rules", Gavel], ["能源场景验证", "/settlements", Calculator], ["Agent 协同", "/agents", Bot]],
  },
  REGULATOR: {
    title: "监管方工作台",
    focus: "四链证据图谱核验、调度闸门追溯、异常处置与报告输出",
    steps: [["核验身份与授权", "追溯 DID/VC 与策略", Users], ["核验四场景证据", "重算哈希并检查安全闸门", Blocks], ["处置异常并归档", "形成责任可追结论", ClipboardCheck]],
    links: [["监管审计", "/audit", ClipboardCheck], ["异常处置", "/anomalies", ShieldCheck], ["可信报告", "/reports", FileCheck2]],
  },
  ADMIN: {
    title: "系统管理员工作台",
    focus: "主体、DID、Agent 凭证与适配器运行状态维护",
    steps: [["维护主体身份", "校验 DID/VC 状态", Users], ["监控可信适配器", "检测服务可用性", Network], ["审查平台日志", "不介入业务裁决", ClipboardCheck]],
    links: [["主体与 DID", "/system", Users], ["运行指标", "/metrics", Network], ["全过程日志", "/logs", ClipboardCheck]],
  },
};

export function WorkbenchPage() {
  const { session } = useAuth();
  const role = session!.user.role_code;
  const config = roleConfig[role];
  const { data, loading, error, reload } = useRemote<JsonRecord[]>(() => api("/settlement/tasks"), []);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "工作台加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="角色权限视图" title={config.title} description={config.focus} />
      <Surface title="本角色可信业务链">
        <div className="role-steps">
          {config.steps.map(([title, note, Icon], index) => (
            <div key={title}><span>{index + 1}</span><Icon size={22} /><strong>{title}</strong><small>{note}</small>{index < config.steps.length - 1 && <ArrowRight className="step-arrow" size={18} />}</div>
          ))}
        </div>
      </Surface>
      <div className="quick-links">
        {config.links.map(([title, path, Icon]) => (
          <Link to={path} key={path}><Icon size={20} /><span>{title}</span><ArrowRight size={16} /></Link>
        ))}
      </div>
      <Surface title="可访问的场景验证任务" note="电力交易仅作为验证数据调用与隐私计算闭环的业务场景，字段范围已按当前主体自动裁剪">
        <DataTable
          keyField="task_id"
          rows={data}
          columns={[
            { key: "capsule_id", label: "可信验证胶囊", render: (row) => <span className="mono-text">{row.capsule_id}</span> },
            { key: "task_name", label: "任务" },
            { key: "trade_batch_no", label: "批次" },
            { key: "current_stage", label: "阶段" },
            { key: "risk_level", label: "风险", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
          ]}
        />
      </Surface>
    </>
  );
}
