import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { linksApi, propertiesApi } from "../api/endpoints";
import { fmtDate } from "../lib/format";
import type { Property, RegLink } from "../lib/types";
import { WaIcon } from "../components/WhatsApp";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Modal, PageHeader, PageLoader, Select, errMsg, useToast } from "../components/ui";

function CreateLink({ properties, onDone }: { properties: Property[]; onDone: (l: RegLink) => void }) {
  const qc = useQueryClient();
  const [propertyId, setPropertyId] = useState(properties[0]?.id ?? 0);
  const [unitId, setUnitId] = useState<string>("");
  const [days, setDays] = useState(7);
  const [uses, setUses] = useState(1);
  const prop = properties.find((p) => p.id === propertyId);
  const m = useMutation({
    mutationFn: () =>
      linksApi.create({ property_id: propertyId, unit_id: unitId ? Number(unitId) : null, expires_in_days: days, max_uses: uses }),
    onSuccess: (l) => { qc.invalidateQueries({ queryKey: ["links"] }); onDone(l); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-4">
      <ErrorBox error={m.error} />
      <Field label="Property" required>
        <Select value={propertyId} onChange={(e) => { setPropertyId(Number(e.target.value)); setUnitId(""); }}>
          {properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </Field>
      <Field label="Unit (optional)">
        <Select value={unitId} onChange={(e) => setUnitId(e.target.value)}>
          <option value="">Any unit — I'll choose when approving</option>
          {prop?.units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Valid for (days)"><Input type="number" min={1} max={90} value={days} onChange={(e) => setDays(Number(e.target.value))} /></Field>
        <Field label="Max uses"><Input type="number" min={1} max={100} value={uses} onChange={(e) => setUses(Number(e.target.value))} /></Field>
      </div>
      <Button type="submit" className="w-full" loading={m.isPending}>Create registration link</Button>
    </form>
  );
}

function LinkActions({ l }: { l: RegLink }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(l.url);
      toast("Link copied");
    } catch {
      prompt("Copy this link", l.url);
    }
  };
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onClick={copy}>Copy link</Button>
      <a href={l.whatsapp_url} target="_blank" rel="noopener noreferrer">
        <Button size="sm" variant="whatsapp"><WaIcon /> Share on WhatsApp</Button>
      </a>
    </div>
  );
}

export default function Links() {
  const qc = useQueryClient();
  const toast = useToast();
  const props = useQuery({ queryKey: ["properties"], queryFn: propertiesApi.list });
  const links = useQuery({ queryKey: ["links"], queryFn: linksApi.list });
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<RegLink | null>(null);
  const act = useMutation({
    mutationFn: ({ id, del }: { id: number; del?: boolean }) =>
      (del ? linksApi.remove(id) : linksApi.deactivate(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["links"] }),
    onError: (e) => toast(errMsg(e), "err"),
  });

  if (props.isLoading || links.isLoading) return <PageLoader />;
  const noProps = !props.data?.length;
  return (
    <div>
      <PageHeader
        title="Registration links"
        subtitle="Send a link; the tenant fills their details and uploads their ID. You approve."
        actions={<Button disabled={noProps} onClick={() => setOpen(true)}>+ Create registration link</Button>}
      />
      {noProps && <Empty title="Add a property first"><Link to="/properties" className="text-brand-700 underline">Go to properties</Link></Empty>}
      {!noProps && links.data?.length === 0 && <Empty title="No links yet">Create a link and share it on WhatsApp.</Empty>}
      <div className="space-y-3">
        {links.data?.map((l) => (
          <Card key={l.id} className={!l.usable ? "opacity-70" : ""}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-medium text-slate-900">{l.property_name}{l.unit_name ? ` · ${l.unit_name}` : ""}</p>
                <p className="text-xs text-slate-500">
                  Used {l.use_count}/{l.max_uses} · expires {fmtDate(l.expires_at)}
                </p>
                <p className="mt-1 truncate text-xs text-slate-400">{l.url}</p>
              </div>
              <Badge value={l.usable ? "ACTIVE" : !l.is_active ? "OFF" : "EXPIRED"} />
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              {l.usable ? <LinkActions l={l} /> : <span className="text-xs text-slate-500">{!l.is_active ? "Turned off" : l.use_count >= l.max_uses ? "All uses consumed" : "Expired"}</span>}
              <div className="flex gap-1">
                {l.is_active && l.usable && <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: l.id })}>Turn off</Button>}
                <Button size="sm" variant="ghost" className="text-red-600" onClick={() => confirm("Delete this link?") && act.mutate({ id: l.id, del: true })}>Delete</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Modal open={open} onClose={() => { setOpen(false); setCreated(null); }} title={created ? "Link ready" : "Create registration link"}>
        {created ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">Share this link with your tenant. It works {created.max_uses === 1 ? "once" : `${created.max_uses} times`} and expires on {fmtDate(created.expires_at)}.</p>
            <p className="break-all rounded-lg bg-slate-100 p-3 text-xs">{created.url}</p>
            <LinkActions l={created} />
          </div>
        ) : (
          props.data && <CreateLink properties={props.data} onDone={setCreated} />
        )}
      </Modal>
    </div>
  );
}
