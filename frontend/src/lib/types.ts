export type Owner = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  upi_id: string | null;
  gmail_address: string | null;
  gmail_configured: boolean;
  preferred_language: "en" | "hi";
  created_at: string;
  default_house_rules: string;
};

export type Unit = { id: number; property_id: number; name: string; default_rent: number };
export type Property = {
  id: number;
  name: string;
  address: string | null;
  house_rules: string | null;
  created_at: string;
  units: Unit[];
};

export type TenantStatus = "PENDING_APPROVAL" | "ACTIVE" | "VACATED" | "REJECTED";

export type Settlement = {
  vacate_date: string;
  deposit: number;
  pending_rent: number;
  pending_months: { month: string; label: string; amount: number }[];
  deductions: { label: string; amount: number }[];
  total_deductions: number;
  refund: number;
  notes: string | null;
};

export type Tenant = {
  id: number;
  full_name: string;
  phone: string;
  email: string | null;
  permanent_address: string | null;
  id_type: string | null;
  id_masked: string;
  has_id_document: boolean;
  has_photo: boolean;
  property_id: number | null;
  property_name: string | null;
  unit_id: number | null;
  unit_name: string | null;
  security_deposit: number;
  agreement_start_date: string | null;
  agreement_end_date: string | null;
  base_rent: number;
  current_rent: number;
  increment_percent: number;
  due_day: number;
  status: TenantStatus;
  consent_given_at: string | null;
  created_at: string;
  vacated_at: string | null;
  settlement: Settlement | null;
  has_settlement_pdf: boolean;
  last_reminded_on: string | null;
  pending_amount: number;
};

export type Payment = {
  id: number;
  rent_entry_id: number;
  amount: number;
  paid_on: string;
  mode: "UPI" | "CASH" | "BANK" | "OTHER";
  reference: string | null;
  receipt_number: string | null;
  has_receipt: boolean;
};

export type RentEntry = {
  id: number;
  tenant_id: number;
  tenant_name: string;
  unit_name: string | null;
  property_name: string | null;
  month: string;
  amount_due: number;
  amount_paid: number;
  status: "DUE" | "PARTIAL" | "PAID" | "OVERDUE";
  due_date: string;
  payments: Payment[];
};

export type RentHistory = {
  id: number;
  tenant_id: number;
  old_rent: number;
  new_rent: number;
  effective_from: string;
  reason: string;
};

export type ReminderLog = {
  id: number;
  tenant_id: number;
  type: string;
  channel: string;
  ref: string | null;
  sent_at: string;
  status: string;
  error: string | null;
};

export type RegLink = {
  id: number;
  property_id: number;
  unit_id: number | null;
  token: string;
  expires_at: string;
  max_uses: number;
  use_count: number;
  is_active: boolean;
  created_at: string;
  url: string;
  property_name: string;
  unit_name: string | null;
  whatsapp_url: string;
  usable: boolean;
};

export type WaItem = {
  tenant_id: number;
  tenant_name: string;
  phone: string;
  unit_name: string | null;
  property_name: string | null;
  text: string;
  link: string;
  type: string;
  ref: string | null;
  rent_entry_id?: number;
  month?: string;
  due_date?: string;
  balance?: number;
  last_whatsapp_on?: string | null;
  old_rent?: number;
  new_rent?: number;
  effective_date?: string;
};

export type Dashboard = {
  today: string;
  month: string;
  month_label: string;
  cards: {
    expected: number;
    collected: number;
    pending: number;
    overdue_count: number;
    overdue_amount: number;
    active_tenants: number;
  };
  actions: {
    due_today: WaItem[];
    overdue: WaItem[];
    pending_approvals: {
      tenant_id: number;
      tenant_name: string;
      phone: string;
      property_name: string | null;
      unit_name: string | null;
      created_at: string;
    }[];
    upcoming_increments: WaItem[];
    expiring_agreements: {
      tenant_id: number;
      tenant_name: string;
      unit_name: string | null;
      end_date: string;
      days_left: number;
    }[];
  };
  chart: { month: string; label: string; expected: number; collected: number }[];
  gmail_configured: boolean;
  upi_configured: boolean;
};
