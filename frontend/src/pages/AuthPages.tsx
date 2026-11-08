import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button, ErrorBox, Field, Input } from "../components/ui";

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-b from-brand-50 to-slate-50 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <img src="/favicon.svg" alt="" className="mx-auto h-12 w-12" />
          <h1 className="mt-3 text-2xl font-bold text-slate-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">{children}</div>
      </div>
    </div>
  );
}

export function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(email.trim(), password);
      nav(loc.state?.from ?? "/", { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title="Rent Manager" subtitle="Log in to manage your tenants and rent">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={err} />
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" className="w-full" loading={busy}>Log in</Button>
        <div className="flex justify-between text-sm">
          <Link to="/forgot-password" className="text-brand-700 hover:underline">Forgot password?</Link>
          <Link to="/signup" className="text-brand-700 hover:underline">Create account</Link>
        </div>
      </form>
    </Shell>
  );
}

export function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", phone: "", password: "" });
  const [err, setErr] = useState<unknown>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password.length < 8) return setFieldErr({ password: "Use at least 8 characters" });
    setBusy(true);
    setErr(null);
    setFieldErr({});
    try {
      await register({ ...form, email: form.email.trim(), phone: form.phone || undefined });
      nav("/settings?welcome=1", { replace: true });
    } catch (e) {
      setErr(e);
      if (e instanceof ApiError) setFieldErr(e.errors);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title="Create your account" subtitle="Free for landlords. Takes 1 minute.">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={err} />
        <Field label="Your name" required error={fieldErr.name}>
          <Input required minLength={2} value={form.name} onChange={set("name")} autoComplete="name" />
        </Field>
        <Field label="Email" required error={fieldErr.email}>
          <Input type="email" required value={form.email} onChange={set("email")} autoComplete="email" />
        </Field>
        <Field label="Mobile number" error={fieldErr.phone}>
          <Input type="tel" inputMode="tel" placeholder="98765 43210" value={form.phone} onChange={set("phone")} />
        </Field>
        <Field label="Password" required error={fieldErr.password} hint="At least 8 characters">
          <Input type="password" required minLength={8} value={form.password} onChange={set("password")} autoComplete="new-password" />
        </Field>
        <Button type="submit" className="w-full" loading={busy}>Create account</Button>
        <p className="text-center text-sm">
          Already registered? <Link to="/login" className="text-brand-700 hover:underline">Log in</Link>
        </p>
      </form>
    </Shell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ detail: string }>("/api/auth/forgot-password", { method: "POST", body: { email }, auth: false });
      setDone(r.detail);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Forgot password" subtitle="We'll email you a reset link">
      {done ? (
        <div className="space-y-4 text-sm">
          <p className="rounded-lg bg-brand-50 p-3 text-brand-900">{done}</p>
          <Link to="/login" className="text-brand-700 hover:underline">Back to login</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <ErrorBox error={err} />
          <Field label="Email">
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" className="w-full" loading={busy}>Send reset link</Button>
          <Link to="/login" className="block text-center text-sm text-brand-700 hover:underline">Back to login</Link>
        </form>
      )}
    </Shell>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) return setErr(new Error("Passwords do not match"));
    setBusy(true);
    setErr(null);
    try {
      await api("/api/auth/reset-password", { method: "POST", body: { token: params.get("token"), password }, auth: false });
      nav("/login", { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={err} />
        <Field label="New password" hint="At least 8 characters">
          <Input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Confirm password">
          <Input type="password" required minLength={8} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <Button type="submit" className="w-full" loading={busy}>Update password</Button>
      </form>
    </Shell>
  );
}
