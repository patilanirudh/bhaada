import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { fmtShort, inr, phoneDisplay, todayISO } from "../lib/format";
import type { Property, Tenant } from "../lib/types";
import { TenantWhatsAppButton } from "../components/WhatsApp";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, PageHeader, PageLoader, Select, useToast } from "../components/ui";
import { validateAadhaar, validatePan } from "../lib/validate";

const STATUSES = [
  { v: "", l: "All" },
  { v: "ACTIVE", l: "Active" },
  { v: "PENDING_APPROVAL", l: "Pending" },
  { v: "VACATED", l: "Vacated" },
  { v: "REJECTED", l: "Rejected" },
];

function AddTenant({ properties, onDone }: { properties: Property[]; onDone: (t: Tenant) => void }) {
  const qc = useQueryClient();
  const units = properties.flatMap((p) => p.units.map((u) => ({ ...u, label: `${p.name} · ${u.name}` })));
  const [f, setF] = useState({
    full_name: "", phone: "", email: "", unit_id: String(units[0]?.id ?? ""), base_rent: String(units[0]?.default_rent || ""),
    security_deposit: "", agreement_start_date: todayISO(), agreement_end_date: "", due_day: "5", increment_percent: "5",
    id_type: "", id_number: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () =>
      api<Tenant>("/api/tenants", {
        method: "POST",
        body: {
          ...f, email: f.email || null, unit_id: Number(f.unit_id), base_rent: Number(f.base_rent),
          security_deposit: Number(f.security_deposit || 0), due_day: Number(f.due_day), increment_percent: Number(f.increment_percent),
          agreement_end_date: f.agreement_end_date || null, id_type: f.id_type || null, id_number: f.id_number || null,
        },
      }),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["tenants"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); onDone(t); },
    onError: (e) => e instanceof ApiError && setErrors(e.errors),
  });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (f.id_number) {
      const x = f.id_type === "PAN" ? validatePan(f.id_number) : f.id_type === "AADHAAR" ? validateAadhaar(f.id_number) : "Choose the ID type";
      if (x) er.id_number = x;
    }
    if (!Number(f.base_rent)) er.base_rent = "Enter the rent";
    setErrors(er);
    if (!Object.keys(er).length) m.mutate();
  };
  if (!units.length) return <p className="text-sm text-slate-600">Add a property and unit first.</p>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-xs text-slate-500">For tenants already living with you. New tenants should use a registration link so they upload their own ID.</p>
      <ErrorBox error={m.error} />
      <Field label="Full name" required error={errors.full_name}><Input required value={f.full_name} onChange={set("full_name")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Mobile" required error={errors.phone}><Input required type="tel" value={f.phone} onChange={set("phone")} /></Field>
        <Field label="Email" error={errors.email}><Input type="email" value={f.email} onChange={set("email")} /></Field>
      </div>
      <Field label="Unit" required>
        <Select value={f.unit_id} onChange={(e) => {
          const u = units.find((x) => x.id === Number(e.target.value));
          setF({ ...f, unit_id: e.target.value, base_rent: u?.default_rent ? String(u.default_rent) : f.base_rent });
        }}>
          {units.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Rent at agreement start (₹)" required error={errors.base_rent}><Input type="number" min={1} value={f.base_rent} onChange={set("base_rent")} /></Field>
        <Field label="Deposit (₹)"><Input type="number" min={0} value={f.security_deposit} onChange={set("security_deposit")} /></Field>
        <Field label="Agreement start" required><Input type="date" required value={f.agreement_start_date} onChange={set("agreement_start_date")} /></Field>
        <Field label="Agreement end"><Input type="date" value={f.agreement_end_date} onChange={set("agreement_end_date")} /></Field>
        <Field label="Due day (1–28)" required><Input type="number" min={1} max={28} value={f.due_day} onChange={set("due_day")} /></Field>
        <Field label="Yearly increment %"><Input type="number" min={0} max={100} step="0.5" value={f.increment_percent} onChange={set("increment_percent")} /></Field>
        <Field label="ID type"><Select value={f.id_type} onChange={set("id_type")}><option value="">None</option><option value="AADHAAR">Aadhaar</option><option value="PAN">PAN</option></Select></Field>
        <Field label="ID number" error={errors.id_number}><Input value={f.id_number} disabled={!f.id_type} onChange={set("id_number")} autoComplete="off" /></Field>
      </div>
      <Button type="submit" className="w-full" loading={m.isPending}>Add tenant</Button>
    </form>
  );
}

