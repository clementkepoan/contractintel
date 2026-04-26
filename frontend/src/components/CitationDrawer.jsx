import { useEffect, useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { api } from "../api/client.js";

export function citationLabel(citation) {
  if (!citation) return "No citation";
  const page = citation.page_estimate ? `p.${citation.page_estimate}` : "page ?";
  const para = citation.para_start !== undefined ? `para ${citation.para_start}` : "para ?";
  return `${citation.source_file || "source"} · ${page} · ${para}`;
}

export function CitationButton({ citations = [], onOpen, label = "Citations" }) {
  const count = Array.isArray(citations) ? citations.length : 0;
  return (
    <button className="icon-button" type="button" disabled={!count} onClick={() => onOpen(citations[0])} title={count ? citationLabel(citations[0]) : "No citation"}>
      {count ? count : "-"}
      <span className="sr-only">{label}</span>
    </button>
  );
}

export function CitationDrawer({ citation, onClose, onOpenSource }) {
  const [sourceBlock, setSourceBlock] = useState(null);
  const [sourceError, setSourceError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setSourceBlock(null);
    setSourceError(null);
    if (!citation?.contract_id || !citation?.block_id) return undefined;
    api.sourceBlock(citation.contract_id, citation.block_id)
      .then((block) => {
        if (!cancelled) setSourceBlock(block);
      })
      .catch((err) => {
        if (!cancelled) setSourceError(err.message || "Source block not found.");
      });
    return () => {
      cancelled = true;
    };
  }, [citation]);

  if (!citation) return null;
  return (
    <aside className="drawer" aria-label="Citation details">
      <div className="drawer-header">
        <div>
          <p className="label-caps">Citation Source</p>
          <h2>{citation.source_file || "Unknown source"}</h2>
        </div>
        <button className="ghost-button square" type="button" onClick={onClose} aria-label="Close citation drawer">
          <X size={18} />
        </button>
      </div>
      <div className="drawer-body">
        <dl className="meta-grid">
          <dt>Field</dt>
          <dd>{citation.field_name || "-"}</dd>
          <dt>Page</dt>
          <dd>{citation.page_estimate || "-"}</dd>
          <dt>Paragraph</dt>
          <dd>{citation.para_start ?? "-"}-{citation.para_end ?? "-"}</dd>
          <dt>Block</dt>
          <dd>{citation.block_id || "-"}</dd>
          <dt>Offsets</dt>
          <dd>{citation.char_offset_start ?? "-"}-{citation.char_offset_end ?? "-"}</dd>
          <dt>Method</dt>
          <dd>{citation.extraction_method || "-"}</dd>
          <dt>Pattern</dt>
          <dd className="code-cell">{citation.regex_pattern || "-"}</dd>
        </dl>
        <div className="snippet">
          <p className="label-caps">Extracted Snippet</p>
          <blockquote>{citation.text_snippet || "No snippet available."}</blockquote>
        </div>
        <div className="snippet">
          <p className="label-caps">Verified Source Block</p>
          {sourceBlock ? <blockquote>{sourceBlock.text || "No source text available."}</blockquote> : null}
          {!sourceBlock && !sourceError ? <blockquote>Loading source block...</blockquote> : null}
          {sourceError ? <blockquote>{sourceError}</blockquote> : null}
        </div>
        {citation.source_path && onOpenSource ? (
          <button className="ghost-button" type="button" onClick={() => onOpenSource(citation.source_path)}>
            <ExternalLink size={16} /> Open Source Page
          </button>
        ) : null}
      </div>
    </aside>
  );
}
