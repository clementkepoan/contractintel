const jsonHeaders = { "Content-Type": "application/json" };

async function apiFetch(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail || JSON.stringify(payload) : payload;
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return payload;
}

export const api = {
  health: () => apiFetch("/api/health"),
  contracts: () => apiFetch("/api/contracts"),
  contract: (contractId) => apiFetch(`/api/contracts/${contractId}`),
  financials: (contractId) => apiFetch(`/api/contracts/${contractId}/financials`),
  rawContract: (contractId) => apiFetch(`/api/contracts/${contractId}/raw`),
  milestone: (milestoneId) => apiFetch(`/api/milestones/${milestoneId}`),
  milestoneStatus: (milestoneId) => apiFetch(`/api/milestones/${milestoneId}/status`),
  workflow: (milestoneId) => apiFetch(`/api/workflow/${milestoneId}`),
  wikiIndex: () => apiFetch("/api/wiki"),
  wikiPage: (path) => apiFetch(`/api/wiki/${path.split("/").map(encodeURIComponent).join("/")}`),
  graph: () => apiFetch("/api/kg/graph"),
  graphSvg: (contractId) => apiFetch(contractId ? `/api/kg/svg/${contractId}` : "/api/kg/svg"),
  graphAcceptedNotPaid: () => apiFetch("/api/kg/query/accepted-not-paid"),
  graphHighRiskClauses: () => apiFetch("/api/kg/query/high-risk-clauses"),
  graphPaymentTrail: (milestoneId) => apiFetch(`/api/kg/query/payment-trail/${milestoneId}`),
  chatSessions: () => apiFetch("/api/chat/sessions"),
  chatMessages: (chatSessionId) => apiFetch(`/api/chat/sessions/${chatSessionId}/messages`),
  query: (payload) => apiFetch("/api/query", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  accept: (payload) => apiFetch("/api/acceptance", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  requestPayment: (payload) => apiFetch("/api/payment-request", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  logPayment: (payload) => apiFetch("/api/payment", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/ingest", { method: "POST", body: form });
  },
};

export function formatMoney(value, currency = "TWD") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Not extracted";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value));
}

export function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