export default function Tenants() {
  const nav = useNavigate();
  const toast = useToast();
  const [status, setStatus] = useState("ACTIVE");
  const [propertyId, setPropertyId] = useState("");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const props = useQuery({ queryKey: ["properties"], queryFn: () => api<Property[]>("/api/properties") });
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (propertyId) params.set("property_id", propertyId);
  if (q.trim()) params.set("q", q.trim());
  const tenants = useQuery({
    queryKey: ["tenants", status, propertyId, q],
    queryFn: () => api<Tenant[]>(`/api/tenants?${params}`),
  });

  return (
    <div>
      <PageHeader title="Tenants" actions={<>
        <Link to="/import"><Button variant="secondary">Import Excel</Button></Link>
        <Button onClick={() => setAdding(true)}>+ Add tenant</Button>
      </>} />
      <div className="mb-4 space-y-2">
        <Input placeholder="Search name, phone or email" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="flex flex-wrap gap-2">
          <div className="flex gap-1 overflow-x-auto">
            {STATUSES.map((s) => (
              <button key={s.v} onClick={() => setStatus(s.v)}
                className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium ${status === s.v ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}>
                {s.l}
              </button>
            ))}
          </div>
          <Select className="!w-auto !py-1.5 text-xs" value={propertyId} onChange={(e) => setPropertyId(e.target.value)}>
            <option value="">All properties</option>
            {props.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </div>
      </div>
      {tenants.isLoading ? <PageLoader /> : <ErrorBox error={tenants.error} />}
      {tenants.data?.length === 0 && <Empty title="No tenants found">Create a registration link or add a tenant.</Empty>}
      <div className="grid gap-3 md:grid-cols-2">
        {tenants.data?.map((t) => (
          <Card key={t.id} className="p-3">
            <div className="flex items-start justify-between gap-2">
              <Link to={`/tenants/${t.id}`} className="min-w-0">
                <p className="truncate font-semibold text-slate-900 hover:underline">{t.full_name}</p>
                <p className="text-xs text-slate-500">{t.property_name}{t.unit_name ? ` · ${t.unit_name}` : ""}</p>
                <p className="text-xs text-slate-500">{phoneDisplay(t.phone)}</p>
              </Link>
              <Badge value={t.status} />
            </div>
            {t.status === "ACTIVE" && (
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2">
                <div className="text-xs">
                  <span className="font-medium text-slate-800">{inr(t.current_rent)}/mo</span>
                  {t.pending_amount > 0 ? <span className="ml-2 text-red-700">Pending {inr(t.pending_amount)}</span> : <span className="ml-2 text-emerald-700">All paid</span>}
                  {t.last_reminded_on && <span className="ml-2 text-slate-500">· Reminded on {fmtShort(t.last_reminded_on)}</span>}
                </div>
                {t.pending_amount > 0 && <TenantWhatsAppButton tenantId={t.id} />}
              </div>
            )}
            {t.status === "PENDING_APPROVAL" && (
              <div className="mt-2 border-t border-slate-100 pt-2">
                <Link to={`/tenants/${t.id}`}><Button size="sm">Review & approve</Button></Link>
              </div>
            )}
          </Card>
        ))}
      </div>
      <Modal open={adding} onClose={() => setAdding(false)} title="Add existing tenant" wide>
        {props.data && <AddTenant properties={props.data} onDone={(t) => { setAdding(false); toast("Tenant added"); nav(`/tenants/${t.id}`); }} />}
      </Modal>
    </div>
  );
}
