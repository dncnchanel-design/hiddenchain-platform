import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Eye, EyeOff, Info, LockKeyhole, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getDefaultPath } from "../access";
import { useAuth } from "../auth";
import { BrandMark, productFooterItems, useProductConfig } from "../branding";
import { Button, Notice } from "../components/ui";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [capsLock, setCapsLock] = useState(false);
  const [mode, setMode] = useState<"account" | "did">("account");
  const [did, setDid] = useState("");
  const [credential, setCredential] = useState("");
  const product = useProductConfig();
  const version = import.meta.env.VITE_APP_VERSION || "0.2.0";
  const footerItems = productFooterItems(product, version);

  function detectCapsLock(event: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(event.getModifierState("CapsLock"));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "did") {
      setError("去中心化身份认证尚未配置生产凭证，本次不会伪造登录结果。请切换账号密码登录，或由企业最高权限账号接入身份服务方。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const session = await login(username, password);
      navigate(getDefaultPath(session), { replace: true });
    } catch {
      setError("登录失败，请核对账号和密码后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen trusted-login-screen">
      <header className="login-brandbar">
        <div className="login-brand">
          <span className="login-product-mark"><BrandMark size={21} /></span>
          <span><strong>{product.productName}</strong><small>{product.productSubtitle}</small></span>
        </div>
        <div className="login-runtime">{product.environmentName && <span className="environment-tag">{product.environmentName}</span>}<span>版本 {version}</span></div>
      </header>

      <main className="login-main">
        <form className="login-form trusted-login-form" onSubmit={submit}>
          <div className="login-form-heading">
            <span className="login-form-icon" aria-hidden="true"><LockKeyhole size={20} /></span>
            <div><h1>登录系统</h1><p>使用已授权账号进入工作空间</p></div>
          </div>

          <div className="trusted-login-tabs" role="tablist" aria-label="登录方式">
            <button type="button" role="tab" aria-selected={mode === "account"} className={mode === "account" ? "is-active" : ""} onClick={() => { setMode("account"); setError(""); }}>账号密码登录</button>
            <button type="button" role="tab" aria-selected={mode === "did"} className={mode === "did" ? "is-active" : ""} onClick={() => { setMode("did"); setError(""); }}>DID 身份认证</button>
          </div>

          {mode === "account" ? <>
          {product.demoAccounts.length > 0 && <label className="field trusted-demo-account"><span>演示身份</span><select defaultValue="" onChange={(event) => { if (!event.target.value) return; const account = product.demoAccounts[Number(event.target.value)]; if (account) { setUsername(account.username); setPassword(account.password); } }}><option value="">请选择企业或机构</option>{product.demoAccounts.map((account, index) => <option key={account.label} value={index}>{account.label}</option>)}</select></label>}
          <label className="field">
            <span>账号</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" placeholder="请输入账号" required minLength={3} maxLength={64} autoFocus />
          </label>
          <label className="field">
            <span>密码</span>
            <div className="password-field">
              <input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} onKeyDown={detectCapsLock} onKeyUp={detectCapsLock} autoComplete="current-password" placeholder="请输入密码" aria-describedby={capsLock ? "caps-lock-hint" : undefined} required minLength={6} maxLength={128} />
              <button className="password-toggle" type="button" onClick={() => setShowPassword((value) => !value)} title={showPassword ? "隐藏密码" : "显示密码"} aria-label={showPassword ? "隐藏密码" : "显示密码"}>
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          {capsLock && <div id="caps-lock-hint" className="caps-lock-hint" role="status"><Info size={15} />大写锁定已开启</div>}
          <div className="login-form-options">
            <label><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />记住我</label>
            <button type="button" onClick={() => setError("密码重置需由所属企业的最高权限账号发起。")}>忘记密码？</button>
          </div>
          </> : <div className="trusted-did-login-panel">
            <label className="field"><span>选择主体身份标识</span><select value={did} onChange={(event) => setDid(event.target.value)}><option value="">未配置身份标识（由企业最高权限账号配置）</option></select></label>
            <label className="field"><span>凭证引用</span><input value={credential} onChange={(event) => setCredential(event.target.value)} placeholder="输入部署端提供的凭证引用" autoComplete="off" /></label>
            <div className="trusted-did-notice"><ShieldCheck size={15} /><span>当前环境未接入去中心化身份服务方。提交后只会提示未配置，不会创建会话或模拟认证成功。</span></div>
          </div>}
          {error && <Notice tone="warning">{error}</Notice>}
          <Button type="submit" variant="primary" busy={busy}>{mode === "did" ? "验证身份凭证" : "登录"}</Button>
          <div className="login-form-divider" aria-hidden="true"><span>或</span></div>
          <Button type="button" variant="secondary" onClick={() => { setMode((value) => value === "account" ? "did" : "account"); setError(""); }}>
            {mode === "account" ? "使用 DID 身份认证" : "使用账号密码登录"}
          </Button>

          {product.loginNotice && <Notice>{product.loginNotice}</Notice>}
          <div className="login-security-note"><ShieldCheck size={15} /><span>请使用授权账号登录，离开终端时及时退出系统。</span></div>
        </form>
      </main>

      <footer className="login-footer">
        {footerItems.map((item) => <span key={item}>{item}</span>)}
      </footer>
    </div>
  );
}
