import { useEffect, useState } from "react";
import { CheckCheck } from "lucide-react";
import { api, formatMoney } from "../api/client.js";
import { useI18n } from "../i18n.jsx";
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
  const { t } = useI18n();
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

  if (loading) return <LoadingBlock label={t("common.loadingData")} />;

  return (
    <div className="page-stack">
      <ErrorBlock error={error} />
      <div className="workflow-layout">
        <div className="page-stack">
          <div className="workflow-headline">
            <div>
              <h2 className="page-title">{t("workflow.title")}</h2>
              <p className="page-subtitle">{t("workflow.subtitle")}</p>
            </div>
            <select value={contract?.contract_id || ""} onChange={(event) => { setSelectedContractId(event.target.value); load(event.target.value); }}>
              {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
            </select>
          </div>
          <div className="workflow-board">
            <section className="workflow-section">
              <div className="workflow-section-header"><h3>{t("workflow.pendingAcceptance")}</h3></div>
              {buckets.pending.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status={workflow[milestone.milestone_id]?.status || milestone.status} /></div>
                  <div><button type="button" onClick={() => setActiveMilestoneId(milestone.milestone_id)}>{t("workflow.recordAcceptance")}</button></div>
                </div>
              ))}
            </section>
            <section className="workflow-section">
              <div className="workflow-section-header"><h3>{t("workflow.acceptedAwaitingRequest")}</h3></div>
              {buckets.accepted.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status="accepted" /></div>
                  <div><button type="button" className="ghost-button" onClick={() => setActiveMilestoneId(milestone.milestone_id)}>{t("workflow.requestPayment")}</button></div>
                </div>
              ))}
            </section>
            <section className="workflow-section">
              <div className="workflow-section-header"><h3>{t("workflow.paymentRequested")}</h3></div>
              {buckets.requested.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status="payment_requested" /></div>
                  <div><button type="button" className="ghost-button" onClick={() => setActiveMilestoneId(milestone.milestone_id)}>{t("workflow.logPayment")}</button></div>
                </div>
              ))}
            </section>
            <section className="workflow-section muted-section">
              <div className="workflow-section-header"><h3>{t("workflow.paymentMadeClosed")}</h3></div>
              {buckets.paid.map((milestone) => (
                <div className="workflow-row" key={milestone.milestone_id}>
                  <div><strong>{milestone.name}</strong></div>
                  <div>{formatMoney(milestone.amount, contract.currency)}</div>
                  <div><StatusBadge status="paid" /></div>
                  <div><button type="button" disabled>{t("workflow.complete")}</button></div>
                </div>
              ))}
            </section>
          </div>
        </div>
        <aside className="workflow-sidecard">
          <section className="financial-summary-card">
            <h3>{t("workflow.financialSummary")}</h3>
            <div className="financial-summary-grid">
              <div><span>{t("workflow.totalContract")}</span><strong>{formatMoney(financials?.total_amount, contract?.currency)}</strong></div>
              <div><span>{t("workflow.unpaidBalance")}</span><strong>{formatMoney(financials?.unpaid, contract?.currency)}</strong></div>
              <div><span>{t("workflow.totalRequested")}</span><strong>{formatMoney(financials?.payment_requested, contract?.currency)}</strong></div>
              <div><span>{t("workflow.totalPaid")}</span><strong>{formatMoney(financials?.paid, contract?.currency)}</strong></div>
            </div>
          </section>
          {activeMilestone ? (
            <section className="acceptance-form-card">
              <div className="acceptance-form-header"><h3>{t("workflow.recordAcceptancePanel")}</h3></div>
              <div className="selected-milestone-card">
                <span className="label-caps">{t("workflow.selectedMilestone")}</span>
                <strong>{activeMilestone.name}</strong>
                <small>{formatMoney(activeMilestone.amount, contract.currency)}</small>
              </div>
              <div className="acceptance-radio-row">
                <button type="button" className={form.passed ? "radio-panel active" : "radio-panel"} onClick={() => setForm({ ...form, passed: true })}>{t("workflow.pass")}</button>
                <button type="button" className={!form.passed ? "radio-panel danger active" : "radio-panel danger"} onClick={() => setForm({ ...form, passed: false })}>{t("workflow.fail")}</button>
              </div>
              <input placeholder={t("workflow.inspectorPlaceholder")} value={form.inspector_name} onChange={(event) => setForm({ ...form, inspector_name: event.target.value })} />
              <textarea placeholder={t("workflow.notesPlaceholder")} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
              <input type="number" placeholder={t("workflow.requestedAmountPlaceholder")} value={form.requested_amount} onChange={(event) => setForm({ ...form, requested_amount: event.target.value })} />
              <select value={form.payment_request_id} onChange={(event) => setForm({ ...form, payment_request_id: event.target.value })}>
                <option value="">{t("workflow.selectPaymentRequest")}</option>
                {(activeWorkflow.payment_requests || []).map((request) => <option key={request.id} value={request.id}>#{request.id} · {formatMoney(request.requested_amount, contract.currency)}</option>)}
              </select>
              <input type="number" placeholder={t("workflow.paidAmountPlaceholder")} value={form.paid_amount} onChange={(event) => setForm({ ...form, paid_amount: event.target.value })} />
              <div className="workflow-submit-row">
                <button type="button" onClick={submitAcceptance}><CheckCheck size={16} /> {t("workflow.submitRecord")}</button>
                <button type="button" className="ghost-button" disabled={!hasAcceptance || !form.requested_amount} onClick={submitPaymentRequest}>{t("workflow.requestPayment")}</button>
                <button type="button" className="ghost-button" disabled={!form.payment_request_id || !form.paid_amount} onClick={submitPayment}>{t("workflow.logPayment")}</button>
              </div>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
