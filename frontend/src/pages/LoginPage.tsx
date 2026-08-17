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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [capsLock, setCapsLock] = useState(false);
  const product = useProductConfig();
  const version = import.meta.env.VITE_APP_VERSION || "0.1.0";
  const footerItems = productFooterItems(product, version);

  function detectCapsLock(event: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(event.getModifierState("CapsLock"));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
    <div className="login-screen">
      <header className="login-brandbar">
        <div className="login-brand">
          <span className="login-product-mark"><BrandMark size={21} /></span>
          <span><strong>{product.productName}</strong><small>{product.productSubtitle}</small></span>
        </div>
        <div className="login-runtime">{product.environmentName && <span className="environment-tag">{product.environmentName}</span>}<span>版本 {version}</span></div>
      </header>

      <main className="login-main">
        <form className="login-form" onSubmit={submit}>
          <div className="login-form-heading">
            <span className="login-form-icon" aria-hidden="true"><LockKeyhole size={20} /></span>
            <div><h1>登录系统</h1><p>使用已授权账号进入工作空间</p></div>
          </div>

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
          {error && <Notice tone="warning">{error}</Notice>}
          <Button type="submit" variant="primary" busy={busy}>登录</Button>

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
