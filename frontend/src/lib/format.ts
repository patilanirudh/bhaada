const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** ₹ with Indian digit grouping: 150000 -> ₹1,50,000 */
export function inr(n: number | null | undefined): string {
  const v = Math.round(Number(n ?? 0));
  return (v < 0 ? "-₹" : "₹") + Math.abs(v).toLocaleString("en-IN");
}

function parse(d: string | Date): Date {
  if (d instanceof Date) return d;
  // Plain dates (YYYY-MM-DD) are calendar dates: don't shift them by timezone.
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
    const [y, m, day] = d.split("-").map(Number);
    return new Date(y, m - 1, day);
  }
  return new Date(d);
}

/** DD-MMM-YYYY, in Asia/Kolkata for timestamps. */
export function fmtDate(d: string | Date | null | undefined): string {
  if (!d) return "—";
  if (typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d)) {
    const x = parse(d);
    return `${String(x.getDate()).padStart(2, "0")}-${MONTHS[x.getMonth()]}-${x.getFullYear()}`;
  }
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).formatToParts(parse(d));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("day")}-${get("month")}-${get("year")}`;
}

/** "5 Nov" */
export function fmtShort(d: string | null | undefined): string {
  if (!d) return "—";
  const x = parse(d);
  return `${x.getDate()} ${MONTHS[x.getMonth()]}`;
}

/** "2026-11" -> "Nov 2026" */
export function monthLabel(m: string): string {
  const [y, mm] = m.split("-").map(Number);
  return `${MONTHS[mm - 1]} ${y}`;
}

export function todayISO(): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  return parts; // YYYY-MM-DD
}

export function addDaysISO(iso: string, days: number): string {
  const d = parse(iso);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addYearsISO(iso: string, years: number): string {
  const d = parse(iso);
  d.setFullYear(d.getFullYear() + years);
  d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function phoneDisplay(e164: string): string {
  if (e164.startsWith("+91") && e164.length === 13) return `+91 ${e164.slice(3, 8)} ${e164.slice(8)}`;
  return e164;
}
