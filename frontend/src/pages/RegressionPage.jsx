import { useEffect, useMemo, useRef, useState } from "react";
import { Download, Play, Square } from "lucide-react";
import { api, formatDate } from "../api/client.js";
import { ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { useI18n } from "../i18n.jsx";

const STORAGE_KEY = "regression-runner-state-v1";
const RESET_MARKER_KEY = "regression-reset-marker-v1";

const promptSets = {
  core: [
    { id: "Q1", label: "Contract overview", prompt: "這份文件主要是在規範什麼？請用 3 到 5 點整理重點。" },
    { id: "Q2", label: "Payment structure", prompt: "這份文件的付款方式是什麼？如果有分期付款，請列出每一期的條件、比例與金額。" },
    { id: "Q3", label: "Acceptance / completion", prompt: "這份文件對於完工、驗收或核定的條件是什麼？請整理成條列。" },
    { id: "Q4", label: "Delay remedies", prompt: "如果乙方進度落後或遲延履約，甲方可以採取哪些行動？" },
    { id: "Q5", label: "Risk summary", prompt: "這份文件對乙方最主要的風險是什麼？請列出 3 到 6 點。" },
    { id: "Q6", label: "Price adjustment / tariff", prompt: "如果因關稅變動、法令變更或政策變更導致成本上升，乙方可以要求調整合約總價嗎？" },
    { id: "Q7", label: "Force majeure", prompt: "哪些情況可以主張不可抗力？關稅或貿易政策變動算不算？" },
    { id: "Q8", label: "Subcontracting / assignment", prompt: "乙方可不可以轉包、分包或轉讓契約權利義務？如果違反，後果是什麼？" },
    { id: "Q9", label: "English overview", prompt: "What is this document about? Summarize it in 4 concise bullet points." },
    { id: "Q10", label: "English risk", prompt: "What are the main contractor-side risks in this document?" },
  ],
  varied: [
    { id: "V1", label: "Plain-language overview", prompt: "用白話說明，這份文件到底是在做什麼？只抓最重要的 3 到 5 點。" },
    { id: "V2", label: "Direct total and count", prompt: "這份文件的總金額是多少？有幾期付款或幾個里程碑？" },
    { id: "V3", label: "Acceptance trigger phrasing", prompt: "要到什麼程度才算完成、驗收通過或可以往下一步走？" },
    { id: "V4", label: "What can Party A do", prompt: "如果承包商做太慢、進度拖延或沒有照要求做，甲方實際可以怎麼處理？" },
    { id: "V5", label: "Contractor downside", prompt: "如果我是乙方，這份文件裡最容易踩雷的地方是什麼？" },
    { id: "V6", label: "Can price go up", prompt: "如果後面成本變高，例如關稅、政策或法規改變，乙方還能不能要求加價？" },
    { id: "V7", label: "Does force majeure help", prompt: "如果碰到天災、政策改變、關稅變動，乙方可不可以主張不可抗力或免責？" },
    { id: "V8", label: "Can the work be handed off", prompt: "乙方能不能把工作交給別人做，像是分包、轉包，或把契約權利義務轉出去？" },
    { id: "V9", label: "English payment paraphrase", prompt: "How does payment actually work here? Include amount, milestone count, and what must happen before the vendor gets paid." },
    { id: "V10", label: "English remedy paraphrase", prompt: "If performance slips or the contractor falls behind schedule, what remedies does the other side have?" },
  ],
  full: [
    { id: "Q1", label: "Contract overview", prompt: "這份文件主要是在規範什麼？請用 3 到 5 點整理重點。" },
    { id: "Q2", label: "Payment structure", prompt: "這份文件的付款方式是什麼？如果有分期付款，請列出每一期的條件、比例與金額。" },
    { id: "Q3", label: "Acceptance / completion", prompt: "這份文件對於完工、驗收或核定的條件是什麼？請整理成條列。" },
    { id: "Q4", label: "Delay remedies", prompt: "如果乙方進度落後或遲延履約，甲方可以採取哪些行動？" },
    { id: "Q5", label: "Risk summary", prompt: "這份文件對乙方最主要的風險是什麼？請列出 3 到 6 點。" },
    { id: "Q6", label: "Price adjustment / tariff", prompt: "如果因關稅變動、法令變更或政策變更導致成本上升，乙方可以要求調整合約總價嗎？" },
    { id: "Q7", label: "Force majeure", prompt: "哪些情況可以主張不可抗力？關稅或貿易政策變動算不算？" },
    { id: "Q8", label: "Subcontracting / assignment", prompt: "乙方可不可以轉包、分包或轉讓契約權利義務？如果違反，後果是什麼？" },
    { id: "Q9", label: "English overview", prompt: "What is this document about? Summarize it in 4 concise bullet points." },
    { id: "Q10", label: "English risk", prompt: "What are the main contractor-side risks in this document?" },
    { id: "Q11", label: "Payment deadline", prompt: "甲方付款的期限是什麼？乙方請款時需要具備哪些前提或文件？" },
    { id: "Q12", label: "Milestone detail probe", prompt: "請逐期說明付款里程碑，不要省略每一期的條件、比例、金額與付款期限。" },
    { id: "Q13", label: "Progress threshold probe", prompt: "如果乙方工程進度落後超過百分之五，甲方可以採取哪些行動？" },
    { id: "Q14", label: "Severe delay probe", prompt: "如果乙方進度落後 25% 且超過十天，甲方可以採取哪些行動？" },
  ],
};

function loadSavedState() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function saveState(state) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function RegressionPage() {
  const { t } = useI18n();
  const stopRef = useRef(false);
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedContractIds, setSelectedContractIds] = useState([]);
  const [promptSetKey, setPromptSetKey] = useState("core");
  const [runnerMode, setRunnerMode] = useState("generation");
  const [topK, setTopK] = useState(10);
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState([]);
  const [currentTask, setCurrentTask] = useState(null);

  function clearRegressionState({ preserveSelection = true } = {}) {
    setResults([]);
    setCurrentTask(null);
    if (!preserveSelection) {
      setSelectedContractIds([]);
      setPromptSetKey("core");
      setRunnerMode("generation");
      setTopK(10);
    }
    window.localStorage.removeItem(STORAGE_KEY);
  }

  useEffect(() => {
    const saved = loadSavedState();
    if (saved) {
      setSelectedContractIds(saved.selectedContractIds || []);
      setPromptSetKey(saved.promptSetKey || "core");
      setRunnerMode(saved.runnerMode || "generation");
      setTopK(saved.topK || 10);
      setResults(saved.results || []);
      setCurrentTask(saved.currentTask || null);
    }
  }, []);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const rows = await api.contracts();
        const sorted = [...rows].sort((a, b) => String(a.source_file || "").localeCompare(String(b.source_file || "")));
        setContracts(sorted);
        setSelectedContractIds((existing) => existing.length ? existing.filter((id) => sorted.some((item) => item.contract_id === id)) : sorted.map((item) => item.contract_id));
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.health().then((health) => {
      if (cancelled) return;
      const marker = health?.infrastructure?.reset_marker || null;
      const previous = window.localStorage.getItem(RESET_MARKER_KEY);
      if (marker && previous && marker !== previous) {
        clearRegressionState({ preserveSelection: false });
      }
      if (marker) {
        window.localStorage.setItem(RESET_MARKER_KEY, marker);
      }
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const promptSet = promptSets[promptSetKey] || promptSets.core;
  const selectedContracts = useMemo(
    () => contracts.filter((contract) => selectedContractIds.includes(contract.contract_id)),
    [contracts, selectedContractIds],
  );
  const totalRuns = selectedContracts.length * promptSet.length;
  const completedRuns = results.filter((item) => item.status === "completed" || item.status === "failed").length;

  useEffect(() => {
    saveState({ selectedContractIds, promptSetKey, runnerMode, topK, results, currentTask });
  }, [selectedContractIds, promptSetKey, runnerMode, topK, results, currentTask]);

  function toggleContract(contractId) {
    setSelectedContractIds((current) => current.includes(contractId) ? current.filter((id) => id !== contractId) : [...current, contractId]);
  }

  async function runRegression() {
    if (!selectedContracts.length || isRunning) return;
    stopRef.current = false;
    setIsRunning(true);
    setError(null);
    const nextResults = [];
    for (const contract of selectedContracts) {
      for (const prompt of promptSet) {
        if (stopRef.current) {
          setIsRunning(false);
          setCurrentTask(null);
          return;
        }
        const startedAt = new Date().toISOString();
        const baseRow = {
          runKey: `${contract.contract_id}:${prompt.id}`,
          contract_id: contract.contract_id,
          source_file: contract.source_file,
          contract_name: contract.contract_name,
          prompt_id: prompt.id,
          prompt_label: prompt.label,
          prompt: prompt.prompt,
          top_k: topK,
          status: "running",
          started_at: startedAt,
        };
        nextResults.push(baseRow);
        setCurrentTask(baseRow);
        setResults([...nextResults]);
        try {
          const payload = {
            query: prompt.prompt,
            contract_id: contract.contract_id,
            top_k: Number(topK) || 10,
            persist_to_wiki: false,
            persist_chat: false,
          };
          const response = runnerMode === "retrieval"
            ? await api.queryRetrievalOnly(payload)
            : await api.query(payload);
          Object.assign(baseRow, {
            status: "completed",
            finished_at: new Date().toISOString(),
            answer: response.answer || null,
            citations: response.citations || [],
            answer_method: response.answer_method,
            retrieval_mode: response.retrieval_mode,
            model_name: response.model_name,
            reranker_model_name: response.reranker_model_name || null,
            retrieval_confident: response.retrieval_confident,
            anchor_failure_reason: response.anchor_failure_reason || null,
            intents: response.intents || [],
            expanded_query: response.expanded_query || null,
            runner_mode: runnerMode,
          });
        } catch (err) {
          Object.assign(baseRow, {
            status: "failed",
            finished_at: new Date().toISOString(),
            error: err.message || String(err),
          });
        }
        setResults([...nextResults]);
      }
    }
    setCurrentTask(null);
    setIsRunning(false);
  }

  function stopRegression() {
    stopRef.current = true;
    setIsRunning(false);
    setCurrentTask(null);
  }

  function exportResults() {
    const blob = new Blob([JSON.stringify({
      exported_at: new Date().toISOString(),
      prompt_set: promptSetKey,
      runner_mode: runnerMode,
      top_k: topK,
      selected_contract_ids: selectedContractIds,
      results,
    }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `regression-results-${new Date().toISOString().slice(0, 19).replaceAll(":", "-")}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <LoadingBlock label={t("common.loadingData")} />;

  return (
    <div className="page-stack regression-screen">
      <ErrorBlock error={error} />
      <div className="panel">
        <div className="panel-header">
          <h2>{t("regression.title")}</h2>
          <div className="action-icons">
            <button type="button" className="ghost-button" onClick={runRegression} disabled={!selectedContracts.length || isRunning}>
              <Play size={16} />
              {t("regression.start")}
            </button>
            <button type="button" className="ghost-button" onClick={stopRegression} disabled={!isRunning}>
              <Square size={16} />
              {t("regression.stop")}
            </button>
            <button type="button" className="ghost-button" onClick={exportResults} disabled={!results.length}>
              <Download size={16} />
              {t("regression.export")}
            </button>
            <button type="button" className="ghost-button" onClick={() => clearRegressionState({ preserveSelection: false })} disabled={isRunning}>
              {t("regression.reset")}
            </button>
          </div>
        </div>
        <div className="panel-body regression-config">
          <div className="regression-grid">
            <label>
              <span className="label-caps">{t("regression.runnerMode")}</span>
              <select value={runnerMode} onChange={(event) => setRunnerMode(event.target.value)} disabled={isRunning}>
                <option value="generation">{t("regression.modeGeneration")}</option>
                <option value="retrieval">{t("regression.modeRetrieval")}</option>
              </select>
            </label>
            <label>
              <span className="label-caps">{t("regression.promptSet")}</span>
                  <select value={promptSetKey} onChange={(event) => setPromptSetKey(event.target.value)} disabled={isRunning}>
                    <option value="core">{t("regression.coreSet")}</option>
                    <option value="varied">{t("regression.variedSet")}</option>
                    <option value="full">{t("regression.fullSet")}</option>
                  </select>
                </label>
            <label>
              <span className="label-caps">{t("regression.topK")}</span>
              <input type="number" min="1" max="24" value={topK} onChange={(event) => setTopK(Number(event.target.value) || 10)} disabled={isRunning} />
            </label>
            <div className="regression-stat">
              <span className="label-caps">{t("regression.progress")}</span>
              <strong>{completedRuns}/{totalRuns || 0}</strong>
              {currentTask ? <small>{currentTask.source_file} {" · "} {currentTask.prompt_id}</small> : null}
            </div>
          </div>
          <div className="regression-contracts">
            {contracts.map((contract) => (
              <label key={contract.contract_id} className="regression-contract-option">
                <input
                  type="checkbox"
                  checked={selectedContractIds.includes(contract.contract_id)}
                  onChange={() => toggleContract(contract.contract_id)}
                  disabled={isRunning}
                />
                <span>{contract.source_file || contract.contract_name}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>{t("regression.results")}</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("regression.contract")}</th>
                <th>{t("regression.prompt")}</th>
                <th>{t("regression.status")}</th>
                <th>{t("regression.answer")}</th>
                <th>{t("regression.evidenceCount")}</th>
                <th>{t("regression.retrievalMode")}</th>
                <th>{t("regression.finishedAt")}</th>
              </tr>
            </thead>
            <tbody>
              {!results.length ? (
                <tr>
                  <td colSpan="7" className="muted">{t("regression.noResults")}</td>
                </tr>
              ) : results.map((row) => (
                <tr key={row.runKey}>
                  <td>
                    <strong>{row.source_file || row.contract_name}</strong>
                    <small>{row.contract_id}</small>
                  </td>
                  <td>
                    <strong>{row.prompt_id}</strong>
                    <small>{row.prompt_label}</small>
                  </td>
                  <td>{row.status}</td>
                  <td className="regression-answer-cell">
                    {row.error ? <span className="muted">{row.error}</span> : (row.answer || t("regression.retrievalOnlyResult"))}
                  </td>
                  <td>{row.citations?.length || 0}</td>
                  <td>{row.retrieval_mode || "-"}</td>
                  <td>{formatDate(row.finished_at || row.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
