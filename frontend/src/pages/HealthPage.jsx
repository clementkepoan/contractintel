import { useEffect, useState } from "react";
import { Activity, Cpu, Database, ExternalLink, FileCog, RefreshCcw, Router, ShieldCheck, Unplug } from "lucide-react";
import { api } from "../api/client.js";
import { ErrorBlock, LoadingBlock, Section } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

const cardConfig = [
  { key: "status", label: "Core System", title: "Backend API", icon: Router },
  { key: "offline_only", label: "Connectivity", title: "Offline Mode", icon: Unplug },
  { key: "host_ollama_reachable", label: "Inference", title: "Host Ollama", icon: Cpu },
  { key: "embedding_model_ready", label: "Vectorization", title: "Embedding Model", icon: Activity },
  { key: "qdrant_ready", label: "Vector DB", title: "Qdrant", icon: Database },
  { key: "doc_conversion_available", label: "Processing", title: "Doc Conversion", icon: FileCog },
];

function healthState(health, key) {
  if (key === "status") return health?.status === "ok" ? { text: "Online", tone: "success" } : { text: "Offline", tone: "danger" };
  if (key === "offline_only") return health?.offline_only ? { text: "Enabled", tone: "info" } : { text: "Disabled", tone: "warning" };
  if (key === "doc_conversion_available") return health?.doc_conversion_available ? { text: "Ready", tone: "success" } : { text: "Slow", tone: "warning" };
  return health?.[key] ? { text: "Ready", tone: "success" } : { text: "Not Ready", tone: "warning" };
}

function exportHealth(health) {
  const blob = new Blob([JSON.stringify(health, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "system-health.json";
  link.click();
  URL.revokeObjectURL(url);
}

export function HealthPage({ health, setHealth }) {
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(!health);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setHealth(await api.health());
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  if (loading) return <LoadingBlock />;

  const infrastructure = health?.infrastructure || {};
  const warning = !health?.doc_conversion_available
    ? "Document conversion service is unavailable in the current runtime. `.doc` ingestion will stay blocked until LibreOffice is present."
    : !health?.embedding_model_ready
      ? "Embedding cache is not ready yet. Querying will fall back to BM25 until the local embedding model is downloaded."
      : null;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="hero-row">
        <div>
          <h2 className="page-title">System Health Overview</h2>
          <p className="page-subtitle">Real-time monitoring of backend services and model infrastructure.</p>
        </div>
        <div className="button-row">
          <button type="button" className="ghost-button" onClick={refresh}><RefreshCcw size={16} /> Refresh</button>
          <button type="button" onClick={() => exportHealth(health)}><ShieldCheck size={16} /> Export Logs</button>
        </div>
      </div>
      {warning ? (
        <div className="health-warning">
          <div className="health-warning-icon"><FileCog size={18} /></div>
          <div>
            <strong>Warning</strong>
            <p>{warning}</p>
          </div>
        </div>
      ) : null}
      <div className="health-card-grid">
        {cardConfig.map((item) => {
          const Icon = item.icon;
          const state = healthState(health, item.key);
          return (
            <article className="health-status-card" key={item.key}>
              <div className="health-card-icon"><Icon size={18} /></div>
              <div className="health-card-copy">
                <p className="label-caps">{item.label}</p>
                <h3>{item.title}</h3>
              </div>
              <div className={`health-pill ${state.tone}`}>{state.text}</div>
            </article>
          );
        })}
      </div>
      <div className="health-panels">
        <Section title="Infrastructure Details">
          <div className="infra-table">
            <div className="infra-row">
              <span>Large Language Model</span>
              <code>{infrastructure.local_model_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>Model Context Window</span>
              <code>{infrastructure.local_model_num_ctx || "-"}</code>
            </div>
            <div className="infra-row">
              <span>Embedding Model</span>
              <code>{infrastructure.embedding_model_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>Qdrant Collection</span>
              <code>{infrastructure.qdrant_collection_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>Qdrant URL</span>
              <code>{infrastructure.qdrant_url || "-"}</code>
            </div>
          </div>
        </Section>
        <Section title="Quick Links">
          <div className="quick-link-list">
            <a className="quick-link" href={infrastructure.api_docs_path || "/docs"} target="_blank" rel="noreferrer">
              <span>API Docs</span>
              <ExternalLink size={15} />
            </a>
            <a className="quick-link" href={infrastructure.qdrant_dashboard_url || "http://localhost:6333/dashboard"} target="_blank" rel="noreferrer">
              <span>Qdrant Dashboard</span>
              <ExternalLink size={15} />
            </a>
            <a className="quick-link" href="/api/health" target="_blank" rel="noreferrer">
              <span>Health JSON</span>
              <ExternalLink size={15} />
            </a>
          </div>
          <div className="health-mini-checks">
            <div className="health-row"><span>Offline only</span><StatusBadge status={health?.offline_only ? "ok" : "warning"} /></div>
            <div className="health-row"><span>Embeddings</span><StatusBadge status={health?.embedding_model_ready ? "ok" : "warning"} /></div>
            <div className="health-row"><span>Doc conversion</span><StatusBadge status={health?.doc_conversion_available ? "ok" : "warning"} /></div>
          </div>
        </Section>
      </div>
    </div>
  );
}
