import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { publicApi } from "../api/endpoints";
import { sniffFile, validateAadhaar, validatePan, validatePhone } from "../lib/validate";
import { Button, ErrorBox, Field, Input, PageLoader, Textarea } from "../components/ui";


export default function PublicRegister() {
  const { token = "" } = useParams();
  const info = useQuery({
    queryKey: ["public-register", token],
    queryFn: () => publicApi.linkInfo(token),
    retry: false,
  });
  const [f, setF] = useState({ full_name: "", phone: "", email: "", permanent_address: "", id_type: "AADHAAR", id_number: "", website: "" });
  const [doc, setDoc] = useState<File | null>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [rules, setRules] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  if (info.isLoading) return <PageLoader />;
  if (info.error || !info.data) {
    return (
      <Centered>
        <p className="text-4xl">🔗</p>
        <h1 className="mt-2 text-xl font-bold text-slate-900">Link not available</h1>
        <p className="mt-2 text-sm text-slate-600">{(info.error as Error)?.message ?? "This link is not valid."}</p>
      </Centered>
    );
  }
  const d = info.data;
  if (done) {
    return (
      <Centered>
        <p className="text-4xl">✅</p>
        <h1 className="mt-2 text-xl font-bold text-slate-900">Registration submitted</h1>
        <p className="mt-2 text-sm text-slate-600">{d.owner_name} will review your details and confirm. You'll get an email once approved.</p>
      </Centered>
    );
  }

  const validate = async () => {
    const e: Record<string, string> = {};
    if (f.full_name.trim().length < 2) e.full_name = "Enter your full name";
    const pe = validatePhone(f.phone);
    if (pe) e.phone = pe;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email.trim())) e.email = "Enter a valid email address";
    if (f.permanent_address.trim().length < 5) e.permanent_address = "Enter your permanent address";
    const ie = f.id_type === "AADHAAR" ? validateAadhaar(f.id_number) : validatePan(f.id_number);
    if (ie) e.id_number = ie;
    if (!doc) e.id_document = "Upload a photo or scan of your ID";
    else {
      const de = await sniffFile(doc, true);
      if (de) e.id_document = de;
    }
    if (photo) {
      const pe2 = await sniffFile(photo, false);
      if (pe2) e.photo = pe2;
    }
    if (!consent) e.consent = "Please give consent to continue";
    if (d.house_rules && !rules) e.rules_accepted = "Please confirm you have read the house rules";
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    const e = await validate();
    setErrors(e);
    if (Object.keys(e).length) {
      document.querySelector(`[data-err="1"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const form = new FormData();
    Object.entries(f).forEach(([k, v]) => form.append(k, v.trim()));
    form.append("consent", String(consent));
    form.append("rules_accepted", String(rules));
    form.append("id_document", doc!);
    if (photo) form.append("photo", photo);
    setBusy(true);
    try {
      await publicApi.register(token, form);
      setDone(true);
      window.scrollTo(0, 0);
    } catch (x) {
      setErr(x);
      if (x instanceof ApiError) setErrors(x.errors);
    } finally {
      setBusy(false);
    }
  };

  const E = ({ k }: { k: string }) => (errors[k] ? <p data-err="1" className="mt-1 text-xs text-red-600">{errors[k]}</p> : null);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-lg">
        <div className="mb-4 rounded-2xl bg-brand-700 p-5 text-white">
          <p className="text-xs uppercase tracking-wide text-brand-100">Tenant registration</p>
          <h1 className="mt-1 text-xl font-bold">{d.property_name}{d.unit_name ? ` · ${d.unit_name}` : ""}</h1>
          {d.property_address && <p className="mt-1 text-sm text-brand-100">{d.property_address}</p>}
          <p className="mt-2 text-sm">Owner: {d.owner_name}</p>
        </div>

        {d.house_rules && (
          <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-5">
            <h2 className="mb-2 font-semibold text-slate-900">House rules</h2>
            <div className="rich-text text-sm text-slate-700" dangerouslySetInnerHTML={{ __html: d.house_rules }} />
          </div>
        )}

        <form onSubmit={submit} noValidate className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
          <ErrorBox error={err} />
          <Field label="Full name (as on ID)" required error={errors.full_name}>
            <Input value={f.full_name} onChange={set("full_name")} autoComplete="name" />
          </Field>
          <Field label="Mobile number" required error={errors.phone}>
            <Input type="tel" inputMode="tel" value={f.phone} onChange={set("phone")} placeholder="98765 43210" autoComplete="tel" />
          </Field>
          <Field label="Email" required error={errors.email}>
            <Input type="email" value={f.email} onChange={set("email")} autoComplete="email" />
          </Field>
          <Field label="Permanent address" required error={errors.permanent_address}>
            <Textarea rows={3} value={f.permanent_address} onChange={set("permanent_address")} />
          </Field>

          <fieldset>
            <legend className="mb-1 text-sm font-medium text-slate-700">ID proof <span className="text-red-500">*</span></legend>
            <div className="grid grid-cols-2 gap-2">
              {(["AADHAAR", "PAN"] as const).map((t) => (
                <label key={t} className={`cursor-pointer rounded-lg border px-3 py-2.5 text-center text-sm font-medium ${f.id_type === t ? "border-brand-600 bg-brand-50 text-brand-800" : "border-slate-300 text-slate-700"}`}>
                  <input type="radio" name="id_type" className="sr-only" checked={f.id_type === t} onChange={() => setF({ ...f, id_type: t, id_number: "" })} />
                  {t === "AADHAAR" ? "Aadhaar" : "PAN"}
                </label>
              ))}
            </div>
          </fieldset>
          <Field label={f.id_type === "AADHAAR" ? "Aadhaar number" : "PAN number"} required error={errors.id_number}
            hint="Stored encrypted. The owner only sees the last 4 digits.">
            <Input
              value={f.id_number}
              onChange={(e) => setF({ ...f, id_number: f.id_type === "PAN" ? e.target.value.toUpperCase() : e.target.value })}
              inputMode={f.id_type === "AADHAAR" ? "numeric" : "text"}
              maxLength={f.id_type === "AADHAAR" ? 14 : 10}
              placeholder={f.id_type === "AADHAAR" ? "1234 5678 9012" : "ABCDE1234F"}
              autoComplete="off"
            />
          </Field>
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700">Upload ID document <span className="text-red-500">*</span></span>
            <input type="file" accept="image/jpeg,image/png,application/pdf" onChange={(e) => setDoc(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-brand-700" />
            <p className="mt-1 text-xs text-slate-500">JPG, PNG or PDF, up to 5 MB</p>
            <E k="id_document" />
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700">Your photo (optional)</span>
            <input type="file" accept="image/jpeg,image/png" capture="user" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700" />
            <E k="photo" />
          </div>

          {/* Honeypot: hidden from humans */}
          <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
            <label>Website<input tabIndex={-1} autoComplete="off" value={f.website} onChange={set("website")} /></label>
          </div>

          <details className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            <summary className="cursor-pointer font-medium text-slate-700">How your data is used (privacy notice)</summary>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              <li><b>Who sees it:</b> only {d.owner_name}, for renting this property. It is never sold or shared with anyone else.</li>
              <li><b>What:</b> your name, contact details, address, ID number and ID document (and photo, if you add one).</li>
              <li><b>Security:</b> your ID number is encrypted; the owner only sees its last 4 digits. Documents are stored privately and open only through short-lived links.</li>
              <li><b>How long:</b> ID documents are deleted automatically 90 days after you move out (immediately if your registration is rejected).</li>
              <li><b>Your rights:</b> you can ask {d.owner_name} to correct or erase your data after the tenancy ends.</li>
            </ul>
          </details>
          {d.house_rules && (
            <label className="flex gap-3 text-sm text-slate-700">
              <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-brand-600" checked={rules} onChange={(e) => setRules(e.target.checked)} />
              <span>I have read the house rules<E k="rules_accepted" /></span>
            </label>
          )}
          <label className="flex gap-3 text-sm text-slate-700">
            <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-brand-600" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>I agree to share my details and ID document with the owner for rental purposes.<E k="consent" /></span>
          </label>
          <Button type="submit" className="w-full" loading={busy}>Submit registration</Button>
          <p className="text-center text-xs text-slate-500">Your data is shared only with {d.owner_name} as per India's DPDP Act.</p>
        </form>
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="max-w-sm rounded-2xl border border-slate-200 bg-white p-8 text-center">{children}</div>
    </div>
  );
}
