import { useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { authApi, settingsApi } from "../api/endpoints";
import { useAuth } from "../lib/auth";
import RichTextEditor from "../components/RichTextEditor";
import { Badge, Button, Card, ErrorBox, Field, Input, PageHeader, PageLoader, Select, Textarea, errMsg, useToast } from "../components/ui";

function Section({ title, desc, children }: { title: string; desc?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <h2 className="font-semibold text-slate-900">{title}</h2>
      {desc && <div className="mb-3 mt-0.5 text-sm text-slate-500">{desc}</div>}
      {!desc && <div className="mb-3" />}
      {children}
    </Card>
  );
}

function Profile() {
  const { owner, setOwner } = useAuth();
  const toast = useToast();
  const [f, setF] = useState({ name: owner!.name, phone: owner!.phone ?? "", upi_id: owner!.upi_id ?? "", preferred_language: owner!.preferred_language });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => settingsApi.updateProfile(f),
    onSuccess: (o) => { setOwner(o); setErrors({}); toast("Profile saved"); },
    onError: (e) => e instanceof ApiError && setErrors(e.errors),
  });
  return (
    <Section title="Profile & UPI" desc="Your UPI ID goes into every reminder so tenants can pay in one tap.">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><ErrorBox error={m.error} /></div>
        <Field label="Name" error={errors.name}><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Mobile" error={errors.phone}><Input type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
        <Field label="UPI ID" error={errors.upi_id} hint="e.g. yourname@okhdfcbank"><Input value={f.upi_id} onChange={(e) => setF({ ...f, upi_id: e.target.value })} /></Field>
        <Field label="Message language">
          <Select value={f.preferred_language} onChange={(e) => setF({ ...f, preferred_language: e.target.value as "en" | "hi" })}>
            <option value="en">English</option><option value="hi">हिन्दी (Hindi)</option>
          </Select>
        </Field>
        <div className="sm:col-span-2"><Button type="submit" loading={m.isPending}>Save profile</Button></div>
      </form>
    </Section>
  );
}

function Gmail() {
  const { owner, setOwner } = useAuth();
  const toast = useToast();
  const [address, setAddress] = useState(owner!.gmail_address ?? "");
  const [pw, setPw] = useState("");
  const save = useMutation({
    mutationFn: () => settingsApi.saveGmail(address, pw),
    onSuccess: (o) => { setOwner(o); setPw(""); toast("Gmail saved. Send a test email to check."); },
  });
  const test = useMutation({
    mutationFn: () => settingsApi.testEmail(),
    onSuccess: (r) => toast(r.detail),
    onError: (e) => toast(errMsg(e), "err"),
  });
  const remove = useMutation({
    mutationFn: () => settingsApi.removeGmail(),
    onSuccess: (o) => { setOwner(o); setAddress(""); toast("Gmail disconnected"); },
  });
  if (owner!.email_mode === "service") {
    return (
      <Section title="Email" desc="Reminders, receipts and welcome emails are sent automatically by Rent Manager.">
        <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Emails show <b>your name</b> as the sender.</li>
          <li>When a tenant replies, it comes to <b>{owner!.email}</b>.</li>
          <li>No Gmail setup is needed.</li>
        </ul>
        <Button variant="secondary" loading={test.isPending} onClick={() => test.mutate()}>Send me a test email</Button>
      </Section>
    );
  }
  return (
    <Section title="Gmail for reminders" desc={<>Automatic emails (reminders, receipts) are sent from <b>your own Gmail</b>, free.
      {owner!.gmail_configured && <> <Badge value="ACTIVE" className="ml-1" /> Connected as {owner!.gmail_address}</>}</>}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-3">
        {!owner!.gmail_configured && <p className="rounded-lg bg-slate-50 p-2 text-xs text-slate-600">Not connected yet: emails are sent from the Rent Manager system Gmail with your name. Connect your own Gmail below so tenants see your address.</p>}
        <ErrorBox error={save.error} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Gmail address"><Input type="email" required value={address} onChange={(e) => setAddress(e.target.value)} placeholder="you@gmail.com" /></Field>
          <Field label="Gmail App Password" hint="16 letters, spaces are fine. Stored encrypted.">
            <Input type="password" required value={pw} onChange={(e) => setPw(e.target.value)} placeholder={owner!.gmail_configured ? "•••• •••• •••• ••••" : "abcd efgh ijkl mnop"} autoComplete="off" />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" loading={save.isPending}>Save Gmail</Button>
          <Button type="button" variant="secondary" loading={test.isPending} onClick={() => test.mutate()}>Send test email</Button>
          {owner!.gmail_configured && <Button type="button" variant="ghost" className="text-red-600" onClick={() => remove.mutate()}>Disconnect</Button>}
        </div>
      </form>
      <details className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
        <summary className="cursor-pointer font-medium">How do I create a Gmail App Password?</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>Open <a className="text-brand-700 underline" href="https://myaccount.google.com/security" target="_blank" rel="noreferrer">myaccount.google.com/security</a> and turn on <b>2-Step Verification</b> (required).</li>
          <li>Open <a className="text-brand-700 underline" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a>.</li>
          <li>Type a name like <i>Rent Manager</i> and tap <b>Create</b>.</li>
          <li>Copy the 16-letter password shown and paste it above. Your normal Gmail password is never needed.</li>
        </ol>
        <p className="mt-2 text-xs text-slate-500">Gmail allows about 500 emails a day — plenty for reminders. You can revoke the App Password anytime from the same page.</p>
      </details>
    </Section>
  );
}

