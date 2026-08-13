import { useState } from "react";
import { Eye, EyeOff, LockKeyhole, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Button, Notice } from "../components/ui";

const accounts = [
  { label: "交易中心", username: "exchange", password: "exchange123" },
  { label: "发电企业", username: "generator", password: "generator123" },
  { label: "售电企业", username: "retailer", password: "retailer123" },
  { label: "监管方", username: "regulator", password: "regulator123" },
  { label: "平台维护", username: "admin", password: "admin123" },
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("exchange");
  const [password, setPassword] = useState("exchange123");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function chooseAccount(account: (typeof accounts)[number]) {
    setUsername(account.username);
    setPassword(account.password);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      navigate("/workbench", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败，请检查账号和密码");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <section className="login-identity" aria-label="平台信息">
        <div className="login-visual" aria-hidden="true">
          <div className="login-visual-orbit orbit-one" />
          <div className="login-visual-orbit orbit-two" />
          <div className="login-visual-grid" />
          <div className="login-visual-node node-one" />
          <div className="login-visual-node node-two" />
          <div className="login-visual-node node-three" />
        </div>
        <div className="login-identity-content">
          <div className="login-product-mark"><ShieldCheck size={25} /></div>
          <div className="eyebrow">隐链明算</div>
          <h1>可信数据协同平台</h1>
          <p>可信数据 · 隐私计算 · 可验证回执</p>
          <div className="login-identity-line" aria-hidden="true"><i /><i /><i /></div>
        </div>
        <span className="login-background-word" aria-hidden="true">TRUSTED DATA</span>
      </section>

      <section className="login-form-area">
        <form className="login-form" onSubmit={submit}>
          <div className="login-form-heading">
            <LockKeyhole size={22} />
            <div><h2>登录平台</h2><p>请选择登录身份</p></div>
          </div>
          <div className="login-role-grid" aria-label="登录身份">
            {accounts.map((account) => (
              <button
                type="button"
                key={account.username}
                className={username === account.username ? "selected" : ""}
                onClick={() => chooseAccount(account)}
              >{account.label}</button>
            ))}
          </div>
          <label className="field">
            <span>账号</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required minLength={3} maxLength={64} />
          </label>
          <label className="field">
            <span>密码</span>
            <div className="password-field">
              <input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required minLength={6} maxLength={128} />
              <button type="button" onClick={() => setShowPassword((value) => !value)} title={showPassword ? "隐藏密码" : "显示密码"}>
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>
          {error && <Notice tone="warning">{error}</Notice>}
          <Button type="submit" variant="primary" busy={busy}>登录</Button>
          <div className="login-form-foot"><ShieldCheck size={15} /><span>身份验证通过后进入对应工作台</span></div>
        </form>
      </section>
    </div>
  );
}
