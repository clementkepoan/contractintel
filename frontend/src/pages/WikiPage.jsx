import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BookOpen, Clock3, FileText, FolderOpen, Network, Search, Sparkles } from "lucide-react";
import { api } from "../api/client.js";
import { useI18n } from "../i18n.jsx";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";

function normalizeWikiPath(currentPath, href) {
  if (!href || href.startsWith("http://") || href.startsWith("https://") || href.startsWith("#")) return null;
  const cleaned = href.replace(/\\/g, "/");
  const base = currentPath.includes("/") ? currentPath.split("/").slice(0, -1) : [];
  const stack = cleaned.startsWith("/") ? [] : [...base];
  for (const part of cleaned.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      stack.pop();
      continue;
    }
    stack.push(part);
  }
  return stack.join("/");
}

function renderInline(text, currentPath, onNavigate) {
  const pieces = [];
  let cursor = 0;
  const linkPattern = /\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*/g;
  let match;
  while ((match = linkPattern.exec(text)) !== null) {
    if (match.index > cursor) pieces.push(text.slice(cursor, match.index));
    if (match[1] && match[2]) {
      const target = normalizeWikiPath(currentPath, match[2]);
      pieces.push(
        <button
          type="button"
          key={`${match.index}-${match[2]}`}
          className="wiki-inline-link"
          onClick={() => target && onNavigate(target)}
        >
          {match[1]}
        </button>,
      );
    } else if (match[3]) {
      pieces.push(<strong key={`${match.index}-strong`}>{match[3]}</strong>);
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) pieces.push(text.slice(cursor));
  return pieces;
}

function MarkdownView({ content, currentPath, onNavigate }) {
  const { t } = useI18n();
  if (!content) return <EmptyBlock label={t("wiki.selectPage")} />;
  const lines = content.split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }
    if (trimmed.startsWith("### ")) {
      blocks.push(<h3 key={`h3-${index}`}>{trimmed.slice(4)}</h3>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      blocks.push(<h2 key={`h2-${index}`}>{trimmed.slice(3)}</h2>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      blocks.push(<h1 key={`h1-${index}`}>{trimmed.slice(2)}</h1>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith(">")) {
      const quote = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quote.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${index}`}>{quote.map((item, quoteIndex) => <p key={`${item}-${quoteIndex}`}>{renderInline(item, currentPath, onNavigate)}</p>)}</blockquote>);
      continue;
    }
    if (trimmed.startsWith("|") && lines[index + 1]?.trim().startsWith("|---")) {
      const tableLines = [trimmed];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        tableLines.push(lines[index].trim());
        index += 1;
      }
      const [header, ...rows] = tableLines.map((row) => row.split("|").slice(1, -1).map((cell) => cell.trim()));
      blocks.push(
        <div className="wiki-table-wrap" key={`table-${index}`}>
          <table className="wiki-markdown-table">
            <thead>
              <tr>{header.map((cell) => <th key={cell}>{renderInline(cell, currentPath, onNavigate)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => <tr key={`row-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`cell-${rowIndex}-${cellIndex}`}>{renderInline(cell, currentPath, onNavigate)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (trimmed.startsWith("- ") || /^\d+\.\s/.test(trimmed)) {
      const ordered = /^\d+\.\s/.test(trimmed);
      const items = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        if (ordered && /^\d+\.\s/.test(current)) {
          items.push(current.replace(/^\d+\.\s/, ""));
          index += 1;
          continue;
        }
        if (!ordered && current.startsWith("- ")) {
          items.push(current.slice(2));
          index += 1;
          continue;
        }
        break;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(<ListTag key={`list-${index}`}>{items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{renderInline(item, currentPath, onNavigate)}</li>)}</ListTag>);
      continue;
    }
    blocks.push(<p key={`p-${index}`}>{renderInline(trimmed, currentPath, onNavigate)}</p>);
    index += 1;
  }

  return <div className="markdown-body">{blocks}</div>;
}

function groupPages(pages) {
  return {
    root: pages.filter((page) => !page.path.includes("/")),
    contracts: pages.filter((page) => page.path.startsWith("contracts/")),
    sources: pages.filter((page) => page.path.startsWith("sources/")),
    milestones: pages.filter((page) => page.path.startsWith("milestones/")),
    queries: pages.filter((page) => page.path.startsWith("queries/")),
  };
}

function PageTreeSection({ label, pages, selectedPath, onSelect }) {
  return (
    <div className="wiki-folder">
      <div className="wiki-folder-label"><FolderOpen size={16} /> {label}</div>
      {pages.map((page) => (
        <button key={page.path} type="button" className={selectedPath === page.path ? "wiki-leaf active" : "wiki-leaf"} onClick={() => onSelect(page.path)}>
          <span>{page.title}</span>
          <small>{page.kind}</small>
        </button>
      ))}
    </div>
  );
}

export function WikiPage({
  setPage,
  selectedWikiPath,
  setSelectedWikiPath,
  selectedContractId,
  selectedMilestoneId,
  setSelectedContractId,
  setSelectedMilestoneId,
}) {
  const { t } = useI18n();
  const [manifest, setManifest] = useState({ pages: [], counts: {} });
  const [pageData, setPageData] = useState(null);
  const [lint, setLint] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function loadManifest() {
    const index = await api.wikiIndex();
    setManifest(index);
    return index;
  }

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const index = await loadManifest();
        if (selectedWikiPath) return;
        if (selectedMilestoneId) {
          const resolved = await api.wikiMilestone(selectedMilestoneId);
          setSelectedWikiPath(resolved.milestone_path);
          return;
        }
        if (selectedContractId) {
          const resolved = await api.wikiContract(selectedContractId);
          setSelectedWikiPath(resolved.project_path);
          return;
        }
        setSelectedWikiPath(index.pages?.[0]?.path || "index.md");
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (!selectedWikiPath) return;
    api.wikiPage(selectedWikiPath).then(setPageData).catch(setError);
  }, [selectedWikiPath]);

  const filteredPages = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return manifest.pages;
    return manifest.pages.filter((page) => [page.path, page.title, page.summary, ...(page.tags || [])].join(" ").toLowerCase().includes(needle));
  }, [manifest.pages, search]);

  const grouped = useMemo(() => groupPages(filteredPages), [filteredPages]);
  const metadata = pageData?.metadata || {};
  const backlinks = pageData?.backlinks || [];

  if (loading) return <LoadingBlock />;

  return (
    <div className="wiki-workspace">
      <div className="wiki-sidebar-panel">
        <label className="query-search-shell">
          <Search size={18} />
          <input type="text" placeholder={t("wiki.filterPlaceholder")} value={search} onChange={(event) => setSearch(event.target.value)} />
        </label>
        <div className="wiki-tree-card">
          <div className="wiki-tree-header">
            <div>
              <h3>{t("wiki.repository")}</h3>
              <p>{manifest.counts.total || 0} {t("wiki.pages")}</p>
            </div>
            <button type="button" className="ghost-button square" onClick={async () => setLint(await api.wikiLint())}><Sparkles size={16} /></button>
          </div>
          <div className="wiki-tree">
            {grouped.root.map((page) => (
              <button key={page.path} type="button" className={selectedWikiPath === page.path ? "wiki-node active" : "wiki-node"} onClick={() => setSelectedWikiPath(page.path)}>
                <FileText size={16} /> {page.title}
              </button>
            ))}
            <PageTreeSection label="contracts/" pages={grouped.contracts} selectedPath={selectedWikiPath} onSelect={setSelectedWikiPath} />
            <PageTreeSection label="sources/" pages={grouped.sources} selectedPath={selectedWikiPath} onSelect={setSelectedWikiPath} />
            <PageTreeSection label="milestones/" pages={grouped.milestones} selectedPath={selectedWikiPath} onSelect={setSelectedWikiPath} />
            <PageTreeSection label="queries/" pages={grouped.queries} selectedPath={selectedWikiPath} onSelect={setSelectedWikiPath} />
          </div>
        </div>
        {lint ? (
          <div className="wiki-tree-card">
            <h3>{t("wiki.lint")}</h3>
            <div className="wiki-lint-stack">
              <span className={`lint-pill ${lint.status}`}>{lint.status}</span>
              {(lint.findings || []).slice(0, 5).map((item, index) => (
                <article key={`${item.page}-${index}`} className="wiki-lint-item">
                  <strong>{item.severity.toUpperCase()}</strong>
                  <p>{item.message}</p>
                  <small>{item.page}</small>
                </article>
              ))}
              {!lint.findings?.length ? <div className="muted">{t("wiki.noLintFindings")}</div> : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="wiki-content-panel">
        <ErrorBlock error={error} />
        <div className="wiki-article-card">
          <div className="wiki-content-head modern">
            <div className="wiki-content-head-copy">
              <p className="wiki-page-eyebrow">{metadata.kind || "page"} <span>•</span> {selectedWikiPath || "wiki"}</p>
              <h2>{metadata.title || selectedWikiPath || "Wiki"}</h2>
              <p className="page-subtitle">{manifest.pages.find((item) => item.path === selectedWikiPath)?.summary || t("wiki.persistentKnowledgeBase")}</p>
              <div className="wiki-meta-inline">
                {metadata.updated_at ? <span className="wiki-meta-pill">{t("wiki.updated")} {metadata.updated_at}</span> : null}
                {metadata.contract_id ? <span className="wiki-meta-pill">{t("wiki.contract")} {metadata.contract_id}</span> : null}
                {metadata.milestone_id ? <span className="wiki-meta-pill">{t("wiki.milestone")} {metadata.milestone_id}</span> : null}
              </div>
            </div>
            <div className="button-row wiki-content-actions">
              {metadata.contract_id ? (
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => {
                    setSelectedContractId(metadata.contract_id);
                    setPage("detail");
                  }}
                ><BookOpen size={16} /> {t("wiki.contract")}</button>
              ) : null}
              {metadata.milestone_id ? (
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => {
                    setSelectedMilestoneId(metadata.milestone_id);
                    setPage("milestone");
                  }}
                ><BookOpen size={16} /> {t("wiki.milestone")}</button>
              ) : null}
              {metadata.contract_id ? (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedContractId(metadata.contract_id);
                    setPage("graph");
                  }}
                ><Network size={16} /> {t("wiki.graph")}</button>
              ) : null}
            </div>
          </div>
          <div className="wiki-article-body">
            <MarkdownView content={pageData?.content || ""} currentPath={selectedWikiPath || ""} onNavigate={setSelectedWikiPath} />
          </div>
        </div>
      </div>

      <aside className="wiki-meta-rail">
        <div className="wiki-meta-card">
          <div className="wiki-meta-head"><Clock3 size={16} /><h3>{t("wiki.pageMetadata")}</h3></div>
          <div className="meta-line"><span>{t("wiki.kind")}</span><strong>{metadata.kind || "-"}</strong></div>
          <div className="meta-line"><span>{t("wiki.updated")}</span><strong>{metadata.updated_at || "-"}</strong></div>
          <div className="meta-line"><span>{t("wiki.contractId")}</span><strong>{metadata.contract_id || "-"}</strong></div>
          <div className="meta-line"><span>{t("wiki.milestoneId")}</span><strong>{metadata.milestone_id || "-"}</strong></div>
          <div className="meta-line"><span>{t("wiki.sourceFile")}</span><strong>{metadata.source_file || "-"}</strong></div>
          <div className="meta-line"><span>{t("wiki.version")}</span><strong>{metadata.source_version || "-"}</strong></div>
        </div>
        <div className="wiki-meta-card">
          <div className="wiki-meta-head"><Network size={16} /><h3>{t("wiki.relatedPages")}</h3></div>
          <div className="wiki-chip-stack">
            {(metadata.related || []).map((item) => (
              <button key={item} type="button" className="wiki-chip" onClick={() => setSelectedWikiPath(item)}>{item}</button>
            ))}
            {!(metadata.related || []).length ? <div className="muted">{t("wiki.noRelatedPages")}</div> : null}
          </div>
        </div>
        <div className="wiki-meta-card">
          <div className="wiki-meta-head"><AlertTriangle size={16} /><h3>{t("wiki.backlinks")}</h3></div>
          <div className="wiki-backlink-list">
            {backlinks.map((item) => (
              <button key={item.path} type="button" className="wiki-row" onClick={() => setSelectedWikiPath(item.path)}>
                <strong>{item.title}</strong>
                <small>{item.path}</small>
              </button>
            ))}
            {!backlinks.length ? <div className="muted">{t("wiki.noBacklinks")}</div> : null}
          </div>
        </div>
      </aside>
    </div>
  );
}
