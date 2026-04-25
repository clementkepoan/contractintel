const statusLabels = {
  ok: "OK",
  pending: "Pending",
  draft: "Draft",
  pending_acceptance: "Pending Acceptance",
  accepted: "Accepted",
  payment_requested: "Payment Requested",
  paid: "Paid",
  warning: "Warning",
  error: "Error",
};

export function StatusBadge({ status }) {
  const key = String(status || "pending").toLowerCase();
  const tone = key.includes("paid") || key.includes("accepted") || key === "ok" ? "success" : key.includes("warn") || key.includes("pending") ? "warning" : key.includes("error") || key.includes("fail") ? "danger" : "neutral";
  return <span className={`status-badge ${tone}`}>{statusLabels[key] || status || "Unknown"}</span>;
}
