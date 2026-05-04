import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Eye, Network, Upload } from "lucide-react";
import { api, formatDate, formatMoney } from "../api/client.js";
import { normalizeTypeValue, translateContractType, useI18n } from "../i18n.jsx";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

function workflowTone(milestones = []) {
  if (milestones.some((item) => item.status === "payment_requested")) return "active";
  if (milestones.some((item) => item.status === "accepted")) return "underReview";
  if (milestones.length === 0) return "draft";
  return "active";
}

function workflowLabel(workflow, t) {
  if (workflow === "underReview") return t("overview.workflowUnderReview");
  if (workflow === "draft") return t("overview.workflowDraft");
  return t("overview.workflowActive");
}

function workflowClass(workflow) {
  if (workflow === "underReview") return "under-review";
  return workflow;
}

function UploadProgressBar({ run, requestProgress }) {
  const { t } = useI18n();
  if (!run && !requestProgress) return null;
  const stage = requestProgress?.stage || (run ? "processing" : "idle");
  const totalFiles = run?.total_files || requestProgress?.totalFiles || 0;
  const completedFiles = run?.completed_files || 0;
  const processingFile = run?.processing_file || requestProgress?.filename;
  const percent = stage === "uploading"
    ? requestProgress?.percent || 0
    : (totalFiles ? Math.round((completedFiles / totalFiles) * 100) : 100);
  return (
    <div className={stage === "processing" ? "upload-progress upload-progress--processing" : "upload-progress"}>
      <div className="upload-progress__header">
        <strong>{processingFile || t("overview.processingRun")}</strong>
        <span>
          {stage === "uploading" ? `${t("common.uploading")}... ${percent}%` : null}
          {stage === "processing" ? `${t("overview.extracting")} ${completedFiles}/${totalFiles}` : null}
          {run?.status === "completed" ? `${t("common.completed")} ${completedFiles}/${totalFiles}` : null}
          {run?.status === "completed_with_errors" || run?.status === "failed" ? t("common.failed") : null}
        </span>
      </div>
      <div className="upload-progress__track">
        <div className="upload-progress__fill" style={{ width: `${Math.min(100, Math.max(8, percent || 0))}%` }} />
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-line skeleton-line--title" />
      <div className="skeleton-line skeleton-line--short" />
      <div className="skeleton-line" />
      <div className="skeleton-line skeleton-line--short" />
    </div>
  );
}

function SkeletonMilestoneList({ count = 3 }) {
  const skeletonCount = Math.max(1, Math.min(count, 12));
  return (
    <div className="skeleton-list">
      {Array.from({ length: skeletonCount }, (_, index) => <SkeletonCard key={index} />)}
    </div>
  );
}

