import { useEffect, useState } from "react";
import { Folder, FolderOpen, Network, Search, Text } from "lucide-react";
import { api } from "../api/client.js";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/Ui.jsx";

function MarkdownBlock({ content }) {
  if (!content) return <EmptyBlock label="Select a wiki page." />;
  return (
    <div className="markdown-body">
      {content.split("\n").map((line, index) => {
        if (line.startsWith("# ")) return <h1 key={index}>{line.slice(2)}</h1>;
        if (line.startsWith("## ")) return <h2 key={index}>{line.slice(3)}</h2>;
        if (line.startsWith("### ")) return <h3 key={index}>{line.slice(4)}</h3>;
        if (line.startsWith("- ")) return <li key={index}>{line.slice(2)}</li>;
        if (line.startsWith("```")) return <div key={index} className="wiki-code-divider" />;
        if (!line.trim()) return <br key={index} />;
        return <p key={index}>{line}</p>;
      })}
    </div>
  );
}

function groupedPages(pages) {
  return {
    root: pages.filter((page) => !page.includes("/")),
    contracts: pages.filter((page) => page.startsWith("contracts/")),
    milestones: pages.filter((page) => page.startsWith("milestones/")),
  };
}

export function WikiPage({ setPage }) {
  const [pages, setPages] = useState([]);
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const index = await api.wikiIndex();
        setPages(index.pages || []);
        setSelected(index.pages?.[0] || "");
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.wikiPage(selected).then((page) => setContent(page.content)).catch(setError);
  }, [selected]);

  if (loading) return <LoadingBlock />;

  const grouped = groupedPages(pages);
  const title = selected.split("/").pop() || "Wiki";

  return (
    <div className="wiki-screen">
      <div className="wiki-sidebar-panel">
        <label className="query-search-shell">
          <Search size={18} />
          <input type="text" placeholder="Search Knowledge Base..." />
        </label>
        <div className="wiki-tree-card">
          <h3>Repository</h3>
          <div className="wiki-tree">
            {grouped.root.map((page) => <button key={page} type="button" className={selected === page ? "wiki-node active" : "wiki-node"} onClick={() => setSelected(page)}><Text size={16} /> {page}</button>)}
            <div className="wiki-folder">
              <div className="wiki-folder-label"><FolderOpen size={16} /> contracts/</div>
              {grouped.contracts.map((page) => <button key={page} type="button" className={selected === page ? "wiki-leaf active" : "wiki-leaf"} onClick={() => setSelected(page)}>{page.split("/").pop()}</button>)}
            </div>
            <div className="wiki-folder">
              <div className="wiki-folder-label"><Folder size={16} /> milestones/</div>
              {grouped.milestones.map((page) => <button key={page} type="button" className={selected === page ? "wiki-leaf active" : "wiki-leaf"} onClick={() => setSelected(page)}>{page.split("/").pop()}</button>)}
            </div>
          </div>
        </div>
      </div>
      <div className="wiki-content-panel">
        <ErrorBlock error={error} />
        <div className="wiki-content-head">
          <div>
            <p className="label-caps">{selected.split("/").slice(0, -1).join(" > ") || "repository"}</p>
            <h2>{title.replace(/\.md$/i, "").replaceAll("_", " ")}</h2>
            <p className="page-subtitle">Last updated by system-generated wiki settlement.</p>
          </div>
          <button type="button" onClick={() => setPage("graph")}><Network size={16} /> View Graph Node</button>
        </div>
        <MarkdownBlock content={content} />
      </div>
    </div>
  );
}
