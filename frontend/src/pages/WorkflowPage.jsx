import { useEffect, useState } from "react";
import { CheckCheck } from "lucide-react";
import { api, formatMoney } from "../api/client.js";
import { ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

function bucketMilestones(milestones = [], workflowMap = {}) {
  return {
    pending: milestones.filter((item) => !["accepted", "payment_requested", "paid"].includes(workflowMap[item.milestone_id]?.status || item.status)),
    accepted: milestones.filter((item) => (workflowMap[item.milestone_id]?.status || item.status) === "accepted"),
    requested: milestones.filter((item) => (workflowMap[item.milestone_id]?.status || item.status) === "payment_requested"),
    paid: milestones.filter((item) => (workflowMap[item.milestone_id]?.status || item.status) === "paid"),
  };
}

export function WorkflowPage({ contractId, setSelectedContractId }) {
  const [contracts, setContracts] = useState([]);
  const [contract, setContract] = useState(null);
  const [financials, setFinancials] = useState(null);
  const [workflow, setWorkflow] = useState({});
  const [activeMilestoneId, setActiveMilestoneId] = useState("");
  const [form, setForm] = useState({ inspector_name: "", notes: "", requested_amount: "", payment_request_id: "", paid_amount: "", remarks: "", passed: true });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load(activeContractId = contractId) {
    setLoading(true);
    setError(null);
    try {
      const list = await api.contracts();
      setContracts(list);
      const selected = activeContractId || list[0]?.contract_id;
      if (!selected) return;
      setSelectedContractId(selected);
      const [detail, totals] = await Promise.all([api.contract(selected), api.financials(selected)]);
      setContract(detail);
      setFinancials(totals);
      const histories = await Promise.allSettled((detail.milestones || []).map((milestone) => api.workflow(milestone.milestone_id)));
      const mapped = Object.fromEntries(histories.filter((item) => item.status === "fulfilled").map((item) => [item.value.milestone_id, item.value]));
      setWorkflow(mapped);
      const first = detail.milestones?.[0]?.milestone_id || "";
      setActiveMilestoneId((current) => current || first);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [contractId]);

  const activeMilestone = contract?.milestones?.find((item) => item.milestone_id === activeMilestoneId);
  const activeWorkflow = workflow[activeMilestoneId] || {};
  const hasAcceptance = activeWorkflow.acceptance_records?.some((record) => record.passed);
  const buckets = bucketMilestones(contract?.milestones || [], workflow);

  async function submitAcceptance() {
    await api.accept({ milestone_id: activeMilestoneId, passed: form.passed, inspector_name: form.inspector_name || null, notes: form.notes || null });
    await load(contract.contract_id);
  }

  async function submitPaymentRequest() {
    const result = await api.requestPayment({ milestone_id: activeMilestoneId, requested_amount: Number(form.requested_amount), remarks: form.remarks || null });
    setForm((current) => ({ ...current, payment_request_id: String(result.id) }));
    await load(contract.contract_id);
  }

  async function submitPayment() {
    await api.logPayment({ payment_request_id: Number(form.payment_request_id), paid_amount: Number(form.paid_amount), remarks: form.remarks || null });
    await load(contract.contract_id);
  }

  if (loading) return <LoadingBlock />;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="workflow-layout">
        <div className="page-stack">
          <div className="workflow-headline">
            <div>
              <h2 className="page-title">Payment Workflow</h2>
              <p className="page-subtitle">Track project milestones, record physical acceptance, and manage payment requests inline.</p>
            </div>
            <select value={contract?.contract_id || ""} onChange={(event) => { setSelectedContractId(event.target.value); load(event.target.value); }}>
              {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
            </select>
          </div>
          <div className="workflow-board">
            <section className="workflow-section">
              <div className="workflow-section-header"><h3>Pending Acceptance</h3></div>
              {buckets.pending.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status={workflow[milestone.milestone_id]?.status || milestone.status} /></div>
                  <div><button type="button" onClick={() => setActiveMilestoneId(milestone.milestone_id)}>Record Acceptance</button></div>
                </div>
              ))}
            </section>
            <section className="workflow-section">
              <div className="workflow-section-header"><h3>Accepted (Awaiting Request)</h3></div>
              {buckets.accepted.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status="accepted" /></div>
                  <div><button type="button" className="ghost-button" onClick={() => setActiveMilestoneId(milestone.milestone_id)}>Request Payment</button></div>
                </div>
              ))}
            </section>
            <section className="workflow-section">
              <div className="workflow-section-header"><h3>Payment Requested</h3></div>
              {buckets.requested.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status="payment_requested" /></div>
                  <div><button type="button" className="ghost-button" onClick={() => setActiveMilestoneId(milestone.milestone_id)}>Log Payment</button></div>
                </div>
              ))}
            </section>
            <section className="workflow-section muted-section">
              <div className="workflow-section-header"><h3>Payment Made (Closed)</h3></div>
              {buckets.paid.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status="paid" /></div>
                  <div><button type="button" disabled>Complete</button></div>
                </div>
              ))}
            </section>
          </div>
        </div>
        <aside className="workflow-sidecard">
          <section className="financial-summary-card">
            <h3>Financial Summary</h3>
            <div className="financial-summary-grid">
              <div><span>Total Contract</span><strong>{formatMoney(financials?.total_amount, contract?.currency)}</strong></div>
              <div><span>Unpaid Balance</span><strong>{formatMoney(financials?.unpaid, contract?.currency)}</strong></div>
              <div><span>Total Requested</span><strong>{formatMoney(financials?.payment_requested, contract?.currency)}</strong></div>
              <div><span>Total Paid</span><strong>{formatMoney(financials?.paid, contract?.currency)}</strong></div>
            </div>
          </section>
          {activeMilestone ? (
            <section className="acceptance-form-card">
              <div className="acceptance-form-header"><h3>Record Acceptance</h3></div>
              <div className="selected-milestone-card">
                <span className="label-caps">Selected Milestone</span>
                <strong>{activeMilestone.name}</strong>
                <small>{formatMoney(activeMilestone.amount, contract.currency)}</small>
              </div>
              <div className="acceptance-radio-row">
                <button type="button" className={form.passed ? "radio-panel active" : "radio-panel"} onClick={() => setForm({ ...form, passed: true })}>Pass</button>
                <button type="button" className={!form.passed ? "radio-panel danger active" : "radio-panel danger"} onClick={() => setForm({ ...form, passed: false })}>Fail</button>
              </div>
              <input placeholder="e.g., J. Doe" value={form.inspector_name} onChange={(event) => setForm({ ...form, inspector_name: event.target.value })} />
              <textarea placeholder="Enter technical observations..." value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
              <input type="number" placeholder="Requested amount" value={form.requested_amount} onChange={(event) => setForm({ ...form, requested_amount: event.target.value })} />
              <select value={form.payment_request_id} onChange={(event) => setForm({ ...form, payment_request_id: event.target.value })}>
                <option value="">Select payment request</option>
                {(activeWorkflow.payment_requests || []).map((request) => <option key={request.id} value={request.id}>#{request.id} · {formatMoney(request.requested_amount, contract.currency)}</option>)}
              </select>
              <input type="number" placeholder="Paid amount" value={form.paid_amount} onChange={(event) => setForm({ ...form, paid_amount: event.target.value })} />
              <div className="workflow-submit-row">
                <button type="button" onClick={submitAcceptance}><CheckCheck size={16} /> Submit Record</button>
                <button type="button" className="ghost-button" disabled={!hasAcceptance || !form.requested_amount} onClick={submitPaymentRequest}>Request Payment</button>
                <button type="button" className="ghost-button" disabled={!form.payment_request_id || !form.paid_amount} onClick={submitPayment}>Log Payment</button>
              </div>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
