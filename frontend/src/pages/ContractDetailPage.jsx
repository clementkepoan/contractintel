import { useEffect, useState } from "react";
import { BookOpen, FileJson, Network, TriangleAlert } from "lucide-react";
import { api, formatDate, formatMoney } from "../api/client.js";
import { CitationButton } from "../components/CitationDrawer.jsx";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

function metadataRows(contract) {
  return [
    ["Parties Involved", contract.source_file],
    ["Document Category", String(contract.doc_category || "-").toUpperCase()],
    ["Execution Window", formatDate(contract.created_at || null)],
    ["Target Completion", formatDate(contract.updated_at || null)],
  ];
}

export function ContractDetailPage({ contractId, setSelectedContractId, setSelectedMilestoneId, setSelectedWikiPath, setPage, setCitation }) {
  const [contracts, setContracts] = useState([]);
  const [contract, setContract] = useState(null);
  const [financials, setFinancials] = useState(null);
  const [raw, setRaw] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const list = await api.contracts();
        setContracts(list);
        const activeId = contractId || list[0]?.contract_id;
        if (activeId) {
          setSelectedContractId(activeId);
          const [detail, totals] = await Promise.all([api.contract(activeId), api.financials(activeId)]);
          setContract(detail);
          setFinancials(totals);
        }
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [contractId, setSelectedContractId]);

  async function loadRaw() {
    if (!contract?.contract_id) return;
    setRaw(await api.rawContract(contract.contract_id));
  }

  if (loading) return <LoadingBlock />;
  if (!contract) return <EmptyBlock label="No contract selected." />;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="detail-header-bar">
        <div>
          <select value={contract.contract_id} onChange={(event) => setSelectedContractId(event.target.value)}>
            {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
          </select>
        </div>
        <div className="button-row">
          <button type="button" className="ghost-button" onClick={loadRaw}><FileJson size={16} /> Raw JSON</button>
          <button
            type="button"
            className="ghost-button"
            onClick={async () => {
              const paths = await api.wikiContract(contract.contract_id);
              setSelectedWikiPath(paths.project_path);
              setPage("wiki");
            }}
          ><BookOpen size={16} /> Open in Wiki</button>
          <button type="button" className="ghost-button" onClick={() => setPage("graph")}><Network size={16} /> View in Graph</button>
        </div>
      </div>
      <div className="contract-detail-layout">
        <div className="page-stack">
          <section className="contract-title-card">
            <div className="contract-title-main">
              <h2>{contract.contract_name}</h2>
              <div className="contract-submeta">
                <span>{contract.source_file}</span>
                <span>{formatMoney(contract.total_amount, contract.currency)}</span>
                <span>{String(contract.doc_category || contract.contract_type || "contract")}</span>
              </div>
            </div>
            {contract.validation?.length ? <div className="validation-header-pill"><TriangleAlert size={16} /> Validation Warning</div> : null}
          </section>
          <section className="warning-board">
            <div className="warning-board-header">
              <h3><TriangleAlert size={18} /> Validation Warnings</h3>
            </div>
            <div className="warning-stack">
              {(contract.validation || []).map((warning, index) => (
                <article className="warning-card" key={`${warning.code}-${index}`}>
                  <div className="warning-dot" />
                  <div className="warning-copy">
                    <strong>Code {warning.code || `V${index + 1}`}: {warning.message}</strong>
                    <div className="warning-actions">
                      <CitationButton citations={warning.citations || []} onOpen={setCitation} />
                      <span>{warning.citations?.[0]?.text_snippet || "View source clause context"}</span>
                    </div>
                  </div>
                </article>
              ))}
              {!contract.validation?.length ? <div className="muted">No validation warnings returned.</div> : null}
            </div>
          </section>
          <section className="deliverables-card">
            <div className="deliverables-header">
              <h3>Milestone Deliverables</h3>
              <span className="label-caps">{contract.milestones?.length || 0} items</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Milestone Name</th>
                    <th>Amount</th>
                    <th>%</th>
                    <th>Payment Condition</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(contract.milestones || []).map((milestone, index) => (
                    <tr key={milestone.milestone_id} onClick={() => { setSelectedMilestoneId(milestone.milestone_id); setPage("milestone"); }}>
                      <td>{String(index + 1).padStart(2, "0")}</td>
                      <td>{milestone.name}</td>
                      <td>{formatMoney(milestone.amount, contract.currency)}</td>
                      <td>{milestone.percentage ?? "-"}</td>
                      <td>{milestone.payment_condition || "-"}</td>
                      <td><StatusBadge status={milestone.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {raw ? <pre className="json-block">{JSON.stringify(raw, null, 2)}</pre> : null}
        </div>
        <aside className="contract-meta-card">
          <h3>Contract Metadata</h3>
          <div className="meta-section">
            {metadataRows(contract).map(([label, value]) => (
              <div className="meta-line" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <div className="meta-section">
            <div className="meta-line">
              <span>Total Requested</span>
              <strong>{formatMoney(financials?.payment_requested, contract.currency)}</strong>
            </div>
            <div className="meta-line">
              <span>Total Paid</span>
              <strong>{formatMoney(financials?.paid, contract.currency)}</strong>
            </div>
            <div className="meta-line">
              <span>Outstanding</span>
              <strong>{formatMoney(financials?.unpaid, contract.currency)}</strong>
            </div>
          </div>
          <div className="meta-section">
            <p className="label-caps">Recent Audit Activity</p>
            <div className="timeline-rail">
              <div className="timeline-entry"><strong>Automated validation run</strong><span>System · {formatDate(contract.updated_at || null)}</span></div>
              {(contract.validation || []).slice(0, 2).map((warning, index) => (
                <div className="timeline-entry" key={`${warning.code}-${index}`}><strong>{warning.code || "Warning"} flagged</strong><span>Risk Engine · {warning.severity || "warning"}</span></div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
