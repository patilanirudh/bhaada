import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download, openSigned } from "../lib/api";
import { fmtDate, inr, monthLabel, todayISO } from "../lib/format";
import type { Payment, RentEntry } from "../lib/types";
import { MarkPaidModal, ReceiptLink } from "../components/MarkPaid";
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, PageLoader, Select, errMsg, useToast } from "../components/ui";

type PaymentRow = Payment & { month: string; tenant_id: number; tenant_name: string; unit_name: string | null; property_name: string | null };

function monthsBack(n: number): string[] {
  const t = todayISO();
  let y = Number(t.slice(0, 4));
  let m = Number(t.slice(5, 7)) + 1; // include next month (pre-generated entries)
  if (m === 13) { m = 1; y++; }
  const out: string[] = [];
  for (let i = 0; i < n; i++) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m--;
    if (m === 0) { m = 12; y--; }
  }
  return out;
}

export default function Payments() {
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"ledger" | "history">("ledger");
  const [month, setMonth] = useState(todayISO().slice(0, 7));
  const [status, setStatus] = useState("");
  const [paying, setPaying] = useState<RentEntry | null>(null);
  const qs = new URLSearchParams({ month });
  if (status) qs.set("status", status);
  const entries = useQuery({ queryKey: ["entries", month, status], queryFn: () => api<RentEntry[]>(`/api/rent/entries?${qs}`), enabled: tab === "ledger" });
  const history = useQuery({ queryKey: ["payments"], queryFn: () => api<PaymentRow[]>("/api/rent/payments?limit=300"), enabled: tab === "history" });
  const gen = useMutation({
    mutationFn: () => api<{ created: number }>("/api/rent/generate", { method: "POST" }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["entries"] }); toast(r.created ? `${r.created} rent entries created` : "Ledger is up to date"); },
  });
  const [dl, setDl] = useState(false);
  const exportXlsx = async () => {
    setDl(true);
    try { await download("/api/excel/export", "rent-data.xlsx"); } catch (e) { toast(errMsg(e), "err"); } finally { setDl(false); }
  };

  const total = entries.data?.reduce((a, e) => ({ due: a.due + e.amount_due, paid: a.paid + e.amount_paid }), { due: 0, paid: 0 });

  return (
    <div>
      <PageHeader title="Payments" actions={<>
        <Button variant="secondary" loading={dl} onClick={exportXlsx}>⬇ Download Excel</Button>
        <Button variant="ghost" onClick={() => openSigned("/api/excel/latest").catch((e) => toast(errMsg(e), "err"))}>Saved copy</Button>
        <Link to="/import"><Button variant="ghost">Import</Button></Link>
      </>} />
      <div className="mb-4 flex gap-1 rounded-lg bg-slate-200 p-1 text-sm">
        {(["ledger", "history"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`flex-1 rounded-md py-1.5 font-medium ${tab === t ? "bg-white shadow-sm" : "text-slate-600"}`}>
            {t === "ledger" ? "Monthly ledger" : "Payment history"}
          </button>
        ))}
      </div>

      {tab === "ledger" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Select className="!w-auto" value={month} onChange={(e) => setMonth(e.target.value)}>
              {monthsBack(13).map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
            </Select>
            <Select className="!w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option><option value="DUE">Due</option><option value="PARTIAL">Partial</option>
              <option value="OVERDUE">Overdue</option><option value="PAID">Paid</option>
            </Select>
            <Button variant="ghost" size="sm" loading={gen.isPending} onClick={() => gen.mutate()}>Refresh ledger</Button>
          </div>
          {total && entries.data!.length > 0 && (
            <p className="mb-3 text-sm text-slate-600">Collected <b>{inr(total.paid)}</b> of {inr(total.due)} · pending <b className="text-red-700">{inr(total.due - total.paid)}</b></p>
          )}
          {entries.isLoading ? <PageLoader /> : <ErrorBox error={entries.error} />}
          {entries.data?.length === 0 && <Empty title="No rent entries for this month">Entries are created automatically each month for active tenants.</Empty>}
          <div className="space-y-2">
            {entries.data?.map((e) => (
              <Card key={e.id} className="p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <Link to={`/tenants/${e.tenant_id}`} className="font-medium text-slate-900 hover:underline">{e.tenant_name}</Link>
                    <p className="text-xs text-slate-500">{e.property_name} · {e.unit_name} · due {fmtDate(e.due_date)}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-right text-sm">
                      <p className="font-semibold">{inr(e.amount_due)}</p>
                      {e.amount_paid > 0 && e.status !== "PAID" && <p className="text-xs text-slate-500">paid {inr(e.amount_paid)}</p>}
                    </div>
                    <Badge value={e.status} />
                  </div>
                </div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <div className="flex gap-3">{e.payments.filter((p) => p.has_receipt).map((p) => <ReceiptLink key={p.id} paymentId={p.id} />)}</div>
                  {e.status !== "PAID" && <Button size="sm" onClick={() => setPaying(e)}>Mark as paid</Button>}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {tab === "history" && (
        <>
          {history.isLoading ? <PageLoader /> : <ErrorBox error={history.error} />}
          {history.data?.length === 0 && <Empty title="No payments recorded yet" />}
          <Card className="overflow-x-auto p-0">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-3 py-2">Date</th><th className="px-3">Tenant</th><th className="px-3">Month</th><th className="px-3 text-right">Amount</th><th className="px-3">Mode</th><th className="px-3"></th></tr>
              </thead>
              <tbody>
                {history.data?.map((p) => (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="px-3 py-2">{fmtDate(p.paid_on)}</td>
                    <td className="px-3"><Link to={`/tenants/${p.tenant_id}`} className="hover:underline">{p.tenant_name}</Link><span className="block text-xs text-slate-500">{p.unit_name}</span></td>
                    <td className="px-3">{monthLabel(p.month)}</td>
                    <td className="px-3 text-right font-medium">{inr(p.amount)}</td>
                    <td className="px-3">{p.mode}{p.reference && <span className="block text-xs text-slate-500">{p.reference}</span>}</td>
                    <td className="px-3">{p.has_receipt && <ReceiptLink paymentId={p.id} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
      <MarkPaidModal entry={paying} onClose={() => setPaying(null)} />
    </div>
  );
}
