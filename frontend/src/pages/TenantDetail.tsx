import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { openSigned } from "../api/client";
import { propertiesApi, rentApi, tenantsApi } from "../api/endpoints";
import { addYearsISO, fmtDate, inr, monthLabel, phoneDisplay, todayISO } from "../lib/format";
import type { Property, RentEntry, Tenant } from "../lib/types";
import { MarkPaidModal, ReceiptLink } from "../components/MarkPaid";
import { TenantWhatsAppButton } from "../components/WhatsApp";
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, PageLoader, Select, Textarea, errMsg, useToast } from "../components/ui";

function useInvalidate() {
  const qc = useQueryClient();
  return () => ["tenant", "tenants", "ledger", "actions", "summary", "history", "reminders"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm font-medium text-slate-900">{children}</dd>
    </div>
  );
}

function ApproveForm({ t, properties }: { t: Tenant; properties: Property[] }) {
  const inv = useInvalidate();
  const toast = useToast();
  const prop = properties.find((p) => p.id === t.property_id);
  const unit = prop?.units.find((u) => u.id === t.unit_id);
  const start = todayISO();
  const [f, setF] = useState({
    unit_id: String(t.unit_id ?? prop?.units[0]?.id ?? ""),
    base_rent: String(unit?.default_rent || prop?.units[0]?.default_rent || ""),
    security_deposit: "",
    agreement_start_date: start,
    agreement_end_date: addYearsISO(start, 1),
    due_day: "5",
    increment_percent: "5",
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const approve = useMutation({
    mutationFn: () =>
      tenantsApi.approve(t.id, {
          unit_id: Number(f.unit_id), base_rent: Number(f.base_rent), security_deposit: Number(f.security_deposit || 0),
          agreement_start_date: f.agreement_start_date, agreement_end_date: f.agreement_end_date || null,
          due_day: Number(f.due_day), increment_percent: Number(f.increment_percent),
        }),
    onSuccess: () => { inv(); toast("Tenant approved. Welcome email sent."); },
  });
  const reject = useMutation({
    mutationFn: () => tenantsApi.reject(t.id),
    onSuccess: () => { inv(); toast("Registration rejected and ID documents deleted"); },
    onError: (e) => toast(errMsg(e), "err"),
  });
  return (
    <Card className="border-amber-300 bg-amber-50/40">
      <h2 className="font-semibold text-slate-900">Review & approve</h2>
      <p className="mb-3 text-sm text-slate-600">Check the ID document, then fill in the rent details.</p>
      <form onSubmit={(e) => { e.preventDefault(); approve.mutate(); }} className="space-y-3">
        <ErrorBox error={approve.error} />
        <Field label="Unit" required>
          <Select value={f.unit_id} onChange={set("unit_id")} required>
            {properties.flatMap((p) => p.units.map((u) => <option key={u.id} value={u.id}>{p.name} · {u.name}</option>))}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Monthly rent (₹)" required><Input type="number" min={1} required value={f.base_rent} onChange={set("base_rent")} /></Field>
          <Field label="Security deposit (₹)"><Input type="number" min={0} value={f.security_deposit} onChange={set("security_deposit")} /></Field>
          <Field label="Agreement start" required><Input type="date" required value={f.agreement_start_date}
            onChange={(e) => setF({ ...f, agreement_start_date: e.target.value, agreement_end_date: e.target.value ? addYearsISO(e.target.value, 1) : "" })} /></Field>
          <Field label="Agreement end"><Input type="date" value={f.agreement_end_date} onChange={set("agreement_end_date")} /></Field>
          <Field label="Rent due day (1–28)" required><Input type="number" min={1} max={28} required value={f.due_day} onChange={set("due_day")} /></Field>
          <Field label="Yearly increment %"><Input type="number" min={0} max={100} step="0.5" value={f.increment_percent} onChange={set("increment_percent")} /></Field>
        </div>
        <div className="flex gap-2">
          <Button type="submit" loading={approve.isPending} className="flex-1">Approve</Button>
          <Button type="button" variant="danger" loading={reject.isPending}
            onClick={() => confirm("Reject this registration? Their ID documents will be deleted.") && reject.mutate()}>Reject</Button>
        </div>
      </form>
    </Card>
  );
}

function EditModal({ t, properties, onClose }: { t: Tenant; properties: Property[]; onClose: () => void }) {
  const inv = useInvalidate();
  const [f, setF] = useState({
    full_name: t.full_name, phone: t.phone, email: t.email ?? "", permanent_address: t.permanent_address ?? "",
    unit_id: String(t.unit_id ?? ""), security_deposit: String(t.security_deposit), due_day: String(t.due_day),
    increment_percent: String(t.increment_percent),
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () => tenantsApi.update(t.id, { ...f, email: f.email || null, unit_id: f.unit_id ? Number(f.unit_id) : null, security_deposit: Number(f.security_deposit),
        due_day: Number(f.due_day), increment_percent: Number(f.increment_percent) }),
    onSuccess: () => { inv(); onClose(); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
      <ErrorBox error={m.error} />
      <Field label="Full name"><Input value={f.full_name} onChange={set("full_name")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Mobile"><Input value={f.phone} onChange={set("phone")} /></Field>
        <Field label="Email"><Input type="email" value={f.email} onChange={set("email")} /></Field>
      </div>
      <Field label="Permanent address"><Textarea rows={2} value={f.permanent_address} onChange={set("permanent_address")} /></Field>
      <Field label="Unit"><Select value={f.unit_id} onChange={set("unit_id")}>
        {properties.flatMap((p) => p.units.map((u) => <option key={u.id} value={u.id}>{p.name} · {u.name}</option>))}
      </Select></Field>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Deposit"><Input type="number" min={0} value={f.security_deposit} onChange={set("security_deposit")} /></Field>
        <Field label="Due day"><Input type="number" min={1} max={28} value={f.due_day} onChange={set("due_day")} /></Field>
        <Field label="Increment %"><Input type="number" min={0} max={100} step="0.5" value={f.increment_percent} onChange={set("increment_percent")} /></Field>
      </div>
      <Button type="submit" className="w-full" loading={m.isPending}>Save</Button>
    </form>
  );
}

function SimpleMutationForm({ label, type, initial, submit, button, hint, onClose }: {
  label: string; type: string; initial: string; submit: (value: string) => Promise<unknown>; button: string; hint?: string; onClose: () => void;
}) {
  const inv = useInvalidate();
  const toast = useToast();
  const [v, setV] = useState(initial);
  const m = useMutation({
    mutationFn: () => submit(v),
    onSuccess: () => { inv(); toast("Saved"); onClose(); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
      <ErrorBox error={m.error} />
      <Field label={label} hint={hint}><Input type={type} required value={v} onChange={(e) => setV(e.target.value)} /></Field>
      <Button type="submit" className="w-full" loading={m.isPending}>{button}</Button>
    </form>
  );
}

function VacateForm({ t, onClose }: { t: Tenant; onClose: () => void }) {
  const inv = useInvalidate();
  const toast = useToast();
  const [date, setDate] = useState(todayISO());
  const [deductions, setDeductions] = useState<{ label: string; amount: string }[]>([{ label: "Maintenance charge", amount: "3000" }]);
  const [notes, setNotes] = useState("");
  const body = () => ({
    vacate_date: date, notes: notes || null,
    deductions: deductions.filter((d) => d.label && Number(d.amount) > 0).map((d) => ({ label: d.label, amount: Number(d.amount) })),
  });
  const preview = useQuery({
    queryKey: ["settlement-preview", t.id, date, JSON.stringify(deductions)],
    queryFn: () => tenantsApi.settlementPreview(t.id, body()),
    enabled: !!date,
  });
  const m = useMutation({
    mutationFn: () => tenantsApi.vacate(t.id, body()),
    onSuccess: () => { inv(); toast("Tenant vacated. Settlement PDF ready."); onClose(); },
  });
  const s = preview.data;
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
      <ErrorBox error={m.error} />
      <Field label="Vacate date" required><Input type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      <div>
        <p className="mb-1 text-sm font-medium text-slate-700">Deductions</p>
        {deductions.map((d, i) => (
          <div key={i} className="mb-2 flex gap-2">
            <Input placeholder="e.g. Painting" value={d.label} onChange={(e) => setDeductions(deductions.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <Input type="number" min={0} placeholder="₹" className="!w-28" value={d.amount} onChange={(e) => setDeductions(deductions.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
            <Button type="button" variant="ghost" onClick={() => setDeductions(deductions.filter((_, j) => j !== i))} aria-label="Remove">✕</Button>
          </div>
        ))}
        <Button type="button" size="sm" variant="secondary" onClick={() => setDeductions([...deductions, { label: "", amount: "" }])}>+ Add deduction</Button>
      </div>
      <Field label="Notes"><Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} /></Field>
      {s && (
        <div className="rounded-lg bg-slate-50 p-3 text-sm">
          <div className="flex justify-between"><span>Security deposit</span><span>{inr(s.deposit)}</span></div>
          {s.pending_months.map((p) => <div key={p.month} className="flex justify-between text-red-700"><span>Pending rent {p.label}</span><span>-{inr(p.amount)}</span></div>)}
          {s.deductions.map((d, i) => <div key={i} className="flex justify-between text-red-700"><span>{d.label}</span><span>-{inr(d.amount)}</span></div>)}
          <div className="mt-1 flex justify-between border-t border-slate-300 pt-1 font-semibold">
            <span>{s.refund >= 0 ? "Refund to tenant" : "Tenant owes you"}</span><span>{inr(Math.abs(s.refund))}</span>
          </div>
        </div>
      )}
      <Button type="submit" variant="danger" className="w-full" loading={m.isPending}>Vacate & generate settlement PDF</Button>
    </form>
  );
}

export default function TenantDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const inv = useInvalidate();
  const tid = Number(id);
  const t = useQuery({ queryKey: ["tenant", tid], queryFn: () => tenantsApi.get(tid) });
  const props = useQuery({ queryKey: ["properties"], queryFn: propertiesApi.list });
  const ledger = useQuery({ queryKey: ["ledger", tid], queryFn: () => tenantsApi.ledger(tid), enabled: !!t.data });
  const history = useQuery({ queryKey: ["history", tid], queryFn: () => tenantsApi.history(tid), enabled: !!t.data });
  const logs = useQuery({ queryKey: ["reminders", tid], queryFn: () => tenantsApi.reminders(tid), enabled: !!t.data });
  const [modal, setModal] = useState<"edit" | "rent" | "renew" | "vacate" | null>(null);
  const [paying, setPaying] = useState<RentEntry | null>(null);

  useEffect(() => {
    if (params.get("renew") === "1") { setModal("renew"); setParams({}, { replace: true }); }
  }, [params, setParams]);

  const delPayment = useMutation({
    mutationFn: (pid: number) => rentApi.deletePayment(pid),
    onSuccess: () => { inv(); toast("Payment deleted"); },
    onError: (e) => toast(errMsg(e), "err"),
  });
  const delDocs = useMutation({
    mutationFn: () => tenantsApi.deleteDocuments(tid),
    onSuccess: () => { inv(); toast("ID documents deleted"); },
    onError: (e) => toast(errMsg(e), "err"),
  });
  const erase = useMutation({
    mutationFn: () => tenantsApi.erase(tid),
    onSuccess: () => { inv(); toast("Personal data erased"); },
    onError: (e) => toast(errMsg(e), "err"),
  });
  const open = (path: string) => openSigned(path).catch((e) => toast(errMsg(e), "err"));

  if (t.isLoading || props.isLoading) return <PageLoader />;
  if (t.error || !t.data) return <ErrorBox error={t.error} />;
  const x = t.data;
  const active = x.status === "ACTIVE";

  return (
    <div className="space-y-4">
      <div>
        <Link to="/tenants" className="text-sm text-brand-700 hover:underline">← Tenants</Link>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{x.full_name}</h1>
            <p className="text-sm text-slate-500">{x.property_name}{x.unit_name ? ` · ${x.unit_name}` : ""}</p>
          </div>
          <Badge value={x.status} />
        </div>
        {active && (
          <div className="mt-3 flex flex-wrap gap-2">
            {x.pending_amount > 0 && <TenantWhatsAppButton tenantId={x.id} />}
            <Button size="sm" variant="secondary" onClick={() => setModal("edit")}>Edit</Button>
            <Button size="sm" variant="secondary" onClick={() => setModal("rent")}>Change rent</Button>
            <Button size="sm" variant="secondary" onClick={() => setModal("renew")}>Renew</Button>
            <TenantWhatsAppButton tenantId={x.id} kind="welcome" label="Send welcome" />
            <Button size="sm" variant="danger" onClick={() => setModal("vacate")}>Vacate</Button>
          </div>
        )}
      </div>

      {x.status === "PENDING_APPROVAL" && props.data && <ApproveForm t={x} properties={props.data} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold text-slate-900">Profile</h2>
          <dl className="grid grid-cols-2 gap-3">
            <Info label="Mobile"><a href={`tel:${x.phone}`} className="text-brand-700">{phoneDisplay(x.phone)}</a></Info>
            <Info label="Email">{x.email ?? "—"}</Info>
            <Info label="ID">{x.id_type ? `${x.id_type === "PAN" ? "PAN" : "Aadhaar"} ${x.id_masked}` : "—"}</Info>
            <Info label="Consent given">{x.consent_given_at ? fmtDate(x.consent_given_at) : "—"}</Info>
            <div className="col-span-2"><Info label="Permanent address">{x.permanent_address ?? "—"}</Info></div>
          </dl>
          <div className="mt-3 flex flex-wrap gap-2">
            {x.has_id_document && <Button size="sm" variant="secondary" onClick={() => open(tenantsApi.documentUrlPath(x.id))}>View ID document</Button>}
            {x.has_photo && <Button size="sm" variant="secondary" onClick={() => open(tenantsApi.photoUrlPath(x.id))}>View photo</Button>}
            {(x.status === "VACATED" || x.status === "REJECTED") && (x.has_id_document || x.has_photo) && (
              <Button size="sm" variant="danger" loading={delDocs.isPending} onClick={() => confirm("Permanently delete the ID document and photo?") && delDocs.mutate()}>Delete ID documents</Button>
            )}
          </div>
          {(x.status === "VACATED" || x.status === "REJECTED") && !x.full_name.startsWith("Erased tenant") && (
            <div className="mt-3 border-t border-slate-100 pt-3">
              <Button size="sm" variant="ghost" className="text-red-600" loading={erase.isPending}
                onClick={() => confirm("Erase this person's name, phone, email, address, ID and documents permanently? Rent and payment records are kept without their identity.") && erase.mutate()}>
                Erase personal data (privacy request)
              </Button>
            </div>
          )}
          {x.status === "VACATED" && (x.has_id_document || x.has_photo) && (
            <p className="mt-2 text-xs text-slate-500">ID documents are deleted automatically 90 days after move-out.</p>
          )}
        </Card>

        {(active || x.status === "VACATED") && (
          <Card>
            <h2 className="mb-3 font-semibold text-slate-900">Rent & agreement</h2>
            <dl className="grid grid-cols-2 gap-3">
              <Info label="Current rent">{inr(x.current_rent)}</Info>
              <Info label="Pending">{x.pending_amount ? <span className="text-red-700">{inr(x.pending_amount)}</span> : "Nil"}</Info>
              <Info label="Base rent">{inr(x.base_rent)}</Info>
              <Info label="Yearly increment">{x.increment_percent}%</Info>
              <Info label="Due day">{x.due_day} of every month</Info>
              <Info label="Deposit">{inr(x.security_deposit)}</Info>
              <Info label="Agreement start">{fmtDate(x.agreement_start_date)}</Info>
              <Info label="Agreement end">{fmtDate(x.agreement_end_date)}</Info>
            </dl>
          </Card>
        )}
      </div>

      {x.status === "VACATED" && x.settlement && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-semibold text-slate-900">Deposit settlement</h2>
              <p className="text-sm text-slate-600">Vacated {fmtDate(x.vacated_at)} · {x.settlement.refund >= 0 ? `Refund ${inr(x.settlement.refund)}` : `Tenant owes ${inr(-x.settlement.refund)}`}</p>
            </div>
            {x.has_settlement_pdf && <Button size="sm" variant="secondary" onClick={() => open(tenantsApi.settlementUrlPath(x.id))}>Settlement PDF</Button>}
          </div>
        </Card>
      )}

      {(ledger.data?.length ?? 0) > 0 && (
        <Card>
          <h2 id="ledger" className="mb-3 font-semibold text-slate-900">Rent ledger</h2>
          <ul className="divide-y divide-slate-100">
            {ledger.data!.map((e) => (
              <li key={e.id} className="py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium text-slate-900">{monthLabel(e.month)} <Badge value={e.status} className="ml-1" /></p>
                    <p className="text-xs text-slate-500">Due {fmtDate(e.due_date)} · {inr(e.amount_paid)} of {inr(e.amount_due)} paid</p>
                  </div>
                  {e.status !== "PAID" && active && <Button size="sm" onClick={() => setPaying(e)}>Mark as paid</Button>}
                </div>
                {e.payments.length > 0 && (
                  <ul className="mt-2 space-y-1 rounded-lg bg-slate-50 p-2 text-xs">
                    {e.payments.map((p) => (
                      <li key={p.id} className="flex flex-wrap items-center justify-between gap-2">
                        <span>{inr(p.amount)} · {p.mode}{p.reference ? ` (${p.reference})` : ""} · {fmtDate(p.paid_on)}</span>
                        <span className="flex gap-3">
                          {p.has_receipt && <ReceiptLink paymentId={p.id} />}
                          <button className="text-red-600 hover:underline" onClick={() => confirm("Delete this payment?") && delPayment.mutate(p.id)}>Delete</button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 font-semibold text-slate-900">Rent history</h2>
          {history.data?.length ? (
            <ul className="divide-y divide-slate-100 text-sm">
              {history.data.map((h) => (
                <li key={h.id} className="flex justify-between py-2">
                  <span>{inr(h.old_rent)} → <b>{inr(h.new_rent)}</b></span>
                  <span className="text-xs text-slate-500">{fmtDate(h.effective_from)} · {h.reason === "MANUAL" ? "Manual" : "Yearly"}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-500">No rent changes yet.</p>}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold text-slate-900">Reminder log</h2>
          {logs.data?.length ? (
            <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto text-sm">
              {logs.data.map((l) => (
                <li key={l.id} className="flex items-center justify-between gap-2 py-2">
                  <span>{l.type.replace(/_/g, " ").toLowerCase()} <span className="text-xs text-slate-500">· {l.channel === "EMAIL" ? "Email" : "WhatsApp"}</span></span>
                  <span className="flex items-center gap-2 text-xs text-slate-500">{fmtDate(l.sent_at)} <Badge value={l.status} /></span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-500">No reminders sent yet.</p>}
        </Card>
      </div>

      <MarkPaidModal entry={paying} onClose={() => setPaying(null)} />
      <Modal open={modal === "edit"} onClose={() => setModal(null)} title="Edit tenant" wide>
        {props.data && <EditModal t={x} properties={props.data} onClose={() => setModal(null)} />}
      </Modal>
      <Modal open={modal === "rent"} onClose={() => setModal(null)} title="Change rent">
        <SimpleMutationForm label="New monthly rent (₹)" type="number" initial={String(x.current_rent)}
          submit={(v) => tenantsApi.changeRent(x.id, Number(v))} button="Update rent"
          hint="Applies from the next rent entry. Yearly increments continue from this amount." onClose={() => setModal(null)} />
      </Modal>
      <Modal open={modal === "renew"} onClose={() => setModal(null)} title="Renew agreement">
        <SimpleMutationForm label="New agreement end date" type="date"
          initial={x.agreement_end_date
            ? `${Number(x.agreement_end_date.slice(0, 4)) + 1}${x.agreement_end_date.slice(4)}`.replace("-02-29", "-02-28")
            : addYearsISO(todayISO(), 1)}
          submit={(v) => tenantsApi.renew(x.id, v)} button="Renew" onClose={() => setModal(null)} />
      </Modal>
      <Modal open={modal === "vacate"} onClose={() => setModal(null)} title="Vacate tenant">
        <VacateForm t={x} onClose={() => setModal(null)} />
      </Modal>
    </div>
  );
}
