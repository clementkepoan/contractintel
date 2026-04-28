import { useI18n } from "../i18n.jsx";

const statusLabels = {
  ok: "status.ok",
  pending: "status.pending",
  draft: "status.draft",
  queued: "status.queued",
  processing: "status.processing",
  running: "status.running",
  completed: "status.completed",
  completed_with_errors: "status.completed_with_errors",
  pending_acceptance: "status.pending_acceptance",
  accepted: "status.accepted",
  payment_requested: "status.payment_requested",
  paid: "status.paid",
  warning: "status.warning",
  error: "status.error",
};

export function StatusBadge({ status }) {
  const { t } = useI18n();
  const key = String(status || "pending").toLowerCase();
  const tone = key.includes("paid") || key.includes("accepted") || key === "ok" ? "success" : key.includes("warn") || key.includes("pending") ? "warning" : key.includes("error") || key.includes("fail") ? "danger" : "neutral";
  return <span className={`status-badge ${tone}`}>{statusLabels[key] ? t(statusLabels[key]) : status || t("status.unknown")}</span>;
}
