const jsonHeaders = { "Content-Type": "application/json" };

const transientStatuses = new Set([502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function readableError(status, payload) {
  if (transientStatuses.has(status)) {
    return "Backend API is still starting. Refresh in a few seconds.";
  }
  if (typeof payload === "object") return payload.detail || JSON.stringify(payload);
  if (typeof payload === "string" && payload.trim().startsWith("<html")) {
    return `Request failed: ${status}`;
  }
  return payload || `Request failed: ${status}`;
}

async function apiFetch(path, options = {}) {
  const retries = options.method ? 0 : 4;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const response = await fetch(path, options);
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (response.ok) return payload;
    if (transientStatuses.has(response.status) && attempt < retries) {
      await sleep(500 * (attempt + 1));
      continue;
    }
    throw new Error(readableError(response.status, payload));
  }
  throw new Error("Request failed.");
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
  wikiPage: (path) => apiFetch(`/api/wiki/page/${path.split("/").map(encodeURIComponent).join("/")}`),
  wikiLint: () => apiFetch("/api/wiki/lint"),
  wikiContract: (contractId) => apiFetch(`/api/wiki/contract/${contractId}`),
  wikiMilestone: (milestoneId) => apiFetch(`/api/wiki/milestone/${milestoneId}`),
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
