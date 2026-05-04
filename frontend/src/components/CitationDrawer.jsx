import { useEffect, useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { api } from "../api/client.js";
import { useI18n } from "../i18n.jsx";

export function citationLabel(citation, t = null) {
  if (!citation) return t ? t("citation.none") : "No citation";
  const page = citation.page_estimate ? `${t ? t("citation.page") : "page"} ${citation.page_estimate}` : `${t ? t("citation.page") : "page"} ?`;
  const para = citation.para_start !== undefined ? `${t ? t("citation.paragraph") : "para"} ${citation.para_start}` : `${t ? t("citation.paragraph") : "para"} ?`;
  return `${citation.source_file || "source"} · ${page} · ${para}`;
}

export function CitationButton({ citations = [], onOpen, label = "" }) {
  const { t } = useI18n();
  const count = Array.isArray(citations) ? citations.length : 0;
  return (
    <button className="icon-button" type="button" disabled={!count} onClick={() => onOpen(citations[0])} title={count ? citationLabel(citations[0], t) : t("citation.none")}>
      {count ? count : "-"}
      <span className="sr-only">{label || t("citation.citations")}</span>
    </button>
  );
}

export function CitationDrawer({ citation, onClose, onOpenSource }) {
  const { t } = useI18n();
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
        if (!cancelled) setSourceError(err.message || t("citation.sourceBlockNotFound"));
      });
    return () => {
      cancelled = true;
    };
  }, [citation]);

  if (!citation) return null;
  const hasOffsets = (citation.char_offset_start ?? -1) >= 0 && (citation.char_offset_end ?? -1) >= 0;
  return (
    <aside className="drawer" aria-label={t("citation.citations")}>
      <div className="drawer-header">
        <div>
          <p className="label-caps">{t("citation.source")}</p>
          <h2>{citation.source_file || t("citation.unknownSource")}</h2>
        </div>
        <button className="ghost-button square" type="button" onClick={onClose} aria-label={t("citation.close")}>
          <X size={18} />
        </button>
      </div>
      <div className="drawer-body">
        <dl className="meta-grid">
          <dt>{t("citation.field")}</dt>
          <dd>{citation.field_name || "-"}</dd>
          <dt>{t("citation.page")}</dt>
          <dd>{citation.page_estimate || "-"}</dd>
          <dt>{t("citation.paragraph")}</dt>
          <dd>{citation.para_start ?? "-"}-{citation.para_end ?? "-"}</dd>
          <dt>{t("citation.block")}</dt>
          <dd>{citation.block_id || "-"}</dd>
          <dt>{t("citation.offsets")}</dt>
          <dd>{hasOffsets ? `${citation.char_offset_start}-${citation.char_offset_end}` : "-"}</dd>
          <dt>{t("citation.mode")}</dt>
          <dd>{citation.citation_mode || "exact_span"}</dd>
          <dt>{t("citation.method")}</dt>
          <dd>{citation.extraction_method || "-"}</dd>
          <dt>{t("citation.pattern")}</dt>
          <dd className="code-cell">{citation.regex_pattern || "-"}</dd>
        </dl>
        <div className="snippet">
          <p className="label-caps">{t("citation.extractedSnippet")}</p>
          <blockquote>{citation.text_snippet || t("citation.noSnippet")}</blockquote>
        </div>
        <div className="snippet">
          <p className="label-caps">{t("citation.verifiedSourceBlock")}</p>
          {sourceBlock ? <blockquote>{sourceBlock.text || t("citation.noSourceText")}</blockquote> : null}
          {!sourceBlock && !sourceError ? <blockquote>{t("citation.loadingSource")}</blockquote> : null}
          {sourceError ? <blockquote>{sourceError}</blockquote> : null}
        </div>
        {citation.source_path && onOpenSource ? (
          <button className="ghost-button" type="button" onClick={() => onOpenSource(citation.source_path)}>
            <ExternalLink size={16} /> {t("common.openSourcePage")}
          </button>
        ) : null}
      </div>
    </aside>
  );
}
