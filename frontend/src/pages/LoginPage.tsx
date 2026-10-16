import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { AudioLines } from "lucide-react";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/Button";
import { ErrorBanner } from "../components/Feedback";
import { Field } from "../components/Field";
import "./login.css";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/campaigns";
  if (user) return <Navigate to={from} replace />;

  const fieldErrors = error instanceof ApiError ? error.fieldErrors() : {};

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login">
      <div className="login__panel">
        <div className="brand" style={{ padding: 0, marginBottom: 28 }}>
          <span className="brand__mark">
            <AudioLines size={16} />
          </span>
          Campaign Manager
        </div>
        <h1>Sign in</h1>
        <p className="muted" style={{ marginTop: 4, marginBottom: 24 }}>
          Run and monitor outbound voice-agent campaigns.
        </p>
        <form className="stack" onSubmit={onSubmit} noValidate>
          {error != null && <ErrorBanner error={error} shownFields={["email", "password"]} />}
          <Field label="Email" error={fieldErrors.email}>
            <input
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
              required
            />
          </Field>
          <Field label="Password" error={fieldErrors.password}>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <Button type="submit" variant="primary" loading={submitting} style={{ height: 40, marginTop: 4 }}>
            Sign in
          </Button>
        </form>
      </div>
      <div className="login__aside" aria-hidden>
        <div className="login__aside-inner">
          <h2>Every call, paced and accounted for.</h2>
          <p>
            Upload a cohort, set a calling window and retry rules, and watch each contact move from pending to done
            in real time, always within your organisation's limits.
          </p>
        </div>
      </div>
    </div>
  );
}
