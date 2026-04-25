import { useEffect, useState } from "react";
import { Quote } from "lucide-react";
import { api, formatMoney } from "../api/client.js";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

export function MilestoneDetailPage({ milestoneId, setSelectedMilestoneId, setCitation }) {
  const [contracts, setContracts] = useState([]);
  const [milestone, setMilestone] = useState(null);
  const [contract, setContract] = useState(null);
  const [selectedCitationIndex, setSelectedCitationIndex] = useState(0);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const list = await api.contracts();
        setContracts(list);
        const fallbackId = list.flatMap((item) => item.milestones || [])[0]?.milestone_id;
        const activeId = milestoneId || fallbackId;
        if (activeId) {
          setSelectedMilestoneId(activeId);
          const detail = await api.milestone(activeId);
          setMilestone(detail);
          setContract(list.find((item) => item.contract_id === detail.contract_id) || null);
        }
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [milestoneId, setSelectedMilestoneId]);

  const options = contracts.flatMap((item) => (item.milestones || []).map((milestoneItem) => ({ ...milestoneItem, contract_name: item.contract_name })));
  const selectedCitation = milestone?.citations?.[selectedCitationIndex] || null;

  if (loading) return <LoadingBlock />;
  if (!milestone) return <EmptyBlock label="No milestone available." />;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="milestone-breadcrumb">
        <select value={milestone.milestone_id} onChange={(event) => setSelectedMilestoneId(event.target.value)}>
          {options.map((item) => <option key={item.milestone_id} value={item.milestone_id}>{item.contract_name} / {item.name}</option>)}
        </select>
      </div>
      <div className="milestone-layout">
        <div className="page-stack">
          <section className="milestone-hero-card">
            <div className="milestone-hero-title">
              <h2>{milestone.name}</h2>
              <StatusBadge status={milestone.status} />
            </div>
            <div className="milestone-hero-metrics">
              <div><span className="label-caps">Amount</span><strong>{formatMoney(milestone.amount, contract?.currency || "TWD")}</strong></div>
              <div><span className="label-caps">Percentage</span><strong>{milestone.percentage ?? "-"}%</strong></div>
            </div>
          </section>
          <div className="milestone-columns">
            <section className="milestone-panel">
              <div className="milestone-panel-header"><h3>Work Items</h3></div>
              <div className="milestone-list">
                {milestone.work_items?.length ? milestone.work_items.map((item, index) => (
                  <div className="milestone-list-item" key={`${item}-${index}`}>
                    <span className="milestone-radio" />
                    <p>{item}</p>
                    <button type="button" className="ghost-button square" onClick={() => { setSelectedCitationIndex(index % (milestone.citations?.length || 1)); setCitation(milestone.citations?.[index % (milestone.citations?.length || 1)]); }}><Quote size={14} /></button>
                  </div>
                )) : <div className="muted">No work list extracted.</div>}
              </div>
            </section>
            <section className="milestone-panel">
              <div className="milestone-panel-header"><h3>Acceptance Criteria</h3><button type="button" className="ghost-button square" onClick={() => selectedCitation && setCitation(selectedCitation)}><Quote size={14} /></button></div>
              <ul className="criteria-list">
                {(milestone.acceptance_criteria || "Not extracted.").split(/[。\n]/).filter(Boolean).map((line, index) => <li key={`${line}-${index}`}>{line}</li>)}
              </ul>
            </section>
          </div>
          <section className="milestone-panel wide">
            <div className="milestone-panel-header"><h3>Payment Conditions</h3><button type="button" className="ghost-button square" onClick={() => selectedCitation && setCitation(selectedCitation)}><Quote size={14} /></button></div>
            <p className="payment-condition-copy">{milestone.payment_condition || "Not extracted."}</p>
            {selectedCitation?.text_snippet ? <mark>{selectedCitation.text_snippet}</mark> : null}
          </section>
        </div>
        <aside className="evidence-panel">
          <div className="evidence-header"><h3>Citation Evidence</h3></div>
          {selectedCitation ? (
            <div className="evidence-body">
              <div className="evidence-file">{selectedCitation.source_file}</div>
              <div className="evidence-grid">
                <div><span className="label-caps">Location</span><strong>Page {selectedCitation.page_estimate}, Para {selectedCitation.para_start}-{selectedCitation.para_end}</strong></div>
                <div><span className="label-caps">Block ID</span><strong>{selectedCitation.block_id}</strong></div>
              </div>
              <div>
                <span className="label-caps">Extraction Method</span>
                <div className="evidence-badge">{selectedCitation.extraction_method}</div>
              </div>
              <div className="evidence-source">
                <span className="label-caps">Source Text</span>
                <div className="evidence-excerpt">{selectedCitation.text_snippet}</div>
              </div>
              <div className="audit-rail">
                <div className="timeline-entry"><strong>Extracted by system</strong><span>{selectedCitation.field_name}</span></div>
                <div className="timeline-entry"><strong>Document uploaded</strong><span>{contract?.source_file || milestone.contract_id}</span></div>
              </div>
              <div className="evidence-footer">
                <button type="button" className="ghost-button">Report Issue</button>
                <button type="button" onClick={() => setCitation(selectedCitation)}>Verify Link</button>
              </div>
            </div>
          ) : <div className="muted">No citation selected.</div>}
        </aside>
      </div>
    </div>
  );
}
