import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dashboardApi, qk } from "../api/endpoints";
import { fmtDate, inr } from "../lib/format";
import { Card, ErrorBox, PageHeader, PageLoader } from "../components/ui";

// Categorical slots 1 & 2 (validated: CVD ΔE 24.7, normal ΔE 33.6, contrast ≥ 3:1 on white).
const C_COLLECTED = "#2a78d6";
const C_EXPECTED = "#eb6834";

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "red" }) {
  return (
    <Card className="p-3 sm:p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-xl font-bold sm:text-2xl ${tone === "red" ? "text-red-700" : "text-slate-900"}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </Card>
  );
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const exp = payload.find((p: any) => p.dataKey === "expected")?.value ?? 0;
  const col = payload.find((p: any) => p.dataKey === "collected")?.value ?? 0;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-slate-900">{label}</p>
      <p className="flex items-center gap-2 text-slate-700"><span className="h-2 w-2 rounded-sm" style={{ background: C_EXPECTED }} />Expected <b className="ml-auto pl-3">{inr(exp)}</b></p>
      <p className="flex items-center gap-2 text-slate-700"><span className="h-2 w-2 rounded-sm" style={{ background: C_COLLECTED }} />Collected <b className="ml-auto pl-3">{inr(col)}</b></p>
      {exp > 0 && <p className="mt-1 text-slate-500">{Math.round((col / exp) * 100)}% collected</p>}
    </div>
  );
}

const compact = (v: number) =>
  v >= 100000 ? `₹${(v / 100000).toFixed(v % 100000 ? 1 : 0)}L` : v >= 1000 ? `₹${Math.round(v / 1000)}k` : `₹${v}`;
const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");

/** Dashboard: money overview only (the to-do list is on Home). */
export default function Dashboard() {
  const { data, isLoading, error } = useQuery({ queryKey: qk.summary, queryFn: dashboardApi.summary });
  const [table, setTable] = useState(false);
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorBox error={error} />;
  const c = data.cards;

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" subtitle={`${data.month_label} · as of ${fmtDate(data.today)}`} />

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">This month</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Expected" value={inr(c.expected)} sub={`${c.active_tenants} active tenants`} />
          <Stat label="Collected" value={inr(c.collected)} sub={`${pct(c.collected, c.expected)} of this month`} />
          <Stat label="Pending" value={inr(c.pending)} sub="this month" />
          <Stat label="Overdue" value={inr(c.overdue_amount)} sub={`${c.overdue_count} unpaid months`} tone={c.overdue_count ? "red" : undefined} />
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Last 12 months</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          <Stat label="Collected" value={inr(c.collected_12m)} sub={`of ${inr(c.expected_12m)} expected`} />
          <Stat label="Collection rate" value={pct(c.collected_12m, c.expected_12m)} />
          <Stat label="Deposits held" value={inr(c.deposits_held)} sub="active tenants" />
        </div>
      </div>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">Collected vs expected · last 12 months</h2>
          <button className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setTable(!table)}>
            {table ? "Show chart" : "View as table"}
          </button>
        </div>
        {table ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Month</th><th className="text-right">Expected</th><th className="text-right">Collected</th><th className="text-right">Pending</th></tr></thead>
              <tbody>
                {data.chart.map((r) => (
                  <tr key={r.month} className="border-t border-slate-100">
                    <td className="py-1.5">{r.label}</td><td className="text-right">{inr(r.expected)}</td>
                    <td className="text-right">{inr(r.collected)}</td><td className="text-right">{inr(r.expected - r.collected)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer>
              <BarChart data={data.chart} barGap={2} margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#eef2f6" />
                <XAxis dataKey="label" tickFormatter={(l: string) => l.slice(0, 3)} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={compact} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} width={52} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "#f1f5f9" }} />
                <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12, color: "#475569" }} />
                <Bar dataKey="expected" name="Expected" fill={C_EXPECTED} radius={[4, 4, 0, 0]} maxBarSize={18} />
                <Bar dataKey="collected" name="Collected" fill={C_COLLECTED} radius={[4, 4, 0, 0]} maxBarSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </div>
  );
}
