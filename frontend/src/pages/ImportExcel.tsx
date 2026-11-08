import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, download } from "../lib/api";
import { fmtDate, inr } from "../lib/format";
import { Button, Card, ErrorBox, PageHeader, Select, errMsg, useToast } from "../components/ui";

type Preview = {
  headers: string[];
  fields: Record<string, { label: string; required: boolean }>;
  mapping: Record<string, string | null>;
  rows: (Record<string, any> & { row: number; errors: string[]; id_masked: string | null })[];
  valid_count: number;
  error_count: number;
};

export default function ImportExcel() {
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const run = async (path: string, f: File, map?: Record<string, string | null>) => {
    const form = new FormData();
    form.append("file", f);
    if (map) form.append("mapping", JSON.stringify(map));
    return api<any>(path, { method: "POST", form });
  };

  const loadPreview = async (f: File, map?: Record<string, string | null>) => {
    setBusy(true);
    setErr(null);
    try {
      const p: Preview = await run("/api/excel/import/preview", f, map);
      setPreview(p);
      setMapping(p.mapping);
    } catch (e) {
      setErr(e);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await run("/api/excel/import/commit", file, mapping);
      toast(`Imported ${r.imported} tenants${r.skipped ? `, skipped ${r.skipped} rows with errors` : ""}`);
      qc.invalidateQueries();
      nav("/tenants");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Import tenants from Excel" subtitle="Upload your existing sheet. We'll match the columns, show a preview and import valid rows."
        actions={<Button variant="secondary" onClick={() => download("/api/excel/template", "tenant-import-template.xlsx").catch((e) => toast(errMsg(e), "err"))}>⬇ Blank template</Button>} />
      <Card className="mb-4">
        <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f) loadPreview(f); }}
          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:font-medium file:text-brand-700" />
        <p className="mt-2 text-xs text-slate-500">.xlsx only, up to 5 MB / 2000 rows. The first sheet is read; row 1 must be the column headers.</p>
      </Card>
      <ErrorBox error={err} />

      {preview && (
        <div className="space-y-4">
          <Card>
            <h2 className="mb-3 font-semibold text-slate-900">1. Match columns</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(preview.fields).map(([key, f]) => (
                <label key={key} className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">{f.label}{f.required && <span className="text-red-500"> *</span>}</span>
                  <Select value={mapping[key] ?? ""} onChange={(e) => setMapping({ ...mapping, [key]: e.target.value || null })}>
                    <option value="">— not in my sheet —</option>
                    {preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                  </Select>
                </label>
              ))}
            </div>
            <Button className="mt-3" variant="secondary" loading={busy} onClick={() => file && loadPreview(file, mapping)}>Re-check with this mapping</Button>
          </Card>

          <Card className="overflow-x-auto">
            <h2 className="mb-1 font-semibold text-slate-900">2. Preview</h2>
            <p className="mb-3 text-sm"><span className="text-emerald-700">{preview.valid_count} ready</span> · <span className="text-red-700">{preview.error_count} with errors (will be skipped)</span></p>
            <table className="w-full min-w-[720px] text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="py-1">Row</th><th>Name</th><th>Phone</th><th>Property / Unit</th><th>Rent</th><th>Start</th><th>ID</th><th>Status</th></tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 200).map((r) => (
                  <tr key={r.row} className={`border-t border-slate-100 ${r.errors.length ? "bg-red-50" : ""}`}>
                    <td className="py-1.5">{r.row}</td><td>{r.full_name}</td><td>{r.phone}</td>
                    <td>{r.property} / {r.unit}</td><td>{r.base_rent ? inr(r.base_rent) : ""}</td>
                    <td>{r.agreement_start_date ? fmtDate(r.agreement_start_date) : ""}</td><td>{r.id_masked ?? ""}</td>
                    <td className={r.errors.length ? "text-red-700" : "text-emerald-700"}>{r.errors.length ? r.errors.join("; ") : "OK"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Button className="w-full sm:w-auto" disabled={!preview.valid_count} loading={busy} onClick={commit}>
            Import {preview.valid_count} tenants
          </Button>
        </div>
      )}
    </div>
  );
}
