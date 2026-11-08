import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { inr } from "../lib/format";
import type { Property, Unit } from "../lib/types";
import RichTextEditor from "../components/RichTextEditor";
import { Button, Card, Empty, ErrorBox, Field, Input, Modal, PageHeader, PageLoader, Textarea, errMsg, useToast } from "../components/ui";

const DEFAULT_RULES =
  "<ul><li>Rent is due by the 5th of every month.</li><li>No smoking inside the flat.</li><li>Visitors allowed till 10 PM.</li><li>Keep common areas clean.</li><li>One month notice before vacating.</li></ul>";

function PropertyForm({ initial, onDone }: { initial?: Property; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(initial?.name ?? "");
  const [address, setAddress] = useState(initial?.address ?? "");
  const [rules, setRules] = useState(initial?.house_rules ?? DEFAULT_RULES);
  const m = useMutation({
    mutationFn: () =>
      api(initial ? `/api/properties/${initial.id}` : "/api/properties", {
        method: initial ? "PUT" : "POST",
        body: { name, address, house_rules: rules },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["properties"] });
      toast(initial ? "Property updated" : "Property added");
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBox error={m.error} />
      <Field label="Property name" required>
        <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Green Residency" />
      </Field>
      <Field label="Address">
        <Textarea rows={2} value={address} onChange={(e) => setAddress(e.target.value)} />
      </Field>
      <Field label="House rules" hint="Shown on the registration page and in the welcome email.">
        <RichTextEditor value={rules} onChange={setRules} placeholder="Write your house rules…" />
      </Field>
      <Button type="submit" className="w-full" loading={m.isPending}>Save</Button>
    </form>
  );
}

function UnitForm({ propertyId, unit, onDone }: { propertyId: number; unit?: Unit; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(unit?.name ?? "");
  const [rent, setRent] = useState(String(unit?.default_rent ?? ""));
  const m = useMutation({
    mutationFn: () =>
      api(unit ? `/api/properties/units/${unit.id}` : `/api/properties/${propertyId}/units`, {
        method: unit ? "PUT" : "POST",
        body: { name, default_rent: Number(rent || 0) },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["properties"] });
      onDone();
    },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-4">
      <ErrorBox error={m.error} />
      <Field label="Unit name" required><Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Flat 203" /></Field>
      <Field label="Default monthly rent (₹)"><Input type="number" min={0} inputMode="numeric" value={rent} onChange={(e) => setRent(e.target.value)} /></Field>
      <Button type="submit" className="w-full" loading={m.isPending}>Save unit</Button>
    </form>
  );
}

export default function Properties() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading, error } = useQuery({ queryKey: ["properties"], queryFn: () => api<Property[]>("/api/properties") });
  const [editing, setEditing] = useState<Property | "new" | null>(null);
  const [unitModal, setUnitModal] = useState<{ propertyId: number; unit?: Unit } | null>(null);

  const del = useMutation({
    mutationFn: (path: string) => api(path, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["properties"] }); toast("Deleted"); },
    onError: (e) => toast(errMsg(e), "err"),
  });

  if (isLoading) return <PageLoader />;
  return (
    <div>
      <PageHeader title="Properties & units" actions={<Button onClick={() => setEditing("new")}>+ Add property</Button>} />
      <ErrorBox error={error} />
      {data?.length === 0 && (
        <Empty title="No properties yet">Add your first building or house, then its flats/rooms.</Empty>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.map((p) => (
          <Card key={p.id}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="font-semibold text-slate-900">{p.name}</h2>
                {p.address && <p className="text-sm text-slate-500">{p.address}</p>}
              </div>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>Edit</Button>
                <Button size="sm" variant="ghost" className="text-red-600"
                  onClick={() => confirm(`Delete ${p.name}?`) && del.mutate(`/api/properties/${p.id}`)}>Delete</Button>
              </div>
            </div>
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between">
                <p className="text-xs font-semibold uppercase text-slate-500">Units ({p.units.length})</p>
                <Button size="sm" variant="secondary" onClick={() => setUnitModal({ propertyId: p.id })}>+ Unit</Button>
              </div>
              <ul className="divide-y divide-slate-100">
                {p.units.map((u) => (
                  <li key={u.id} className="flex items-center justify-between py-2 text-sm">
                    <span>{u.name} <span className="text-slate-500">· {inr(u.default_rent)}</span></span>
                    <span className="flex gap-1">
                      <button className="text-xs text-brand-700 hover:underline" onClick={() => setUnitModal({ propertyId: p.id, unit: u })}>Edit</button>
                      <button className="ml-2 text-xs text-red-600 hover:underline"
                        onClick={() => confirm(`Delete ${u.name}?`) && del.mutate(`/api/properties/units/${u.id}`)}>Delete</button>
                    </span>
                  </li>
                ))}
                {p.units.length === 0 && <li className="py-2 text-sm text-slate-500">No units yet.</li>}
              </ul>
            </div>
          </Card>
        ))}
      </div>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Add property" : "Edit property"} wide>
        {editing !== null && <PropertyForm initial={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />}
      </Modal>
      <Modal open={unitModal !== null} onClose={() => setUnitModal(null)} title={unitModal?.unit ? "Edit unit" : "Add unit"}>
        {unitModal && <UnitForm propertyId={unitModal.propertyId} unit={unitModal.unit} onDone={() => setUnitModal(null)} />}
      </Modal>
    </div>
  );
}
