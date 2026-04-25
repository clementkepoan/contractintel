import { useEffect, useState } from "react";
import { History, Paperclip, Search, Send } from "lucide-react";
import { api, formatDate } from "../api/client.js";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";

export function QueryPage({ contractId, setSelectedContractId }) {
  const [contracts, setContracts] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [messages, setMessages] = useState([]);
  const [chatSessionId, setChatSessionId] = useState("");
  const [query, setQuery] = useState("What are the specific limitation of liability caps mentioned across our standard MSAs?");
  const [topK, setTopK] = useState(5);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
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

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!chatSessionId) {
      setMessages([]);
      return;
    }
    api.chatMessages(chatSessionId).then(setMessages).catch(setError);
  }, [chatSessionId]);

  async function ask(event) {
    event.preventDefault();
    if (!query.trim()) return;
    setAsking(true);
    setError(null);
    try {
      const payload = await api.query({ query, top_k: Number(topK), contract_id: contractId || null, chat_session_id: chatSessionId || null });
      setResult(payload);
      setChatSessionId(payload.chat_session_id);
      const [sessionList, messageList] = await Promise.all([api.chatSessions(), api.chatMessages(payload.chat_session_id)]);
      setSessions(sessionList);
      setMessages(messageList);
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
          <input type="text" placeholder="Global search..." />
        </label>
        <div className="session-history-card">
          <h3>Session History</h3>
          {sessions.length ? sessions.map((session) => (
            <button key={session.chat_session_id} type="button" className={chatSessionId === session.chat_session_id ? "session-history-item active" : "session-history-item"} onClick={() => setChatSessionId(session.chat_session_id)}>
              <span className="label-caps">{session.chat_session_id} · {formatDate(session.updated_at)}</span>
              <strong>{session.title || session.chat_session_id}</strong>
            </button>
          )) : <EmptyBlock label="No chat sessions yet." />}
        </div>
      </div>
      <div className="query-main-panel">
        <div className="query-prompt-bubble">{query}</div>
        <section className="analysis-card">
          <div className="analysis-label"><History size={14} /> AI Analysis</div>
          <div className="analysis-copy">
            <p>{result?.answer || messages.findLast?.((message) => message.role === "ai")?.content || "Run a query to retrieve evidence-backed analysis."}</p>
          </div>
          <div className="analysis-meta">
            <span>Mode: {result?.retrieval_mode || "-"}</span>
            <span>Model: qwen2.5</span>
            <span>Session ID: {result?.chat_session_id || chatSessionId || "-"}</span>
          </div>
        </section>
        <section className="evidence-stack">
          <p className="label-caps">Retrieved Evidence</p>
          {(result?.citations || []).map((citation, index) => (
            <article className="evidence-result-card" key={`${citation.block_id}-${index}`}>
              <div className="evidence-result-head">
                <div className="evidence-title-row">
                  <span className="evidence-rank">R-{String(index + 1).padStart(2, "0")}</span>
                  <strong>{citation.source_file}</strong>
                  <small>{citation.block_id}</small>
                </div>
                <div className="evidence-score">Score · {citation.page_estimate || "-"}</div>
              </div>
              <div className="evidence-result-body">{citation.text_snippet}</div>
            </article>
          ))}
        </section>
        <form className="query-composer" onSubmit={ask}>
          <div className="composer-toolbar">
            <select value={contractId || ""} onChange={(event) => setSelectedContractId(event.target.value || "")}>
              <option value="">All Contracts</option>
              {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
            </select>
            <label>Top K Results: {topK}<input type="range" min="1" max="10" value={topK} onChange={(event) => setTopK(event.target.value)} /></label>
            <span className="composer-hybrid">Hybrid Search</span>
          </div>
          <div className="composer-input-row">
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask a question about the filtered contracts..." />
            <button type="submit" disabled={asking}><Send size={18} /> Run Query</button>
          </div>
          <div className="composer-icons"><Paperclip size={16} /><History size={16} /></div>
        </form>
      </div>
    </div>
  );
}
