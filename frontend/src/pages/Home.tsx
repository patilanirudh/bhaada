import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { dashboardApi, qk } from "../api/endpoints";
import { fmtDate, fmtShort, inr } from "../lib/format";
import type { WaItem } from "../lib/types";
import { Button, Card, ErrorBox, PageHeader, PageLoader } from "../components/ui";
import { WhatsAppButton } from "../components/WhatsApp";

function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  if (!count) return null;
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-700">
        {title} <span className="ml-1 rounded-full bg-slate-200 px-2 py-0.5 text-xs">{count}</span>
      </h3>
      <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">{children}</ul>
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <li className="flex flex-wrap items-center justify-between gap-2 px-3 py-3">{children}</li>;
}

function RentRow({ it, overdue }: { it: WaItem; overdue?: boolean }) {
  return (
    <Row>
      <div className="min-w-0">
        <Link to={`/tenants/${it.tenant_id}`} className="font-medium text-slate-900 hover:underline">{it.tenant_name}</Link>
        <p className="text-xs text-slate-500">
          {it.unit_name} · {inr(it.balance)} · {overdue ? `was due ${fmtShort(it.due_date)}` : "due today"}
          {it.last_whatsapp_on && <span className="ml-1 text-emerald-700">· Reminded on {fmtShort(it.last_whatsapp_on)}</span>}
        </p>
      </div>
      <div className="flex gap-2">
        <Link to={`/tenants/${it.tenant_id}#ledger`}><Button size="sm" variant="secondary">Mark paid</Button></Link>
        <WhatsAppButton item={it} label="Remind" />
      </div>
    </Row>
  );
}

/** Home: today's to-do list. Money overview lives on the separate Dashboard page. */
export default function Home() {
  const { data, isLoading, error } = useQuery({ queryKey: qk.actions, queryFn: dashboardApi.actions });
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorBox error={error} />;
  const count =
    data.due_today.length + data.overdue.length + data.pending_approvals.length +
    data.upcoming_increments.length + data.expiring_agreements.length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Action today"
        subtitle={fmtDate(data.today)}
        actions={(data.due_today.length + data.overdue.length > 0) && (
          <Link to="/whatsapp-queue?kind=due"><Button variant="whatsapp" size="sm">Send all due reminders</Button></Link>
        )}
      />

      {(!data.gmail_configured || !data.upi_configured) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Finish setup:{" "}
          {!data.upi_configured && <span>add your <b>UPI ID</b> </span>}
          {!data.upi_configured && !data.gmail_configured && "and "}
          {!data.gmail_configured && <span>connect your own <b>Gmail</b> </span>}
          — <Link to="/settings" className="font-medium underline">Open settings</Link>
        </div>
      )}

      {count === 0 ? (
        <Card className="text-center text-sm text-slate-500">🎉 Nothing needs your attention today.</Card>
      ) : (
        <div className="space-y-4">
          <Section title="Pending approvals" count={data.pending_approvals.length}>
            {data.pending_approvals.map((p) => (
              <Row key={p.tenant_id}>
                <div>
                  <p className="font-medium text-slate-900">{p.tenant_name}</p>
                  <p className="text-xs text-slate-500">{p.property_name}{p.unit_name ? ` · ${p.unit_name}` : ""} · registered {fmtDate(p.created_at)}</p>
                </div>
                <Link to={`/tenants/${p.tenant_id}`}><Button size="sm">Review</Button></Link>
              </Row>
            ))}
          </Section>
          <Section title="Due today" count={data.due_today.length}>
            {data.due_today.map((it) => <RentRow key={it.tenant_id} it={it} />)}
          </Section>
          <Section title="Overdue" count={data.overdue.length}>
            {data.overdue.map((it) => <RentRow key={it.tenant_id} it={it} overdue />)}
          </Section>
          <Section title="Rent increase in next 30 days" count={data.upcoming_increments.length}>
            {data.upcoming_increments.map((it) => (
              <Row key={it.tenant_id}>
                <div>
                  <Link to={`/tenants/${it.tenant_id}`} className="font-medium text-slate-900 hover:underline">{it.tenant_name}</Link>
                  <p className="text-xs text-slate-500">{inr(it.old_rent)} → <b>{inr(it.new_rent)}</b> from {fmtDate(it.effective_date)}</p>
                </div>
                <WhatsAppButton item={it} label="Send notice" />
              </Row>
            ))}
          </Section>
          <Section title="Agreements ending soon" count={data.expiring_agreements.length}>
            {data.expiring_agreements.map((a) => (
              <Row key={a.tenant_id}>
                <div>
                  <p className="font-medium text-slate-900">{a.tenant_name}</p>
                  <p className={`text-xs ${a.days_left < 0 ? "text-red-600" : "text-slate-500"}`}>
                    {a.unit_name} · ends {fmtDate(a.end_date)} ({a.days_left < 0 ? `${-a.days_left} days ago` : `${a.days_left} days left`})
                  </p>
                </div>
                <Link to={`/tenants/${a.tenant_id}?renew=1`}><Button size="sm" variant="secondary">Renew</Button></Link>
              </Row>
            ))}
          </Section>
        </div>
      )}
      <Link to="/dashboard" className="block text-center text-sm font-medium text-brand-700 hover:underline">
        View money dashboard →
      </Link>
    </div>
  );
}
