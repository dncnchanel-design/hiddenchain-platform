import { useState, type FormEvent } from "react";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";
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
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [demoAccount, setDemoAccount] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function chooseDemoAccount(value: string) {
    setDemoAccount(value);
    const account = accounts.find((item) => item.username === value);
    if (!account) return;
    setUsername(account.username);
    setPassword(account.password);
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
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
      <section
        className="login-identity"
        aria-label="产品信息"
        draggable={false}
        onCopy={(event) => event.preventDefault()}
        onDragStart={(event) => event.preventDefault()}
      >
        <div className="login-visual" aria-hidden="true">
          <div className="login-visual-node node-one" />
          <div className="login-visual-node node-two" />
          <div className="login-visual-node node-three" />
        </div>
        <div className="login-identity-content">
          <div className="login-product-mark"><ShieldCheck size={24} /></div>
          <h1>隐链明算</h1>
          <h2>电力交易可信执行平台</h2>
        </div>
      </section>

      <section className="login-form-area">
        <form className="login-form" onSubmit={submit}>
          <div className="login-form-heading">
            <h2>登录工作空间</h2>
          </div>

          <label className="field">
            <span>账号</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" placeholder="输入账号" required minLength={3} maxLength={64} />
          </label>
          <label className="field">
            <span>密码</span>
            <div className="password-field">
              <input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder="输入密码" required minLength={6} maxLength={128} />
              <button className="password-toggle" type="button" onClick={() => setShowPassword((value) => !value)} title={showPassword ? "隐藏密码" : "显示密码"} aria-label={showPassword ? "隐藏密码" : "显示密码"}>
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          {error && <Notice tone="warning">{error}</Notice>}
          <Button type="submit" variant="primary" busy={busy}>登录</Button>

          <label className="demo-account-picker">
            <span>演示账号</span>
            <select aria-label="选择演示身份" value={demoAccount} onChange={(event) => chooseDemoAccount(event.target.value)}>
              <option value="">请选择</option>
              {accounts.map((account) => <option key={account.username} value={account.username}>{account.label}</option>)}
            </select>
          </label>
        </form>
      </section>
    </div>
  );
}
