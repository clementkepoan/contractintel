import { BookOpen, Boxes, CreditCard, FileSearch, FlaskConical, GitBranch, HeartPulse, Landmark, Network } from "lucide-react";
import { useI18n } from "../i18n.jsx";

const navSections = [
  {
    id: "workspace",
    label: "Workspace",
    items: [
      { id: "overview", labelKey: "nav.overview", icon: Landmark },
      { id: "detail", labelKey: "nav.detail", icon: FileSearch },
      { id: "milestone", labelKey: "nav.milestone", icon: Boxes },
      { id: "workflow", labelKey: "nav.workflow", icon: CreditCard },
      { id: "query", labelKey: "nav.query", icon: GitBranch },
    ],
  },
  {
    id: "knowledge",
    label: "Knowledge",
    items: [
      { id: "wiki", labelKey: "nav.wiki", icon: BookOpen },
      { id: "graph", labelKey: "nav.graph", icon: Network },
    ],
  },
  {
    id: "system",
    label: "System",
    items: [
      { id: "health", labelKey: "nav.health", icon: HeartPulse },
    ],
  },
];

const pageLabelById = Object.fromEntries(
  [
    ...navSections.flatMap((section) => section.items),
    { id: "regression", labelKey: "nav.regression", icon: FlaskConical },
  ].map((item) => [item.id, item.labelKey]),
);

function FloatingProcessingBar({ activeIngestRun, setPage }) {
  const { t } = useI18n();
  if (!activeIngestRun) return null;
  const { completed_files: completedFiles = 0, total_files: totalFiles = 0, failed_files: failedFiles = 0, processing_file: processingFile } = activeIngestRun;
  const percent = totalFiles ? Math.max(8, Math.round((completedFiles / totalFiles) * 100)) : 0;
  return (
    <button type="button" className="floating-run-bar" onClick={() => setPage("overview")}>
      <div className="floating-run-copy">
        <strong>{t("shell.processingDocuments")}</strong>
        <span>{completedFiles}/{totalFiles} {t("shell.completed")} {failedFiles ? `· ${failedFiles} ${t("shell.failed")}` : ""}</span>
        {processingFile ? <small>{t("shell.runningNow")}: {processingFile}</small> : null}
      </div>
      <div className="floating-run-progress">
        <div className="floating-run-progress-fill" style={{ width: `${percent}%` }} />
      </div>
      <span className="floating-run-link">{t("shell.openOverview")}</span>
    </button>
  );
}

export function Layout({ page, setPage, health, activeIngestRun, children }) {
  const { lang, setLang, t } = useI18n();
  const pageLabel = pageLabelById[page] ? t(pageLabelById[page]) : "Contract Intelligence";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand brand-logo">
          <div className="brand-lockup">
            <div className="brand-mark-modern" aria-hidden="true">
              <span className="brand-mark-main" />
              <span className="brand-mark-cut" />
            </div>
            <div className="brand-wording">
              <h1>ONEWORK</h1>
              <p>{t("shell.subtitle")}</p>
            </div>
          </div>
        </div>
        <nav className="nav-list modern">
          {navSections.map((section) => (
            <div key={section.id} className="nav-section">
              <p className="nav-section-label">{section.label}</p>
              <div className="nav-section-items">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button key={item.id} className={page === item.id ? "nav-item active" : "nav-item"} type="button" onClick={() => setPage(item.id)}>
                      <span className="nav-item-icon"><Icon size={17} /></span>
                      <span>{t(item.labelKey)}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-language">
            <span className="label-caps">{t("shell.language")}</span>
            <div className="language-toggle">
              <button type="button" className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>{t("shell.english")}</button>
              <button type="button" className={lang === "zh-TW" ? "active" : ""} onClick={() => setLang("zh-TW")}>{t("shell.traditionalChinese")}</button>
            </div>
          </div>
          <div className="local-mode modern">
            <div className="local-mode-head">
              <span className={health?.status === "ok" ? "pulse-dot" : "pulse-dot muted"} />
              <div>
                <strong>{t("shell.localMode")}</strong>
                <span>{health?.local_model_server_reachable ? t("shell.ollamaReachable") : t("shell.llmUnreachable")}</span>
              </div>
            </div>
            <div className="local-mode-foot">
              <span>{health?.offline_only ? t("shell.offlinePipeline") : "Online"}</span>
            </div>
          </div>
        </div>
      </aside>
      <main className="content">
        <header className="topbar modern">
          <div className="topbar-title">
            <p className="label-caps">Offline Contract Intelligence</p>
            <h1>{pageLabel}</h1>
          </div>
          <div className="topbar-actions modern">
            <button type="button" className={page === "regression" ? "topbar-utility active" : "topbar-utility"} onClick={() => setPage("regression")}>
              <span className="topbar-utility-icon"><FlaskConical size={17} /></span>
              <span className="topbar-utility-copy">
                <strong>{t("nav.regression")}</strong>
                <small>Prompt and retrieval QA</small>
              </span>
            </button>
          </div>
        </header>
        {children}
      </main>
      <FloatingProcessingBar activeIngestRun={activeIngestRun} setPage={setPage} />
    </div>
  );
}
