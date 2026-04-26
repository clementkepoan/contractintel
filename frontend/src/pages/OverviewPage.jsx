import { useEffect, useMemo, useState } from "react";
import { BookOpen, Eye, Network, Upload } from "lucide-react";
import { api, formatDate, formatMoney } from "../api/client.js";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

function workflowTone(milestones = []) {
  if (milestones.some((item) => item.status === "payment_requested")) return "Active";
  if (milestones.some((item) => item.status === "accepted")) return "Under Review";
  if (milestones.length === 0) return "Draft";
  return "Active";
}

function UploadProgressBar({ stage, percent, filename }) {
  if (stage === "idle") return null;
  const processing = stage === "processing";
  return (
    <div className={processing ? "upload-progress upload-progress--processing" : "upload-progress"}>
      <div className="upload-progress__header">
        <strong>{filename || "Document upload"}</strong>
        <span>
          {stage === "uploading" ? `Uploading... ${percent}%` : null}
          {stage === "processing" ? "Extracting and indexing..." : null}
          {stage === "done" ? "Completed" : null}
          {stage === "error" ? "Failed" : null}
        </span>
      </div>
      <div className="upload-progress__track">
        <div className="upload-progress__fill" style={{ width: processing ? "100%" : `${percent}%` }} />
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

function SkeletonMilestoneList() {
  return (
    <div className="skeleton-list">
      {[1, 2, 3].map((index) => <SkeletonCard key={index} />)}
    </div>
  );
}

export function OverviewPage({ setPage, setSelectedContractId, setSelectedWikiPath }) {
  const [contracts, setContracts] = useState([]);
  const [financials, setFinancials] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [uploadState, setUploadState] = useState({ stage: "idle", percent: 0, filename: null, error: null });
  const [typeFilter, setTypeFilter] = useState("all");
  const [validationFilter, setValidationFilter] = useState("all");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const list = await api.contracts();
      setContracts(list);
      const rows = await Promise.allSettled(list.map((contract) => api.financials(contract.contract_id)));
      setFinancials(Object.fromEntries(rows.filter((row) => row.status === "fulfilled").map((row) => [row.value.contract_id, row.value])));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const totals = useMemo(() => {
    const totalAmount = contracts.reduce((sum, item) => sum + Number(item.total_amount || 0), 0);
    const requested = Object.values(financials).reduce((sum, item) => sum + Number(item.payment_requested || 0), 0);
    const paid = Object.values(financials).reduce((sum, item) => sum + Number(item.paid || 0), 0);
    const warnings = contracts.reduce((sum, item) => sum + (item.validation || []).length, 0);
    return { totalAmount, requested, paid, unpaid: Math.max(totalAmount - paid, 0), warnings };
  }, [contracts, financials]);

  const filtered = contracts.filter((contract) => {
    const typeOk = typeFilter === "all" || contract.doc_category === typeFilter || contract.contract_type === typeFilter;
    const validationState = contract.validation?.length ? "warning" : "passed";
    const validationOk = validationFilter === "all" || validationFilter === validationState;
    return typeOk && validationOk;
  });

  async function upload(file) {
    if (!file) return;
    setUploadState({ stage: "uploading", percent: 0, filename: file.name, error: null });
    setError(null);
    try {
      const result = await api.uploadWithProgress(file, ({ stage, percent }) => {
        setUploadState((current) => ({ ...current, stage, percent }));
      });
      await load();
      setSelectedContractId(result.contract_id);
      setSelectedWikiPath("");
      setUploadState((current) => ({ ...current, stage: "done", percent: 100 }));
    } catch (err) {
      setError(err);
      setUploadState((current) => ({ ...current, stage: "error", error: err.message || String(err) }));
    } finally {
      window.setTimeout(() => {
        setUploadState((current) => (current.stage === "done" ? { stage: "idle", percent: 0, filename: null, error: null } : current));
      }, 1200);
    }
  }

  if (loading) return <LoadingBlock />;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="overview-metrics">
        <article className="overview-stat-card">
          <span className="label-caps">Total Contract Value</span>
          <strong>{formatMoney(totals.totalAmount)}</strong>
        </article>
        <article className="overview-stat-card">
          <span className="label-caps">Payment Requested</span>
          <strong>{formatMoney(totals.requested)}</strong>
        </article>
        <article className="overview-stat-card">
          <span className="label-caps">Paid</span>
          <strong>{formatMoney(totals.paid)}</strong>
        </article>
        <article className="overview-stat-card">
          <span className="label-caps">Unpaid</span>
          <strong>{formatMoney(totals.unpaid)}</strong>
        </article>
        <article className="overview-stat-card warning">
          <span className="label-caps">Validation Warnings</span>
          <strong>{totals.warnings}</strong>
        </article>
      </div>
      <div className="overview-toolbar">
        <div className="overview-filters">
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="all">Type: All Types</option>
            <option value="contract">Type: Contract</option>
            <option value="rfp">Type: RFP</option>
            <option value="ci">Type: CI</option>
          </select>
          <select value={validationFilter} onChange={(event) => setValidationFilter(event.target.value)}>
            <option value="all">Validation: All Status</option>
            <option value="passed">Validation: Passed</option>
            <option value="warning">Validation: Warning</option>
          </select>
        </div>
        <label className="file-button dark">
          <Upload size={16} />
          {uploadState.stage === "idle" ? "Import .doc/.docx" : "Importing..."}
          <input type="file" accept=".doc,.docx" disabled={uploadState.stage === "uploading" || uploadState.stage === "processing"} onChange={(event) => upload(event.target.files?.[0])} />
        </label>
      </div>
      <UploadProgressBar stage={uploadState.stage} percent={uploadState.percent} filename={uploadState.filename} />
      {uploadState.stage === "processing" ? <SkeletonMilestoneList /> : null}
      {uploadState.stage === "error" && uploadState.error ? <ErrorBlock error={{ message: uploadState.error }} /> : null}
      {!filtered.length ? <EmptyBlock label="No contracts imported yet. Upload a .doc or .docx file to begin." /> : null}
      {filtered.length ? (
        <div className="overview-table-card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Contract Name</th>
                  <th>Type</th>
                  <th>Amount</th>
                  <th>Milestones</th>
                  <th>Validation</th>
                  <th>Workflow</th>
                  <th>Updated</th>
                  <th>Actions</th>
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
                      <td>{String(contract.doc_category || contract.contract_type || "contract").toUpperCase()}</td>
                      <td>{formatMoney(contract.total_amount, contract.currency)}</td>
                      <td>{contract.milestones?.length || 0}</td>
                      <td><StatusBadge status={validationState} /></td>
                      <td><span className={`workflow-pill ${workflow.toLowerCase().replaceAll(" ", "-")}`}>{workflow}</span></td>
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
