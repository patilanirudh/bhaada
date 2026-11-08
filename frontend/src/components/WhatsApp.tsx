import { useMutation, useQueryClient } from "@tanstack/react-query";
import { remindersApi } from "../api/endpoints";
import type { WaItem } from "../lib/types";
import { Button, errMsg, useToast } from "./ui";

/** Opens wa.me (synchronously, so popup blockers allow it) and logs the tap in ReminderLog. */
export function useWhatsAppSend() {
  const qc = useQueryClient();
  const toast = useToast();
  const log = useMutation({
    mutationFn: (item: Pick<WaItem, "tenant_id" | "type" | "ref">) =>
      remindersApi.logWhatsApp(item),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["actions"] });
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["reminders"] });
    },
    onError: (e) => toast(errMsg(e), "err"),
  });
  return (item: Pick<WaItem, "tenant_id" | "type" | "ref" | "link">, logIt = true) => {
    window.open(item.link, "_blank", "noopener");
    if (logIt) log.mutate(item);
  };
}

export function WhatsAppButton({
  item,
  label = "Remind on WhatsApp",
  size = "sm",
}: {
  item: Pick<WaItem, "tenant_id" | "type" | "ref" | "link">;
  label?: string;
  size?: "sm" | "md";
}) {
  const send = useWhatsAppSend();
  return (
    <Button variant="whatsapp" size={size} onClick={() => send(item)}>
      <WaIcon /> {label}
    </Button>
  );
}

/** For a tenant: fetch the message for `kind`, then open it. */
export function TenantWhatsAppButton({
  tenantId,
  kind = "rent",
  label = "Remind on WhatsApp",
}: {
  tenantId: number;
  kind?: "rent" | "welcome" | "increment";
  label?: string;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const onClick = async () => {
    // Open the tab first (synchronously) so popup blockers allow it, then fill it in.
    const w = window.open("", "_blank");
    try {
      const item = await remindersApi.forTenant(tenantId, kind);
      if (w) w.location.href = item.link;
      await remindersApi.logWhatsApp(item);
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["reminders"] });
    } catch (e) {
      w?.close();
      toast(errMsg(e), "err");
    }
  };
  return (
    <Button variant="whatsapp" size="sm" onClick={onClick}>
      <WaIcon /> {label}
    </Button>
  );
}

export function WaIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden>
      <path d="M17.5 14.4c-.3-.1-1.7-.8-2-.9-.3-.1-.5-.1-.7.1-.2.3-.8.9-.9 1.1-.2.2-.3.2-.6.1-.3-.1-1.2-.5-2.3-1.4-.9-.8-1.4-1.7-1.6-2-.2-.3 0-.5.1-.6l.4-.5c.2-.2.2-.3.3-.5.1-.2 0-.4 0-.5l-.9-2.2c-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.5s1.1 2.9 1.2 3.1c.1.2 2.1 3.2 5.1 4.5.7.3 1.3.5 1.7.6.7.2 1.4.2 1.9.1.6-.1 1.7-.7 2-1.4.2-.7.2-1.2.2-1.4-.1-.1-.3-.2-.6-.3zM12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2c-1.5 0-3-.4-4.3-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2z" />
    </svg>
  );
}
