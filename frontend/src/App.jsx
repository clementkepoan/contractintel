import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import { CitationDrawer } from "./components/CitationDrawer.jsx";
import { ErrorBoundary } from "./components/ErrorBoundary.jsx";
import { Layout } from "./components/Layout.jsx";
import { I18nProvider } from "./i18n.jsx";
import { ContractDetailPage } from "./pages/ContractDetailPage.jsx";
import { GraphPage } from "./pages/GraphPage.jsx";
import { HealthPage } from "./pages/HealthPage.jsx";
import { MilestoneDetailPage } from "./pages/MilestoneDetailPage.jsx";
import { OverviewPage } from "./pages/OverviewPage.jsx";
import { QueryPage } from "./pages/QueryPage.jsx";
import { RegressionPage } from "./pages/RegressionPage.jsx";
import { WikiPage } from "./pages/WikiPage.jsx";
import { WorkflowPage } from "./pages/WorkflowPage.jsx";

const validPages = new Set(["overview", "detail", "milestone", "workflow", "query", "regression", "wiki", "graph", "health"]);

function initialPage() {
  const hash = window.location.hash.replace("#/", "");
  return validPages.has(hash) ? hash : "overview";
}

export function App() {
  const [page, setPageState] = useState(initialPage);
  const [health, setHealth] = useState(null);
  const [activeIngestRun, setActiveIngestRun] = useState(null);
  const [selectedContractId, setSelectedContractId] = useState("");
  const [selectedMilestoneId, setSelectedMilestoneId] = useState("");
  const [selectedWikiPath, setSelectedWikiPath] = useState("");
  const [citation, setCitation] = useState(null);

  function setPage(nextPage) {
    setPageState(nextPage);
    window.location.hash = `/${nextPage}`;
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "unavailable", offline_only: true }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    async function poll() {
      try {
        const run = await api.activeIngestRun();
        if (cancelled) return;
        setActiveIngestRun(run);
        if (run?.run_id) {
          window.localStorage.setItem("active-ingest-run-id", run.run_id);
        } else {
          window.localStorage.removeItem("active-ingest-run-id");
        }
      } catch {
        if (!cancelled) setActiveIngestRun(null);
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(poll, activeIngestRun ? 1500 : 3000);
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeIngestRun?.run_id, activeIngestRun?.status]);

  return (
    <ErrorBoundary>
      <I18nProvider>
      <Layout page={page} setPage={setPage} health={health} activeIngestRun={activeIngestRun}>
        {page === "overview" ? <OverviewPage activeIngestRun={activeIngestRun} refreshActiveIngestRun={async () => setActiveIngestRun(await api.activeIngestRun())} setPage={setPage} setSelectedContractId={setSelectedContractId} setSelectedWikiPath={setSelectedWikiPath} setCitation={setCitation} /> : null}
        {page === "detail" ? <ContractDetailPage contractId={selectedContractId} setSelectedContractId={setSelectedContractId} setSelectedMilestoneId={setSelectedMilestoneId} setSelectedWikiPath={setSelectedWikiPath} setPage={setPage} setCitation={setCitation} /> : null}
        {page === "milestone" ? <MilestoneDetailPage milestoneId={selectedMilestoneId} setSelectedMilestoneId={setSelectedMilestoneId} setSelectedWikiPath={setSelectedWikiPath} setPage={setPage} setCitation={setCitation} /> : null}
        {page === "workflow" ? <WorkflowPage contractId={selectedContractId} setSelectedContractId={setSelectedContractId} /> : null}
        {page === "query" ? <QueryPage contractId={selectedContractId} setSelectedContractId={setSelectedContractId} setSelectedWikiPath={setSelectedWikiPath} setPage={setPage} setCitation={setCitation} /> : null}
        {page === "regression" ? <RegressionPage /> : null}
        {page === "wiki" ? <WikiPage setPage={setPage} selectedWikiPath={selectedWikiPath} setSelectedWikiPath={setSelectedWikiPath} selectedContractId={selectedContractId} selectedMilestoneId={selectedMilestoneId} setSelectedContractId={setSelectedContractId} setSelectedMilestoneId={setSelectedMilestoneId} /> : null}
        {page === "graph" ? <GraphPage contractId={selectedContractId} milestoneId={selectedMilestoneId} setSelectedContractId={setSelectedContractId} setSelectedMilestoneId={setSelectedMilestoneId} setPage={setPage} /> : null}
        {page === "health" ? <HealthPage health={health} setHealth={setHealth} /> : null}
        <CitationDrawer
          citation={citation}
          onClose={() => setCitation(null)}
          onOpenSource={(path) => {
            setSelectedWikiPath(path);
            setPage("wiki");
            setCitation(null);
          }}
        />
      </Layout>
      </I18nProvider>
    </ErrorBoundary>
  );
}
