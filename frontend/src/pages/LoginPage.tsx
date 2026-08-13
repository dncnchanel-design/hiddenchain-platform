import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Blocks, Bot, Eye, EyeOff, Home, Info, KeyRound, LockKeyhole, Megaphone, Network, PhoneCall, ShieldCheck, Zap } from "lucide-react";
import { useAuth } from "../auth";
import { Button, Notice } from "../components/ui";

const accounts = [
  { label: "交易中心", username: "exchange", password: "exchange123" },
  { label: "发电企业", username: "generator", password: "generator123" },
  { label: "售电企业", username: "retailer", password: "retailer123" },
  { label: "监管方", username: "regulator", password: "regulator123" },
  { label: "系统管理员", username: "admin", password: "admin123" },
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("exchange");
  const [password, setPassword] = useState("exchange123");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      navigate("/overview", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "认证失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <header className="login-portal-head">
        <div className="login-portal-head-inner">
          <div className="login-portal-brand"><div className="login-portal-brand-mark"><ShieldCheck size={27} /></div><div><strong>隐链明算</strong><span>可信电力交易空间</span></div></div>
          <div className="login-portal-utility"><a href="#about"><Home size={14} />平台首页</a><a href="#notice"><Megaphone size={14} />通知公告</a><a href="#guide"><Info size={14} />使用指南</a><a href="#support"><PhoneCall size={14} />业务支持</a><span>2026年08月</span></div>
        </div>
      </header>
      <nav className="login-portal-nav" aria-label="登录门户导航"><span className="active">首页</span><span>可信业务</span><span>数字化能力</span><span>安全监管</span><span>信息公开</span></nav>
      <div className="login-body">
        <section className="login-identity">
          <div className="login-product">
            <div className="eyebrow">AGENT-NATIVE TRUSTED DATA SPACE</div>
            <h1>能源四场景可信协同平台</h1>
            <p>贯通新能源消纳、市场交易、虚拟电厂响应与电网调度，在原始数据不出域前提下完成自动结算。</p>
          </div>
          <div className="login-chain" aria-label="核心可信链路">
            <div><KeyRound size={19} /><span>DID 身份链</span><small>主体与 Agent 可验</small></div>
            <i />
            <div><Network size={19} /><span>隐私计算链</span><small>自适应策略路由</small></div>
            <i />
            <div><Blocks size={19} /><span>区块链存证链</span><small>全过程可核验</small></div>
            <i />
            <div><Bot size={19} /><span>智能体协作链</span><small>调用可追责</small></div>
          </div>
          <div className="login-foot"><Zap size={15} />面向能源可信数据空间的多方安全协同</div>
        </section>
        <section className="login-form-area">
          <form className="login-form" onSubmit={submit}>
            <div className="login-form-heading">
              <LockKeyhole size={22} />
              <div><h2>主体身份认证</h2><p>选择主体后进入对应权限工作台</p></div>
            </div>
            <label className="field">
              <span>登录账号</span>
              <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required minLength={3} maxLength={64} />
            </label>
            <label className="field">
              <span>访问凭证</span>
              <div className="password-field">
                <input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required minLength={6} maxLength={128} />
                <button type="button" onClick={() => setShowPassword((value) => !value)} title={showPassword ? "隐藏凭证" : "显示凭证"}>
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>
            {error && <Notice tone="warning">{error}</Notice>}
            <Button type="submit" variant="primary" busy={busy}>通过 DID 网关登录</Button>
            <div className="demo-accounts">
              <span>演示主体</span>
              <div>
                {accounts.map((account) => (
                  <button
                    type="button"
                    key={account.username}
                    className={username === account.username ? "selected" : ""}
                    onClick={() => { setUsername(account.username); setPassword(account.password); }}
                  >{account.label}</button>
                ))}
              </div>
            </div>
            <div className="login-security"><ShieldCheck size={15} />本地 MVP 环境 · 凭证经 PBKDF2 哈希验证 · 会话采用 JWT</div>
          </form>
        </section>
      </div>
    </div>
  );
}
