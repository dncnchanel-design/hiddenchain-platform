import { useState } from "react";
import { Bot, Check, ClipboardList, CornerDownLeft, Database, FileSearch, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle, IconButton, Input, Button, Badge } from "./ui-primitives";

const planItems = ["读取新能源出力数据资产", "校验数据授权与质量评分", "生成本地受控 MPC 计算草案", "预览结果摘要并等待人工确认"];

export function AgentSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [message, setMessage] = useState("");
  const [submitted, setSubmitted] = useState(false);

  function submit() {
    if (!message.trim()) return;
    setSubmitted(true);
    setMessage("");
  }

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="energy-agent-sheet">
      <div className="energy-agent-heading"><div className="energy-agent-title"><span className="energy-agent-icon"><Bot size={17} /></span><div><DialogTitle>隐链智能助手</DialogTitle><DialogDescription>仅操作本地界面，不代表真实执行</DialogDescription></div></div><IconButton label="关闭 Agent 助手" onClick={() => onOpenChange(false)}><X size={16} /></IconButton></div>
      <div className="energy-agent-body">
        <div className="energy-agent-message energy-agent-message-bot"><span className="energy-agent-avatar"><Bot size={14} /></span><div><p>我可以帮助你定位资产、解释任务状态，或生成一份可供人工确认的操作草案。</p><small>当前主体：<code>did:energy:generator001</code></small></div></div>
        {submitted && <div className="energy-agent-message energy-agent-message-user"><span>已记录本地指令：正在等待人工确认</span></div>}
        <section className="energy-agent-plan"><div className="energy-agent-section-heading"><div><span className="energy-section-kicker">LOCAL PLAN</span><h3>建议执行计划</h3></div><Badge tone="warning" dot>演示计划</Badge></div><ol>{planItems.map((item, index) => <li key={item}><span className={index < 2 ? "energy-plan-done" : ""}>{index < 2 ? <Check size={13} /> : index + 1}</span><span>{item}</span></li>)}</ol><div className="energy-agent-plan-note"><ShieldCheck size={14} /><span>MPC 能力：<code>LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST</code></span></div></section>
        <section className="energy-agent-shortcuts"><h3>常用指令</h3><div>{[[FileSearch, "查找资产"], [ClipboardList, "查看任务"], [Database, "检查数据质量"], [Sparkles, "解释当前状态"]].map(([Icon, label]) => <button type="button" key={label as string} onClick={() => setMessage(label as string)}><Icon size={14} />{label as string}</button>)}</div></section>
      </div>
      <div className="energy-agent-composer"><Input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") submit(); }} placeholder="输入本地查询或需求…" aria-label="输入 Agent 指令" /><Button variant="primary" size="icon" onClick={submit} aria-label="发送"><Send size={15} /></Button></div>
      <footer className="energy-agent-footer"><span><span className="energy-status-dot" />受控环境</span><span>结果需人工确认</span><CornerDownLeft size={13} /></footer>
    </DialogContent>
  </Dialog>;
}
