import { useEffect, useState } from "react";
import { Activity, Cpu, Database, ExternalLink, FileCog, RefreshCcw, Router, ShieldCheck, Unplug } from "lucide-react";
import { api } from "../api/client.js";
import { useI18n } from "../i18n.jsx";
import { ErrorBlock, LoadingBlock, Section } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

const cardConfig = [
  { key: "status", labelKey: "health.coreSystem", titleKey: "health.backendApi", icon: Router },
  { key: "offline_only", labelKey: "health.connectivity", titleKey: "health.offlineMode", icon: Unplug },
  { key: "local_model_server_reachable", labelKey: "health.inference", titleKey: "health.hostOllama", icon: Cpu },
  { key: "embedding_model_ready", labelKey: "health.vectorization", titleKey: "health.embeddingModel", icon: Activity },
  { key: "qdrant_ready", labelKey: "health.vectorDb", titleKey: "health.qdrant", icon: Database },
  { key: "doc_conversion_available", labelKey: "health.processing", titleKey: "health.docConversion", icon: FileCog },
];

function healthState(health, key, t) {
  if (key === "status") return health?.status === "ok" ? { text: t("health.online"), tone: "success" } : { text: t("health.offline"), tone: "danger" };
  if (key === "offline_only") return health?.offline_only ? { text: t("health.enabled"), tone: "info" } : { text: t("health.disabled"), tone: "warning" };
  if (key === "doc_conversion_available") return health?.doc_conversion_available ? { text: t("health.ready"), tone: "success" } : { text: t("health.slow"), tone: "warning" };
  return health?.[key] ? { text: t("health.ready"), tone: "success" } : { text: t("health.notReady"), tone: "warning" };
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
  const { t } = useI18n();
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

  if (loading) return <LoadingBlock label={t("common.loadingData")} />;

  const infrastructure = health?.infrastructure || {};
  const warning = !health?.doc_conversion_available
    ? "Document conversion service is unavailable in the current runtime. `.doc` ingestion will stay blocked until LibreOffice is present."
    : !health?.embedding_model_ready
      ? "Embedding service is not ready yet. Vector retrieval will stay degraded until the local embedding model endpoint responds."
      : null;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="hero-row">
        <div>
          <h2 className="page-title">{t("health.title")}</h2>
          <p className="page-subtitle">{t("health.subtitle")}</p>
        </div>
        <div className="button-row">
          <button type="button" className="ghost-button" onClick={refresh}><RefreshCcw size={16} /> {t("health.refresh")}</button>
          <button type="button" onClick={() => exportHealth(health)}><ShieldCheck size={16} /> {t("health.exportLogs")}</button>
        </div>
      </div>
      {warning ? (
        <div className="health-warning">
          <div className="health-warning-icon"><FileCog size={18} /></div>
          <div>
            <strong>{t("health.warning")}</strong>
            <p>{warning}</p>
          </div>
        </div>
      ) : null}
      <div className="health-card-grid">
        {cardConfig.map((item) => {
          const Icon = item.icon;
          const state = healthState(health, item.key, t);
          return (
            <article className="health-status-card" key={item.key}>
              <div className="health-card-icon"><Icon size={18} /></div>
              <div className="health-card-copy">
                <p className="label-caps">{t(item.labelKey)}</p>
                <h3>{t(item.titleKey)}</h3>
              </div>
              <div className={`health-pill ${state.tone}`}>{state.text}</div>
            </article>
          );
        })}
      </div>
      <div className="health-panels">
        <Section title={t("health.infrastructureDetails")}>
          <div className="infra-table">
            <div className="infra-row">
              <span>{t("health.extractionModel")}</span>
              <code>{infrastructure.local_extraction_model_name || infrastructure.local_model_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>{t("health.queryModel")}</span>
              <code>{infrastructure.local_query_model_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>{t("health.modelContextWindow")}</span>
              <code>{infrastructure.local_model_num_ctx || "-"}</code>
            </div>
            <div className="infra-row">
              <span>{t("health.embeddingModel")}</span>
              <code>{infrastructure.embedding_model_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>{t("health.rerankerModel")}</span>
              <code>{infrastructure.reranker_model_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>{t("health.qdrantCollection")}</span>
              <code>{infrastructure.qdrant_collection_name || "-"}</code>
            </div>
            <div className="infra-row">
              <span>{t("health.qdrantUrl")}</span>
              <code>{infrastructure.qdrant_url || "-"}</code>
            </div>
          </div>
        </Section>
        <Section title={t("health.quickLinks")}>
          <div className="quick-link-list">
            <a className="quick-link" href={infrastructure.api_docs_path || "/docs"} target="_blank" rel="noreferrer">
              <span>{t("health.apiDocs")}</span>
              <ExternalLink size={15} />
            </a>
            <a className="quick-link" href={infrastructure.qdrant_dashboard_url || "http://localhost:6333/dashboard"} target="_blank" rel="noreferrer">
              <span>{t("health.qdrantDashboard")}</span>
              <ExternalLink size={15} />
            </a>
            <a className="quick-link" href="/api/health" target="_blank" rel="noreferrer">
              <span>{t("health.healthJson")}</span>
              <ExternalLink size={15} />
            </a>
          </div>
          <div className="health-mini-checks">
            <div className="health-row"><span>{t("health.offlineOnly")}</span><StatusBadge status={health?.offline_only ? "ok" : "warning"} /></div>
            <div className="health-row"><span>{t("health.embeddings")}</span><StatusBadge status={health?.embedding_model_ready ? "ok" : "warning"} /></div>
            <div className="health-row"><span>{t("health.docConversion")}</span><StatusBadge status={health?.doc_conversion_available ? "ok" : "warning"} /></div>
          </div>
        </Section>
      </div>
    </div>
  );
}
