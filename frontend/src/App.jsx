import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import { CitationDrawer } from "./components/CitationDrawer.jsx";
import { ErrorBoundary } from "./components/ErrorBoundary.jsx";
import { Layout } from "./components/Layout.jsx";
import { ContractDetailPage } from "./pages/ContractDetailPage.jsx";
import { GraphPage } from "./pages/GraphPage.jsx";
import { HealthPage } from "./pages/HealthPage.jsx";
import { MilestoneDetailPage } from "./pages/MilestoneDetailPage.jsx";
import { OverviewPage } from "./pages/OverviewPage.jsx";
import { QueryPage } from "./pages/QueryPage.jsx";
import { WikiPage } from "./pages/WikiPage.jsx";
import { WorkflowPage } from "./pages/WorkflowPage.jsx";

const validPages = new Set(["overview", "detail", "milestone", "workflow", "query", "wiki", "graph", "health"]);

function initialPage() {
  const hash = window.location.hash.replace("#/", "");
  return validPages.has(hash) ? hash : "overview";
}

export function App() {
  const [page, setPageState] = useState(initialPage);
  const [health, setHealth] = useState(null);
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

  return (
    <ErrorBoundary>
      <Layout page={page} setPage={setPage} health={health}>
        {page === "overview" ? <OverviewPage setPage={setPage} setSelectedContractId={setSelectedContractId} setSelectedWikiPath={setSelectedWikiPath} setCitation={setCitation} /> : null}
        {page === "detail" ? <ContractDetailPage contractId={selectedContractId} setSelectedContractId={setSelectedContractId} setSelectedMilestoneId={setSelectedMilestoneId} setSelectedWikiPath={setSelectedWikiPath} setPage={setPage} setCitation={setCitation} /> : null}
        {page === "milestone" ? <MilestoneDetailPage milestoneId={selectedMilestoneId} setSelectedMilestoneId={setSelectedMilestoneId} setSelectedWikiPath={setSelectedWikiPath} setPage={setPage} setCitation={setCitation} /> : null}
        {page === "workflow" ? <WorkflowPage contractId={selectedContractId} setSelectedContractId={setSelectedContractId} /> : null}
        {page === "query" ? <QueryPage contractId={selectedContractId} setSelectedContractId={setSelectedContractId} setSelectedWikiPath={setSelectedWikiPath} setPage={setPage} setCitation={setCitation} /> : null}
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
    </ErrorBoundary>
  );
}
