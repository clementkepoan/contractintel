import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Send } from "lucide-react";
import { api, formatDate } from "../api/client.js";
import { useI18n } from "../i18n.jsx";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";

function renderInlineBold(text) {
  const parts = String(text || "").split(/(\*\*.*?\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

function MarkdownLite({ text }) {
  const lines = String(text || "").split("\n");
  const nodes = [];
  let listBuffer = [];

  function flushList(keyPrefix) {
    if (!listBuffer.length) return;
    nodes.push(
      <ul className="query-rich-list" key={`${keyPrefix}-${nodes.length}`}>
        {listBuffer.map((item, index) => <li key={index}>{renderInlineBold(item)}</li>)}
      </ul>
    );
    listBuffer = [];
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList("blank");
      return;
    }
    if (/^[-*]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      listBuffer.push(trimmed.replace(/^[-*]\s+/, "").replace(/^\d+\.\s+/, ""));
      return;
    }
    flushList("text");
    if (trimmed.startsWith("### ")) {
      nodes.push(<h4 className="query-rich-heading" key={index}>{renderInlineBold(trimmed.slice(4))}</h4>);
      return;
    }
    if (trimmed.startsWith("## ")) {
      nodes.push(<h3 className="query-rich-heading" key={index}>{renderInlineBold(trimmed.slice(3))}</h3>);
      return;
    }
    nodes.push(<p className="query-rich-paragraph" key={index}>{renderInlineBold(trimmed)}</p>);
  });
  flushList("final");
  return <div className="query-rich-copy">{nodes}</div>;
}

function EvidencePreview({ citations, setSelectedWikiPath, setPage, expanded, onToggle }) {
  const { t } = useI18n();
  if (!citations?.length) return null;
  const preview = expanded ? citations : citations.slice(0, 3);
  return (
    <div className="query-evidence-attachment">
      <button type="button" className="query-evidence-toggle" onClick={onToggle}>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {t("common.retrievedEvidence")} ({citations.length})
      </button>
      <div className="query-evidence-preview-list">
        {preview.map((citation, index) => (
          <article className="query-evidence-preview-card" key={`${citation.chunk_id || citation.block_id || "citation"}-${index}`}>
            <div className="query-evidence-preview-head">
              <strong>{citation.source_file || citation.chunk_type || "Evidence"}</strong>
              <small>{citation.clause_label || citation.structured_kind || citation.chunk_id || citation.block_id || "-"}</small>
            </div>
            <p>{citation.text_snippet}</p>
            {citation.source_path ? (
              <div className="query-evidence-preview-actions">
                <button type="button" className="ghost-button" onClick={() => { setSelectedWikiPath(citation.source_path); setPage("wiki"); }}>{t("common.openSourcePage")}</button>
                {citation.project_path ? <button type="button" className="ghost-button" onClick={() => { setSelectedWikiPath(citation.project_path); setPage("wiki"); }}>{t("common.openProjectPage")}</button> : null}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

export function QueryPage({ contractId, setSelectedContractId, setSelectedWikiPath, setPage }) {
  const { t } = useI18n();
  const [contracts, setContracts] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [turns, setTurns] = useState([]);
  const [chatSessionId, setChatSessionId] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(10);
  const [persistToWiki, setPersistToWiki] = useState(true);
  const [result, setResult] = useState(null);
  const [expandedEvidence, setExpandedEvidence] = useState({});
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState(null);

  function startNewSession() {
    setChatSessionId("");
    setTurns([]);
    setResult(null);
    setExpandedEvidence({});
    setError(null);
    setQuery("");
  }

  async function loadBase() {
    setLoading(true);
    setError(null);
    try {
      const [contractList, sessionList] = await Promise.all([api.contracts(), api.chatSessions()]);
      setContracts(contractList);
      setSessions(sessionList);
      if (!contractId && contractList[0]) setSelectedContractId(contractList[0].contract_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  async function loadSessionArtifacts(nextSessionId) {
    if (!nextSessionId) {
      setTurns([]);
      setResult(null);
      return;
    }
    try {
      const [turnList, latestQuery] = await Promise.all([
        api.chatSessionTurns(nextSessionId),
        api.chatSessionLatestQuery(nextSessionId),
      ]);
      setTurns(turnList);
      setResult(latestQuery);
      if (latestQuery?.contract_id) {
        setSelectedContractId(latestQuery.contract_id);
      }
    } catch (err) {
      setError(err);
    }
  }

  useEffect(() => {
    loadBase();
  }, []);

  useEffect(() => {
    loadSessionArtifacts(chatSessionId);
  }, [chatSessionId]);

  async function ask(event) {
    event.preventDefault();
    if (!query.trim()) return;
    setAsking(true);
    setError(null);
    try {
      const payload = await api.query({
        query,
        top_k: Number(topK),
        contract_id: contractId || null,
        chat_session_id: chatSessionId || null,
        persist_to_wiki: persistToWiki,
      });
      setQuery("");
      setChatSessionId(payload.chat_session_id);
      const [sessionList, turnList, latestQuery] = await Promise.all([
        api.chatSessions(),
        api.chatSessionTurns(payload.chat_session_id),
        api.chatSessionLatestQuery(payload.chat_session_id),
      ]);
      setSessions(sessionList);
      setTurns(turnList);
      setResult(latestQuery || payload);
    } catch (err) {
      setError(err);
    } finally {
      setAsking(false);
    }
  }

  const orderedTurns = useMemo(() => turns, [turns]);

  if (loading) return <LoadingBlock label={t("common.loadingData")} />;

  return (
    <div className="query-screen">
      <ErrorBlock error={error} />
      <div className="query-left-rail">
        <div className="session-history-card">
          <div className="session-history-head">
            <h3>{t("query.sessionHistory")}</h3>
            <button type="button" className="ghost-button" onClick={startNewSession}>
              {t("query.newSession")}
            </button>
          </div>
          {sessions.length ? sessions.map((session) => (
            <button
              key={session.chat_session_id}
              type="button"
              className={chatSessionId === session.chat_session_id ? "session-history-item active" : "session-history-item"}
              onClick={() => setChatSessionId(session.chat_session_id)}
            >
              <span className="label-caps">{session.chat_session_id} · {formatDate(session.updated_at)}</span>
              <strong>{session.title || session.chat_session_id}</strong>
            </button>
          )) : <EmptyBlock label={t("query.noSessions")} />}
        </div>
      </div>
      <div className="query-main-panel">
        <section className="query-thread">
          {orderedTurns.length ? orderedTurns.map((turn, index) => {
            const evidenceOpen = expandedEvidence[index] || false;
            return (
              <div className="query-turn" key={`turn-${index}`}>
                {turn.question ? (
                  <article className="query-message query-message-user">
                    <div className="query-message-label">{t("common.userQuestion")}</div>
                    <div className="query-message-copy">{turn.question}</div>
                  </article>
                ) : null}
                {turn.answer ? (
                  <article className="query-message query-message-ai">
                    <div className="query-message-label">{t("common.aiAnalysis")}</div>
                    <MarkdownLite text={turn.answer} />
                    <div className="analysis-meta">
                      <span>Mode: {turn.retrieval_mode || "-"}</span>
                      <span>Model: {turn.model_name || result?.model_name || "-"}</span>
                      <span>Session ID: {chatSessionId || "-"}</span>
                      {turn.wiki_path ? (
                        <button type="button" className="ghost-button" onClick={() => { setSelectedWikiPath(turn.wiki_path); setPage("wiki"); }}>
                          {t("common.openWikiNote")}
                        </button>
                      ) : null}
                    </div>
                    <EvidencePreview
                      citations={turn.citations || []}
                      setSelectedWikiPath={setSelectedWikiPath}
                      setPage={setPage}
                      expanded={evidenceOpen}
                      onToggle={() => setExpandedEvidence((state) => ({ ...state, [index]: !state[index] }))}
                    />
                  </article>
                ) : null}
              </div>
            );
          }) : <EmptyBlock label={t("query.startSession")} />}
        </section>
        <form className="query-composer" onSubmit={ask}>
          <div className="composer-toolbar">
            <select value={contractId || ""} onChange={(event) => setSelectedContractId(event.target.value || "")}>
              <option value="">{t("query.allContracts")}</option>
              {contracts.map((item) => (
                <option key={item.contract_id} value={item.contract_id}>
                  {item.source_file || item.contract_name}
                </option>
              ))}
            </select>
            <label>{t("query.topK")}: {topK}<input type="range" min="1" max="12" value={topK} onChange={(event) => setTopK(event.target.value)} /></label>
            <span className="composer-hybrid">{t("query.llmQuery")}</span>
            <label className="composer-toggle"><input type="checkbox" checked={persistToWiki} onChange={(event) => setPersistToWiki(event.target.checked)} /> {t("query.fileAnswerToWiki")}</label>
          </div>
          <div className="composer-input-row">
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("query.askPlaceholder")} />
            <button type="submit" disabled={asking}><Send size={18} /> {t("query.runQuery")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
