// Typed API layer: the only place in the frontend that knows backend URLs.
// Pages and components call these functions (usually through TanStack Query).
import { api } from "./client";
import type {
  ActionsData,
  Owner,
  Payment,
  Property,
  RegLink,
  ReminderLog,
  RentEntry,
  RentHistory,
  Settlement,
  SummaryData,
  Tenant,
  WaItem,
} from "../lib/types";

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export type PaymentRow = Payment & {
  month: string;
  tenant_id: number;
  tenant_name: string;
  unit_name: string | null;
  property_name: string | null;
};
export type Template = { kind: string; language: string; body: string; is_custom: boolean };
export type PublicLinkInfo = {
  property_name: string;
  property_address: string | null;
  unit_name: string | null;
  house_rules: string | null;
  owner_name: string;
  expires_at: string;
};

export const authApi = {
  login: (email: string, password: string) =>
    api<{ access_token: string }>("/api/auth/login", { method: "POST", body: { email, password }, auth: false }),
  register: (data: { name: string; email: string; password: string; phone?: string }) =>
    api<{ access_token: string }>("/api/auth/register", { method: "POST", body: data, auth: false }),
  logout: () => api("/api/auth/logout", { method: "POST", auth: false }),
  me: () => api<Owner>("/api/auth/me"),
  forgotPassword: (email: string) =>
    api<{ detail: string }>("/api/auth/forgot-password", { method: "POST", body: { email }, auth: false }),
  resetPassword: (token: string | null, password: string) =>
    api("/api/auth/reset-password", { method: "POST", body: { token, password }, auth: false }),
  changePassword: (current_password: string, new_password: string) =>
    api("/api/auth/change-password", { method: "POST", body: { current_password, new_password } }),
};

export const settingsApi = {
  updateProfile: (body: Partial<Pick<Owner, "name" | "phone" | "upi_id" | "preferred_language">>) =>
    api<Owner>("/api/settings/profile", { method: "PUT", body }),
  saveGmail: (gmail_address: string, app_password: string) =>
    api<Owner>("/api/settings/gmail", { method: "PUT", body: { gmail_address, app_password } }),
  removeGmail: () => api<Owner>("/api/settings/gmail", { method: "DELETE" }),
  testEmail: () => api<{ detail: string }>("/api/settings/gmail/test", { method: "POST" }),
  saveHouseRules: (house_rules: string, apply_to_all_properties: boolean) =>
    api<Owner>("/api/settings/house-rules", { method: "PUT", body: { house_rules, apply_to_all_properties } }),
  templates: () =>
    api<{ kinds: Record<string, string>; placeholders: string[]; templates: Template[] }>("/api/settings/templates"),
  saveTemplate: (kind: string, language: string, body: string) =>
    api("/api/settings/templates", { method: "PUT", body: { kind, language, body } }),
  resetTemplate: (kind: string, language: string) =>
    api(`/api/settings/templates/${kind}/${language}`, { method: "DELETE" }),
};

export const propertiesApi = {
  list: () => api<Property[]>("/api/properties"),
  save: (id: number | undefined, body: { name: string; address: string; house_rules: string }) =>
    api<Property>(id ? `/api/properties/${id}` : "/api/properties", { method: id ? "PUT" : "POST", body }),
  remove: (id: number) => api(`/api/properties/${id}`, { method: "DELETE" }),
  saveUnit: (propertyId: number, unitId: number | undefined, body: { name: string; default_rent: number }) =>
    api<{ id: number }>(unitId ? `/api/properties/units/${unitId}` : `/api/properties/${propertyId}/units`, {
      method: unitId ? "PUT" : "POST",
      body,
    }),
  removeUnit: (unitId: number) => api(`/api/properties/units/${unitId}`, { method: "DELETE" }),
};

export const linksApi = {
  list: () => api<RegLink[]>("/api/links"),
  create: (body: { property_id: number; unit_id: number | null; expires_in_days: number; max_uses: number }) =>
    api<RegLink>("/api/links", { method: "POST", body }),
  deactivate: (id: number) => api(`/api/links/${id}/deactivate`, { method: "POST" }),
  remove: (id: number) => api(`/api/links/${id}`, { method: "DELETE" }),
};

