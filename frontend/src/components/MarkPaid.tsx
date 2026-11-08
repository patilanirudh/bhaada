import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { openSigned } from "../api/client";
import { rentApi } from "../api/endpoints";
import { inr, monthLabel, todayISO } from "../lib/format";
import type { RentEntry } from "../lib/types";
import { Button, ErrorBox, Field, Input, Modal, Select, useToast } from "./ui";

export function MarkPaidModal({ entry, onClose }: { entry: RentEntry | null; onClose: () => void }) {
  return (
    <Modal open={!!entry} onClose={onClose} title="Mark as paid">
      {entry && <MarkPaidForm entry={entry} onDone={onClose} />}
    </Modal>
  );
}

function MarkPaidForm({ entry, onDone }: { entry: RentEntry; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const balance = entry.amount_due - entry.amount_paid;
  const [amount, setAmount] = useState(String(balance));
  const [paidOn, setPaidOn] = useState(todayISO());
  const [mode, setMode] = useState("UPI");
  const [reference, setReference] = useState("");
  const [sendReceipt, setSendReceipt] = useState(true);
  const m = useMutation({
    mutationFn: () =>
      rentApi.pay(entry.id, { amount: Number(amount), paid_on: paidOn, mode, reference: reference || null, send_receipt: sendReceipt }),
    onSuccess: (e) => {
      ["actions", "summary", "entries", "ledger", "tenants", "payments", "tenant"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast(e.status === "PAID" ? "Marked as paid. Receipt generated." : "Partial payment saved. Receipt generated.");
      onDone();
    },
  });
  const n = Number(amount);
  const invalid = !n || n <= 0 || n > balance;
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (!invalid) m.mutate(); }} className="space-y-4">
      <div className="rounded-lg bg-slate-50 p-3 text-sm">
        <p className="font-medium text-slate-900">{entry.tenant_name} · {monthLabel(entry.month)}</p>
        <p className="text-slate-600">Rent {inr(entry.amount_due)} · paid {inr(entry.amount_paid)} · <b>balance {inr(balance)}</b></p>
      </div>
      <ErrorBox error={m.error} />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount (₹)" required error={n > balance ? `Max ${inr(balance)}` : undefined}>
          <Input type="number" min={1} max={balance} inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label="Paid on" required>
          <Input type="date" max={todayISO()} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </Field>
      </div>
      <div className="flex gap-2">
        <button type="button" className="text-xs text-brand-700 underline" onClick={() => setAmount(String(balance))}>Full {inr(balance)}</button>
      </div>
      <Field label="Mode" required>
        <Select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="UPI">UPI</option><option value="CASH">Cash</option><option value="BANK">Bank transfer</option><option value="OTHER">Other</option>
        </Select>
      </Field>
      <Field label="Reference (UTR / cheque no.)">
        <Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={120} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={sendReceipt} onChange={(e) => setSendReceipt(e.target.checked)} />
        Email the PDF receipt to the tenant
      </label>
      <Button type="submit" className="w-full" disabled={invalid} loading={m.isPending}>
        Save payment {n > 0 && n < balance ? "(partial)" : ""}
      </Button>
    </form>
  );
}

export function ReceiptLink({ paymentId }: { paymentId: number }) {
  const toast = useToast();
  return (
    <button
      className="text-xs font-medium text-brand-700 hover:underline"
      onClick={() => openSigned(rentApi.receiptUrlPath(paymentId)).catch((e) => toast(e.message, "err"))}
    >
      Receipt
    </button>
  );
}