export function OverviewPage({ activeIngestRun, refreshActiveIngestRun, setPage, setSelectedContractId, setSelectedWikiPath }) {
  const { t } = useI18n();
  const [contracts, setContracts] = useState([]);
  const [financials, setFinancials] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [requestProgress, setRequestProgress] = useState(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [validationFilter, setValidationFilter] = useState("all");
  const lastCompletedCount = useRef(-1);
  const previousRunId = useRef(null);

  async function load({ silent = false } = {}) {
    if (!silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const list = await api.contracts();
      setContracts(list);
      const rows = await Promise.allSettled(list.map((contract) => api.financials(contract.contract_id)));
      setFinancials(Object.fromEntries(rows.filter((row) => row.status === "fulfilled").map((row) => [row.value.contract_id, row.value])));
    } catch (err) {
      setError(err);
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const completedCount = activeIngestRun?.completed_files ?? -1;
    const currentRunId = activeIngestRun?.run_id ?? null;

    if (completedCount > lastCompletedCount.current) {
      lastCompletedCount.current = completedCount;
      load({ silent: true });
    }

    // When the backend stops reporting an active run after completion,
    // refresh once so newly imported contracts appear without a manual reload.
    if (!currentRunId && previousRunId.current) {
      window.setTimeout(() => {
        load({ silent: true });
      }, 500);
    }

    if (!activeIngestRun) {
      lastCompletedCount.current = -1;
    }
    previousRunId.current = currentRunId;
  }, [activeIngestRun?.completed_files, activeIngestRun?.run_id]);

  useEffect(() => {
    if (!activeIngestRun?.run_id) return undefined;
    const timer = window.setInterval(() => {
      load({ silent: true });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeIngestRun?.run_id]);

  const pendingRunContracts = useMemo(() => {
    const pendingContractIds = new Set();
    const pendingSourceFiles = new Set();
    for (const item of activeIngestRun?.items || []) {
      if (item.status === "completed") continue;
      if (item.contract_id) pendingContractIds.add(item.contract_id);
      if (item.source_file) pendingSourceFiles.add(item.source_file);
    }
    return { pendingContractIds, pendingSourceFiles };
  }, [activeIngestRun?.items]);

  const visibleContracts = contracts.filter((contract) => {
    if (pendingRunContracts.pendingContractIds.has(contract.contract_id)) return false;
    if (pendingRunContracts.pendingSourceFiles.has(contract.source_file)) return false;
    return true;
  });

  const totals = useMemo(() => {
    const visibleIds = new Set(visibleContracts.map((contract) => contract.contract_id));
    const totalAmount = visibleContracts.reduce((sum, item) => sum + Number(item.total_amount || 0), 0);
    const requested = Object.values(financials)
      .filter((item) => visibleIds.has(item.contract_id))
      .reduce((sum, item) => sum + Number(item.payment_requested || 0), 0);
    const paid = Object.values(financials)
      .filter((item) => visibleIds.has(item.contract_id))
      .reduce((sum, item) => sum + Number(item.paid || 0), 0);
    const warnings = visibleContracts.reduce((sum, item) => sum + (item.validation || []).length, 0);
    return { totalAmount, requested, paid, unpaid: Math.max(totalAmount - paid, 0), warnings };
  }, [visibleContracts, financials]);

  const filtered = visibleContracts.filter((contract) => {
    const docCategory = normalizeTypeValue(contract.doc_category);
    const contractType = normalizeTypeValue(contract.contract_type);
    const typeOk = typeFilter === "all" || docCategory === typeFilter || contractType === typeFilter;
    const validationState = contract.validation?.length ? "warning" : "passed";
    const validationOk = validationFilter === "all" || validationFilter === validationState;
    return typeOk && validationOk;
  });

  async function upload(files) {
    const selectedFiles = Array.from(files || []).filter(Boolean);
    if (!selectedFiles.length) return;
    setRequestProgress({ stage: "uploading", percent: 0, totalFiles: selectedFiles.length, filename: selectedFiles[0].name });
    setError(null);
    try {
      const run = await api.createIngestRun(selectedFiles, ({ stage, percent }) => {
        setRequestProgress({ stage, percent, totalFiles: selectedFiles.length, filename: selectedFiles[0]?.name || null });
      });
      await refreshActiveIngestRun();
      setRequestProgress(null);
      setSelectedWikiPath("");
      if (run?.items?.[0]?.contract_id) {
        setSelectedContractId(run.items[0].contract_id);
      }
    } catch (err) {
      setError(err);
      setRequestProgress(null);
    }
  }

  if (loading) return <LoadingBlock label={t("common.loadingData")} />;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="overview-metrics">
        <article className="overview-stat-card">
          <span className="label-caps">{t("overview.totalContractValue")}</span>
          <strong>{formatMoney(totals.totalAmount)}</strong>
        </article>
        <article className="overview-stat-card">
          <span className="label-caps">{t("overview.paymentRequested")}</span>
          <strong>{formatMoney(totals.requested)}</strong>
        </article>
        <article className="overview-stat-card">
          <span className="label-caps">{t("overview.paid")}</span>
          <strong>{formatMoney(totals.paid)}</strong>
        </article>
        <article className="overview-stat-card">
          <span className="label-caps">{t("overview.unpaid")}</span>
          <strong>{formatMoney(totals.unpaid)}</strong>
        </article>
        <article className="overview-stat-card warning">
          <span className="label-caps">{t("overview.validationWarnings")}</span>
          <strong>{totals.warnings}</strong>
        </article>
      </div>
      <div className="overview-toolbar">
        <div className="overview-filters">
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="all">{t("overview.typeAll")}</option>
            <option value="contract">{t("overview.typeContract")}</option>
            <option value="rfp">{t("overview.typeRfp")}</option>
            <option value="construction_instruction">{t("overview.typeCi")}</option>
            <option value="spec_rfp">{t("overview.typeSpecRfp")}</option>
            <option value="mixed">{t("overview.typeMixed")}</option>
          </select>
          <select value={validationFilter} onChange={(event) => setValidationFilter(event.target.value)}>
            <option value="all">{t("overview.validationAll")}</option>
            <option value="passed">{t("overview.validationPassed")}</option>
            <option value="warning">{t("overview.validationWarning")}</option>
          </select>
        </div>
        <label className="file-button dark">
          <Upload size={16} />
          {requestProgress ? `${t("overview.importing")} ${requestProgress.totalFiles || 1}` : t("overview.importDocs")}
          <input
            type="file"
            accept=".doc,.docx"
            multiple
            disabled={Boolean(activeIngestRun) || requestProgress?.stage === "uploading"}
            onChange={(event) => {
              upload(event.target.files);
              event.target.value = "";
            }}
          />
        </label>
      </div>
      <UploadProgressBar run={activeIngestRun} requestProgress={requestProgress} />
      {activeIngestRun ? (
        <>
          <SkeletonMilestoneList count={Math.max(1, activeIngestRun.total_files - activeIngestRun.completed_files)} />
        </>
      ) : null}
      {!filtered.length ? <EmptyBlock label={t("common.noContracts")} /> : null}
      {filtered.length ? (
        <div className="overview-table-card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("overview.contractName")}</th>
                  <th>{t("overview.type")}</th>
                  <th>{t("overview.amount")}</th>
                  <th>{t("overview.milestones")}</th>
                  <th>{t("overview.validation")}</th>
                  <th>{t("overview.workflow")}</th>
                  <th>{t("overview.updated")}</th>
                  <th>{t("overview.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((contract) => {
                  const workflow = workflowTone(contract.milestones);
                  const validationState = contract.validation?.length ? "warning" : "accepted";
                  return (
                    <tr key={contract.contract_id}>
                      <td>
                        <strong>{contract.contract_name}</strong>
                        <small>{contract.source_file}</small>
                      </td>
                      <td>{translateContractType(contract.doc_category || contract.contract_type || "contract", t)}</td>
                      <td>{formatMoney(contract.total_amount, contract.currency)}</td>
                      <td>{contract.milestones?.length || 0}</td>
                      <td><StatusBadge status={validationState} /></td>
                      <td><span className={`workflow-pill ${workflowClass(workflow)}`}>{workflowLabel(workflow, t)}</span></td>
                      <td>{formatDate(contract.updated_at || null)}</td>
                      <td>
                        <div className="action-icons">
                          <button type="button" className="ghost-button square" onClick={() => { setSelectedContractId(contract.contract_id); setPage("detail"); }}><Eye size={16} /></button>
                          <button type="button" className="ghost-button square" onClick={async () => {
                            setSelectedContractId(contract.contract_id);
                            const paths = await api.wikiContract(contract.contract_id);
                            setSelectedWikiPath(paths.project_path);
                            setPage("wiki");
                          }}><BookOpen size={16} /></button>
                          <button type="button" className="ghost-button square" onClick={() => { setSelectedContractId(contract.contract_id); setPage("graph"); }}><Network size={16} /></button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