export const tenantsApi = {
  list: (filters: { status?: string; property_id?: string; q?: string }) =>
    api<Tenant[]>(`/api/tenants${qs(filters)}`),
  get: (id: number) => api<Tenant>(`/api/tenants/${id}`),
  create: (body: Record<string, unknown>) => api<Tenant>("/api/tenants", { method: "POST", body }),
  update: (id: number, body: Record<string, unknown>) => api<Tenant>(`/api/tenants/${id}`, { method: "PATCH", body }),
  approve: (id: number, body: Record<string, unknown>) =>
    api<Tenant>(`/api/tenants/${id}/approve`, { method: "POST", body }),
  reject: (id: number) => api<Tenant>(`/api/tenants/${id}/reject`, { method: "POST" }),
  changeRent: (id: number, new_rent: number) =>
    api<Tenant>(`/api/tenants/${id}/rent-change`, { method: "POST", body: { new_rent } }),
  renew: (id: number, new_end_date: string) =>
    api<Tenant>(`/api/tenants/${id}/renew`, { method: "POST", body: { new_end_date } }),
  settlementPreview: (id: number, body: unknown) =>
    api<Settlement>(`/api/tenants/${id}/settlement-preview`, { method: "POST", body }),
  vacate: (id: number, body: unknown) => api<Tenant>(`/api/tenants/${id}/vacate`, { method: "POST", body }),
  deleteDocuments: (id: number) => api<Tenant>(`/api/tenants/${id}/documents`, { method: "DELETE" }),
  erase: (id: number) => api<Tenant>(`/api/tenants/${id}/erase`, { method: "POST" }),
  ledger: (id: number) => api<RentEntry[]>(`/api/tenants/${id}/ledger`),
  history: (id: number) => api<RentHistory[]>(`/api/tenants/${id}/rent-history`),
  reminders: (id: number) => api<ReminderLog[]>(`/api/tenants/${id}/reminders`),
  // Paths for short-lived signed file URLs (opened with openSigned)
  documentUrlPath: (id: number) => `/api/tenants/${id}/document-url`,
  photoUrlPath: (id: number) => `/api/tenants/${id}/photo-url`,
  settlementUrlPath: (id: number) => `/api/tenants/${id}/settlement-url`,
};

export const rentApi = {
  entries: (filters: { month?: string; status?: string }) => api<RentEntry[]>(`/api/rent/entries${qs(filters)}`),
  generate: () => api<{ created: number }>("/api/rent/generate", { method: "POST" }),
  pay: (entryId: number, body: { amount: number; paid_on: string; mode: string; reference: string | null; send_receipt: boolean }) =>
    api<RentEntry>(`/api/rent/entries/${entryId}/payments`, { method: "POST", body }),
  deletePayment: (paymentId: number) => api<RentEntry>(`/api/rent/payments/${paymentId}`, { method: "DELETE" }),
  payments: (limit = 300) => api<PaymentRow[]>(`/api/rent/payments${qs({ limit })}`),
  receiptUrlPath: (paymentId: number) => `/api/rent/payments/${paymentId}/receipt-url`,
};

export const remindersApi = {
  queue: (kind: string) => api<{ items: WaItem[] }>(`/api/reminders/whatsapp/queue${qs({ kind })}`),
  forTenant: (tenantId: number, kind: string) => api<WaItem>(`/api/reminders/whatsapp/tenant/${tenantId}${qs({ kind })}`),
  logWhatsApp: (item: Pick<WaItem, "tenant_id" | "type" | "ref">) =>
    api("/api/reminders/whatsapp/log", {
      method: "POST",
      body: { tenant_id: item.tenant_id, type: item.type, ref: item.ref },
    }),
};

export const dashboardApi = {
  summary: () => api<SummaryData>("/api/dashboard/summary"),
  actions: () => api<ActionsData>("/api/dashboard/actions"),
};

export const excelApi = {
  exportPath: "/api/excel/export",
  templatePath: "/api/excel/template",
  latestPath: "/api/excel/latest",
  preview: (form: FormData) => api<any>("/api/excel/import/preview", { method: "POST", form }),
  commit: (form: FormData) => api<{ imported: number; skipped: number }>("/api/excel/import/commit", { method: "POST", form }),
};

export const publicApi = {
  linkInfo: (token: string) => api<PublicLinkInfo>(`/api/public/register/${token}`, { auth: false }),
  register: (token: string, form: FormData) =>
    api(`/api/public/register/${token}`, { method: "POST", form, auth: false }),
};

/** Central TanStack Query keys (invalidate by prefix). */
export const qk = {
  me: ["me"] as const,
  summary: ["summary"] as const,
  actions: ["actions"] as const,
  properties: ["properties"] as const,
  links: ["links"] as const,
  tenants: ["tenants"] as const,
  tenant: (id: number) => ["tenant", id] as const,
  ledger: (id: number) => ["ledger", id] as const,
  history: (id: number) => ["history", id] as const,
  reminders: (id: number) => ["reminders", id] as const,
  entries: ["entries"] as const,
  payments: ["payments"] as const,
  templates: ["templates"] as const,
};