function HouseRules() {
  const { owner, setOwner } = useAuth();
  const toast = useToast();
  const [rules, setRules] = useState(owner!.default_house_rules);
  const [applyAll, setApplyAll] = useState(false);
  const m = useMutation({
    mutationFn: () => settingsApi.saveHouseRules(rules, applyAll),
    onSuccess: (o) => { setOwner(o); toast(applyAll ? "Rules saved and applied to all properties" : "Default rules saved"); setApplyAll(false); },
  });
  return (
    <Section title="Default house rules" desc="Used for every new property. Each property's rules can still be edited on the Properties page.">
      <ErrorBox error={m.error} />
      <RichTextEditor value={rules} onChange={setRules} placeholder="Write your house rules…" />
      <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={applyAll} onChange={(e) => setApplyAll(e.target.checked)} />
        Also replace the rules of all my existing properties
      </label>
      <Button className="mt-3" loading={m.isPending} onClick={() => m.mutate()}>Save rules</Button>
    </Section>
  );
}

function Password() {
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const m = useMutation({
    mutationFn: () => authApi.changePassword(cur, nw),
    onSuccess: () => { setCur(""); setNw(""); toast("Password changed"); },
  });
  return (
    <Section title="Change password">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><ErrorBox error={m.error} /></div>
        <Field label="Current password"><Input type="password" required value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></Field>
        <Field label="New password" hint="At least 8 characters"><Input type="password" required minLength={8} value={nw} onChange={(e) => setNw(e.target.value)} autoComplete="new-password" /></Field>
        <div className="sm:col-span-2"><Button type="submit" loading={m.isPending}>Change password</Button></div>
      </form>
    </Section>
  );
}


function Templates() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: settingsApi.templates,
  });
  const [lang, setLang] = useState<"en" | "hi">("en");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (t: { kind: string; body: string }) => settingsApi.saveTemplate(t.kind, lang, t.body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["templates"] }); toast("Template saved"); },
    onError: (e) => toast(errMsg(e), "err"),
  });
  const reset = useMutation({
    mutationFn: (kind: string) => settingsApi.resetTemplate(kind, lang),
    onSuccess: (_, kind) => { setDrafts((d) => { const n = { ...d }; delete n[`${kind}:${lang}`]; return n; }); qc.invalidateQueries({ queryKey: ["templates"] }); toast("Reset to default"); },
  });
  if (isLoading || !data) return <PageLoader />;
  return (
    <Section title="Message templates" desc={<>Used for WhatsApp and email. Placeholders: {data.placeholders.map((p) => <code key={p} className="mr-1 rounded bg-slate-100 px-1 text-xs">{p}</code>)}</>}>
      <div className="mb-3 flex gap-1">
        {(["en", "hi"] as const).map((l) => (
          <button key={l} onClick={() => setLang(l)} className={`rounded-full px-3 py-1 text-xs font-medium ${lang === l ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600"}`}>
            {l === "en" ? "English" : "हिन्दी"}
          </button>
        ))}
      </div>
      <div className="space-y-4">
        {data.templates.filter((t) => t.language === lang).map((t) => {
          const key = `${t.kind}:${lang}`;
          const val = drafts[key] ?? t.body;
          return (
            <div key={key}>
              <p className="mb-1 text-sm font-medium text-slate-700">{data.kinds[t.kind]} {t.is_custom && <Badge value="CUSTOM" className="ml-1" />}</p>
              <Textarea rows={3} value={val} onChange={(e) => setDrafts({ ...drafts, [key]: e.target.value })} />
              <div className="mt-1 flex gap-2">
                <Button size="sm" disabled={val === t.body} onClick={() => save.mutate({ kind: t.kind, body: val })}>Save</Button>
                {t.is_custom && <Button size="sm" variant="ghost" onClick={() => reset.mutate(t.kind)}>Reset to default</Button>}
              </div>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

export default function Settings() {
  const { logout } = useAuth();
  const [params] = useSearchParams();
  return (
    <div className="space-y-4">
      <PageHeader title="Settings" actions={<Button variant="ghost" className="text-red-600 md:hidden" onClick={logout}>Log out</Button>} />
      {params.get("welcome") && (
        <div className="rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm text-brand-900">
          👋 Welcome! Add your <b>UPI ID</b> and connect <b>Gmail</b> below, then add your first property.
        </div>
      )}
      <Profile />
      <Gmail />
      <HouseRules />
      <Templates />
      <Password />
    </div>
  );
}
