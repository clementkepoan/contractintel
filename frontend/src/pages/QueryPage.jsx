import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, History, Search, Send } from "lucide-react";
import { api, formatDate } from "../api/client.js";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";

function EvidencePreview({ citations, setSelectedWikiPath, setPage, expanded, onToggle }) {
  if (!citations?.length) return null;
  const preview = expanded ? citations : citations.slice(0, 3);
  return (
    <div className="query-evidence-attachment">
      <button type="button" className="query-evidence-toggle" onClick={onToggle}>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        Retrieved Evidence ({citations.length})
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
                <button type="button" className="ghost-button" onClick={() => { setSelectedWikiPath(citation.source_path); setPage("wiki"); }}>Open Source Page</button>
                {citation.project_path ? <button type="button" className="ghost-button" onClick={() => { setSelectedWikiPath(citation.project_path); setPage("wiki"); }}>Open Project Page</button> : null}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

export function QueryPage({ contractId, setSelectedContractId, setSelectedWikiPath, setPage }) {
  const [contracts, setContracts] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [turns, setTurns] = useState([]);
  const [chatSessionId, setChatSessionId] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(12);
  const [persistToWiki, setPersistToWiki] = useState(true);
  const [result, setResult] = useState(null);
  const [expandedEvidence, setExpandedEvidence] = useState({});
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState(null);

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

  if (loading) return <LoadingBlock />;

  return (
    <div className="query-screen">
      <ErrorBlock error={error} />
      <div className="query-left-rail">
        <label className="query-search-shell">
          <Search size={18} />
          <input type="text" placeholder="Session search unavailable" disabled />
        </label>
        <div className="session-history-card">
          <h3>Session History</h3>
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
          )) : <EmptyBlock label="No chat sessions yet." />}
        </div>
      </div>
      <div className="query-main-panel">
        <section className="query-thread">
          {turns.length ? turns.map((turn, index) => {
            const isLatestAnswer = turn.query_id === result?.query_id;
            const evidenceOpen = expandedEvidence[index] || false;
            return (
              <div className="query-turn" key={`turn-${index}`}>
                {turn.question ? (
                  <article className="query-message query-message-user">
                    <div className="query-message-label">User Question</div>
                    <div className="query-message-copy">{turn.question}</div>
                  </article>
                ) : null}
                {turn.answer ? (
                  <article className="query-message query-message-ai">
                    <div className="query-message-label">AI Analysis</div>
                    <div className="query-message-copy">{turn.answer}</div>
                    <div className="analysis-meta">
                      <span>Mode: {turn.retrieval_mode || "-"}</span>
                      <span>Model: {turn.model_name || result?.model_name || "-"}</span>
                      <span>Session ID: {chatSessionId || "-"}</span>
                      {turn.wiki_path ? (
                        <button type="button" className="ghost-button" onClick={() => { setSelectedWikiPath(turn.wiki_path); setPage("wiki"); }}>
                          Open Wiki Note
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
          }) : <EmptyBlock label="Run a query to start a session." />}
        </section>
        <form className="query-composer" onSubmit={ask}>
          <div className="composer-toolbar">
            <select value={contractId || ""} onChange={(event) => setSelectedContractId(event.target.value || "")}>
              <option value="">All Contracts</option>
              {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
            </select>
            <label>Top K Results: {topK}<input type="range" min="1" max="12" value={topK} onChange={(event) => setTopK(event.target.value)} /></label>
            <span className="composer-hybrid">LLM Query</span>
            <label className="composer-toggle"><input type="checkbox" checked={persistToWiki} onChange={(event) => setPersistToWiki(event.target.checked)} /> File answer into wiki</label>
          </div>
          <div className="composer-input-row">
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask a question about the filtered contracts..." />
            <button type="submit" disabled={asking}><Send size={18} /> Run Query</button>
          </div>
        </form>
      </div>
    </div>
  );
}
