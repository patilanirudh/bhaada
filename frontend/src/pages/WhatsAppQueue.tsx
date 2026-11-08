import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { remindersApi } from "../api/endpoints";
import { fmtShort, inr } from "../lib/format";
import { WaIcon } from "../components/WhatsApp";
import { Button, Card, Empty, ErrorBox, PageHeader, PageLoader, errMsg, useToast } from "../components/ui";

type Result = "sent" | "skipped";

/** Step-by-step queue: open WhatsApp for tenant N, come back, confirm "Sent? ✓ / Skip", move on. */
export default function WhatsAppQueue() {
  const [params] = useSearchParams();
  const kind = params.get("kind") ?? "due";
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["wa-queue", kind],
    queryFn: () => remindersApi.queue(kind),
    staleTime: Infinity,
  });
  const [idx, setIdx] = useState(0);
  const [opened, setOpened] = useState(false);
  const [results, setResults] = useState<Record<number, Result>>({});
  const [saving, setSaving] = useState(false);

  // When the owner comes back from WhatsApp, the confirm buttons are already showing.
  useEffect(() => {
    const onVis = () => { if (document.visibilityState === "visible" && opened) window.scrollTo(0, 0); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [opened]);

  if (q.isLoading) return <PageLoader />;
  if (q.error) return <ErrorBox error={q.error} />;
  const items = q.data?.items ?? [];
  const title = kind === "increment" ? "Rent increase notices" : "Send all due reminders";
  if (!items.length) return (<div><PageHeader title={title} /><Empty title="Nobody to message right now">All caught up. <Link to="/" className="text-brand-700 underline">Back to dashboard</Link></Empty></div>);

  const done = idx >= items.length;
  const item = items[Math.min(idx, items.length - 1)];
  const sentCount = Object.values(results).filter((r) => r === "sent").length;

  const openWa = () => {
    window.open(item.link, "_blank", "noopener");
    setOpened(true);
  };
  const next = async (r: Result) => {
    if (r === "sent") {
      setSaving(true);
      try {
        await remindersApi.logWhatsApp(item);
      } catch (e) {
        toast(errMsg(e), "err");
      } finally {
        setSaving(false);
      }
    }
    setResults({ ...results, [item.tenant_id]: r });
    setOpened(false);
    setIdx(idx + 1);
    if (idx + 1 >= items.length) {
      qc.invalidateQueries({ queryKey: ["actions"] });
      qc.invalidateQueries({ queryKey: ["tenants"] });
    }
  };

  return (
    <div className="mx-auto max-w-lg">
      <PageHeader title={title} subtitle={done ? "Finished" : `Tenant ${idx + 1} of ${items.length}`} />
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full bg-[#25D366] transition-all" style={{ width: `${(Math.min(idx, items.length) / items.length) * 100}%` }} />
      </div>

      {done ? (
        <Card className="text-center">
          <p className="text-4xl">✅</p>
          <p className="mt-2 font-semibold text-slate-900">Done! {sentCount} sent, {items.length - sentCount} skipped.</p>
          <Link to="/"><Button className="mt-4">Back to dashboard</Button></Link>
        </Card>
      ) : (
        <Card>
          <p className="text-lg font-semibold text-slate-900">{item.tenant_name}</p>
          <p className="text-sm text-slate-500">
            {item.unit_name}{item.balance ? ` · ${inr(item.balance)}` : ""}
            {item.last_whatsapp_on && <span className="text-emerald-700"> · Reminded on {fmtShort(item.last_whatsapp_on)}</span>}
          </p>
          <div className="mt-3 whitespace-pre-wrap rounded-xl bg-[#e7fbe9] p-3 text-sm text-slate-800">{item.text}</div>
          {!opened ? (
            <div className="mt-4 flex gap-2">
              <Button variant="whatsapp" className="flex-1" onClick={openWa}><WaIcon /> Open WhatsApp</Button>
              <Button variant="secondary" onClick={() => next("skipped")}>Skip</Button>
            </div>
          ) : (
            <div className="mt-4">
              <p className="mb-2 text-center text-sm font-medium text-slate-700">Did you send the message?</p>
              <div className="flex gap-2">
                <Button className="flex-1" loading={saving} onClick={() => next("sent")}>Sent ✓</Button>
                <Button variant="secondary" className="flex-1" onClick={() => next("skipped")}>Skip</Button>
              </div>
              <button className="mt-2 w-full text-center text-xs text-brand-700 underline" onClick={openWa}>Open WhatsApp again</button>
            </div>
          )}
        </Card>
      )}

      <ul className="mt-4 space-y-1 text-sm">
        {items.map((it, i) => (
          <li key={it.tenant_id} className={`flex justify-between rounded-lg px-3 py-2 ${i === idx ? "bg-white ring-1 ring-slate-200" : ""}`}>
            <span className={i < idx ? "text-slate-500" : "text-slate-800"}>{it.tenant_name}</span>
            <span className="text-xs">{results[it.tenant_id] === "sent" ? "✓ Sent" : results[it.tenant_id] === "skipped" ? "Skipped" : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
