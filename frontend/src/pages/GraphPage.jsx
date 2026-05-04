import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Boxes, CircleDollarSign, FileText, Flag, Network, ReceiptText, Scale } from "lucide-react";

import { api, formatDate, formatMoney } from "../api/client.js";
import {
  formatTranslation,
  translateContractType,
  translateGraphEdgeType,
  translateGraphNodeType,
  translatePaymentState,
  translateValidationMessage,
  useI18n,
} from "../i18n.jsx";
import { ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";
import { GraphCanvas } from "../components/graph/GraphCanvas.jsx";
import {
  buildContractFocusSubgraph,
  buildMilestoneFocusSubgraph,
  buildPortfolioOverviewSubgraph,
  isEvidenceNode,
} from "../components/graph/buildFocusSubgraph.js";

const typeToIcon = {
  Contract: FileText,
  Milestone: Flag,
  WorkItem: Boxes,
  Invoice: ReceiptText,
  Payment: CircleDollarSign,
  Clause: Scale,
  ClauseBundle: Scale,
  ValidationWarning: AlertTriangle,
};

const toneByType = {
  Contract: "contract",
  Milestone: "milestone",
  WorkItem: "work",
  Invoice: "invoice",
  Payment: "payment",
  Clause: "clause",
  ClauseBundle: "clause",
  ValidationWarning: "warning",
};

function nodeLabel(node, t) {
  if (node?.type === "ClauseBundle") {
    return t("graph.supportingClauses");
  }
  if (node?.type === "ValidationWarning") {
    return translateValidationMessage(node.message, t) || node?.id || t("common.unknown");
  }
  return node?.name || node?.description || node?.message || node?.text || node?.id || t("common.unknown");
}

function filterByNodeIds(graph, ids) {
  if (!ids?.size) return graph;
  return {
    nodes: graph.nodes.filter((node) => ids.has(node.id)),
    edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
  };
}

function nodeById(graph, nodeId) {
  return graph.nodes.find((node) => node.id === nodeId) || null;
}

function relationshipSummary(graph, selectedId) {
  if (!selectedId) return { outgoing: [], incoming: [] };
  return {
    outgoing: graph.edges.filter((edge) => edge.source === selectedId),
    incoming: graph.edges.filter((edge) => edge.target === selectedId),
  };
}

function uniqueNodes(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (!item?.id || seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function peersByType(graph, selectedNodeId, edges, type) {
  return uniqueNodes(
    edges
      .map((edge) => {
        const peerId = edge.source === selectedNodeId ? edge.target : edge.source;
        return nodeById(graph, peerId);
      })
      .filter((node) => node?.type === type),
  );
}

function findContractIdForNode(graph, node) {
  if (!node) return "";
  if (node.type === "Contract") return node.id;
  if (node.contract_id) return node.contract_id;

  const supportingEdge = graph.edges.find((edge) => edge.source === node.id && edge.type === "SUPPORTS");
  if (supportingEdge) {
    const milestone = nodeById(graph, supportingEdge.target);
    return milestone?.contract_id || "";
  }

  const attachedEdge = graph.edges.find((edge) => edge.source === node.id && edge.type === "ATTACHED_TO");
  if (attachedEdge) {
    const contract = nodeById(graph, attachedEdge.target);
    return contract?.id || "";
  }

  const governsEdge = graph.edges.find((edge) => edge.source === node.id && edge.type === "GOVERNS");
  if (governsEdge) return governsEdge.target;

  return "";
}

function buildAcceptedPresetGraph(fullGraph, contractId, itemIds) {
  const visibleIds = new Set(itemIds);

  for (const itemId of itemIds) {
    const item = nodeById(fullGraph, itemId);
    if (!item) continue;
    const contractRef = item.contract_id || findContractIdForNode(fullGraph, item);
    if (contractRef) visibleIds.add(contractRef);

    for (const edge of fullGraph.edges) {
      if (edge.source === itemId && ["TRIGGERS_PAYMENT", "HAS_WORKITEM"].includes(edge.type)) {
        visibleIds.add(edge.source);
        visibleIds.add(edge.target);
      }
      if (edge.target === itemId && edge.type === "HAS_MILESTONE") {
        visibleIds.add(edge.source);
        visibleIds.add(edge.target);
      }
    }
  }

  const presetGraph = filterByNodeIds(fullGraph, visibleIds);
  const strippedGraph = {
    nodes: presetGraph.nodes.filter((node) => !["Clause", "ValidationWarning"].includes(node.type)),
    edges: presetGraph.edges.filter((edge) => edge.type !== "SUPPORTS" && edge.type !== "GOVERNS" && edge.type !== "ATTACHED_TO"),
  };
  if (!contractId) return strippedGraph;
  return filterByNodeIds(
    strippedGraph,
    new Set(
      strippedGraph.nodes
        .filter((node) => node.type === "Contract" ? node.id === contractId : node.contract_id === contractId || findContractIdForNode(strippedGraph, node) === contractId)
        .map((node) => node.id),
    ),
  );
}

function buildRiskPresetGraph(fullGraph, contractId, warningIds) {
  const visibleIds = new Set(warningIds);

  for (const warningId of warningIds) {
    const warning = nodeById(fullGraph, warningId);
    if (!warning) continue;
    const contractRef = warning.contract_id || findContractIdForNode(fullGraph, warning);
    if (contractRef) visibleIds.add(contractRef);
  }

  const presetGraph = filterByNodeIds(fullGraph, visibleIds);
  if (!contractId) return presetGraph;
  return filterByNodeIds(
    presetGraph,
    new Set(
      presetGraph.nodes
        .filter((node) => node.type === "Contract" ? node.id === contractId : node.contract_id === contractId || findContractIdForNode(presetGraph, node) === contractId)
        .map((node) => node.id),
    ),
  );
}

export function GraphPage({ contractId, milestoneId, setSelectedContractId, setSelectedMilestoneId, setPage }) {
  const { t } = useI18n();
  const [contracts, setContracts] = useState([]);
  const [fullGraph, setFullGraph] = useState({ nodes: [], edges: [] });
  const [queryResult, setQueryResult] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [focusedMilestoneId, setFocusedMilestoneId] = useState("");
  const [preset, setPreset] = useState("default");
  const [layoutNonce, setLayoutNonce] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [contractList, graphData] = await Promise.all([api.contracts(), api.graph()]);
      setContracts(contractList);
      setFullGraph(graphData);
      setQueryResult(null);
      setPreset("default");
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
    setPreset("default");
    setQueryResult(null);
    setFocusedMilestoneId(milestoneId || "");
    setSelectedNodeId("");
    setLayoutNonce((current) => current + 1);
  }, [contractId, milestoneId]);

  async function runPreset(name) {
    setPreset(name);
    setQueryResult(null);

    if (name === "default") {
      setLayoutNonce((current) => current + 1);
      return;
    }

    if (name === "accepted") {
      const payload = await api.graphAcceptedNotPaid();
      setQueryResult(payload);
      setSelectedNodeId(payload.items[0]?.id || "");
      setFocusedMilestoneId(payload.items[0]?.type === "Milestone" ? payload.items[0].id : "");
      setLayoutNonce((current) => current + 1);
      return;
    }

    if (name === "risk") {
      const payload = await api.graphHighRiskWarnings();
      setQueryResult(payload);
      setSelectedNodeId(payload.items[0]?.id || "");
      setFocusedMilestoneId("");
      setLayoutNonce((current) => current + 1);
      return;
    }

    if (name === "trail" && milestoneId) {
      const payload = await api.graphPaymentTrail(milestoneId);
      setQueryResult(payload);
      setSelectedNodeId(milestoneId);
      setFocusedMilestoneId(milestoneId);
      setLayoutNonce((current) => current + 1);
    }
  }

  const baseVisibleGraph = useMemo(() => {
    if (preset === "accepted" && queryResult?.items) {
      return buildAcceptedPresetGraph(fullGraph, contractId || "", queryResult.items.map((item) => item.id));
    }

    if (preset === "risk" && queryResult?.items) {
      return buildRiskPresetGraph(fullGraph, contractId || "", queryResult.items.map((item) => item.id));
    }

    if (preset === "trail" && queryResult?.nodes && queryResult?.edges) {
      return queryResult;
    }

    if (!contractId) {
      return buildPortfolioOverviewSubgraph(fullGraph);
    }

    if (focusedMilestoneId) {
      return buildMilestoneFocusSubgraph(fullGraph, focusedMilestoneId);
    }

    return buildContractFocusSubgraph(fullGraph, contractId);
  }, [contractId, focusedMilestoneId, fullGraph, preset, queryResult]);

  useEffect(() => {
    if (!selectedNodeId) return;
    if (!baseVisibleGraph.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId("");
    }
  }, [baseVisibleGraph, selectedNodeId]);

  const selectedNode = useMemo(
    () => nodeById(baseVisibleGraph, selectedNodeId) || nodeById(fullGraph, selectedNodeId) || null,
    [baseVisibleGraph, fullGraph, selectedNodeId],
  );

  const { outgoing, incoming } = relationshipSummary(baseVisibleGraph, selectedNodeId);
  const neighborhoodEdges = useMemo(() => outgoing.concat(incoming), [incoming, outgoing]);
  const connectedIds = useMemo(
    () => new Set(selectedNodeId ? [selectedNodeId, ...outgoing.map((edge) => edge.target), ...incoming.map((edge) => edge.source)] : []),
    [incoming, outgoing, selectedNodeId],
  );
  const relatedClauses = uniqueNodes([
    ...peersByType(baseVisibleGraph, selectedNodeId, neighborhoodEdges, "ClauseBundle"),
    ...peersByType(baseVisibleGraph, selectedNodeId, neighborhoodEdges, "Clause"),
  ]);
  const relatedWarnings = peersByType(baseVisibleGraph, selectedNodeId, neighborhoodEdges, "ValidationWarning");
  const directPeerNodes = uniqueNodes(
    neighborhoodEdges
      .map((edge) => {
        const peerId = edge.source === selectedNodeId ? edge.target : edge.source;
        return nodeById(baseVisibleGraph, peerId);
      })
      .filter((node) => node && !["Clause", "ClauseBundle", "ValidationWarning"].includes(node.type)),
  );
  const invoiceNodes = outgoing
    .map((edge) => nodeById(baseVisibleGraph, edge.target))
    .filter((node) => node?.type === "Invoice");
  const invoicedTotal = invoiceNodes.reduce((sum, node) => sum + Number(node.amount || 0), 0);

  function handleNodeSelect(nodeId) {
    const node = nodeById(baseVisibleGraph, nodeId) || nodeById(fullGraph, nodeId);
    if (!node) return;

    setSelectedNodeId(node.id);

    if (isEvidenceNode(node)) return;

    if (node.type === "Contract") {
      if (!contractId || contractId !== node.id) {
        setFocusedMilestoneId("");
        setSelectedMilestoneId("");
        setSelectedContractId(node.id);
        return;
      }
      setFocusedMilestoneId("");
      setLayoutNonce((current) => current + 1);
      return;
    }

    if (node.type === "Milestone") {
      setFocusedMilestoneId(node.id);
      setSelectedMilestoneId(node.id);
      setLayoutNonce((current) => current + 1);
    }
  }

  function handleContractFilterChange(nextContractId) {
    setFocusedMilestoneId("");
    setSelectedNodeId("");
    setSelectedMilestoneId("");
    setSelectedContractId(nextContractId);
    setLayoutNonce((current) => current + 1);
  }

  function handleBackToContractView() {
    setFocusedMilestoneId("");
    setSelectedNodeId(contractId || "");
    setLayoutNonce((current) => current + 1);
  }

  function viewDetails() {
    if (!selectedNode) return;
    if (selectedNode.type === "Contract") {
      setSelectedContractId(selectedNode.id);
      setPage("detail");
    }
    if (selectedNode.type === "Milestone") {
      setSelectedMilestoneId(selectedNode.id);
      setPage("milestone");
    }
  }

  if (loading) return <LoadingBlock />;

  return (
    <div className="page-stack graph-screen">
      <ErrorBlock error={error} />
      <div className="graph-layout modern">
        <div className="graph-workspace modern">
          <div className="graph-overlay top modern">
            <div className="graph-overlay-stack">
              <div className="graph-chip-row">
                <button type="button" className={preset === "accepted" ? "graph-chip active warning" : "graph-chip"} onClick={() => runPreset("accepted")}><span className="dot amber" />{t("graph.acceptedNotFullyPaid")}</button>
                <button type="button" className={preset === "risk" ? "graph-chip active danger" : "graph-chip"} onClick={() => runPreset("risk")}><span className="dot red" />{t("graph.highRiskWarnings")}</button>
                <button type="button" className={preset === "trail" ? "graph-chip active info" : "graph-chip"} disabled={!milestoneId} onClick={() => runPreset("trail")}><span className="dot blue" />{t("graph.milestoneDependencies")}</button>
                <button type="button" className={preset === "default" ? "graph-chip active" : "graph-chip"} onClick={() => runPreset("default")}><Network size={14} />{t("graph.fullGraph")}</button>
              </div>
              <div className="graph-legend-row">
                <span className="graph-legend-item"><span className="dot slate" />{translatePaymentState("no_invoice", t)}</span>
                <span className="graph-legend-item"><span className="dot amber" />{translatePaymentState("invoiced_unpaid", t)}</span>
                <span className="graph-legend-item"><span className="dot blue" />{translatePaymentState("partially_paid", t)}</span>
                <span className="graph-legend-item"><span className="dot green" />{translatePaymentState("fully_paid", t)}</span>
              </div>
            </div>
            <div className="graph-overlay-actions">
              {preset === "default" && contractId && focusedMilestoneId ? (
                <button type="button" className="graph-chip active graph-back-button" onClick={handleBackToContractView}>
                  <ArrowLeft size={14} />
                  {t("graph.backToContractView")}
                </button>
              ) : null}
              <select className="graph-contract-filter" value={contractId || ""} onChange={(event) => handleContractFilterChange(event.target.value)}>
                <option value="">{t("common.allContracts")}</option>
                {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
              </select>
            </div>
          </div>
          <div className="graph-canvas modern">
            <GraphCanvas
              graph={baseVisibleGraph}
              layoutNonce={layoutNonce}
              selectedNodeId={selectedNodeId}
              highlightIds={connectedIds}
              onSelectNode={handleNodeSelect}
              onRelayout={() => setLayoutNonce((current) => current + 1)}
              contractId={contractId || ""}
              focusedMilestoneId={focusedMilestoneId}
            />
          </div>
        </div>
        <aside className="graph-drawer">
          {selectedNode ? (
            <>
              <div className="graph-drawer-header">
                <div className={`graph-node-badge ${toneByType[selectedNode.type]}`}>
                  {(() => {
                    const Icon = typeToIcon[selectedNode.type] || Network;
                    return <Icon size={18} />;
                  })()}
                </div>
                <div>
                  <p className="label-caps">{translateGraphNodeType(selectedNode.type, t)}</p>
                  <h2>{nodeLabel(selectedNode, t)}</h2>
                </div>
              </div>
              <div className="graph-drawer-body">
                {selectedNode.type === "Milestone" ? (
                  <div className="drawer-metrics">
                    <div className="drawer-metric">
                      <span>{t("graph.status")}</span>
                      <div>{selectedNode.status ? <StatusBadge status={selectedNode.status} /> : "-"}</div>
                    </div>
                    <div className="drawer-wide payment-state-card">
                      <span>{t("graph.paymentState")}</span>
                      <strong>{translatePaymentState(selectedNode.payment_state, t)}</strong>
                    </div>
                    <div className="drawer-wide">
                      <span>{t("graph.financialValue")}</span>
                      <strong>{formatMoney(selectedNode.amount, "TWD")}</strong>
                    </div>
                    <div className="drawer-wide align-end">
                      <span>{t("graph.invoiced")}</span>
                      <strong>{formatMoney(invoicedTotal, "TWD")}</strong>
                    </div>
                  </div>
                ) : null}

                {selectedNode.type === "Invoice" || selectedNode.type === "Payment" ? (
                  <div className="drawer-metrics">
                    <div className="drawer-metric">
                      <span>{t("graph.date")}</span>
                      <div>{formatDate(selectedNode.date)}</div>
                    </div>
                    <div className="drawer-wide">
                      <span>{t("graph.financialValue")}</span>
                      <strong>{formatMoney(selectedNode.amount, "TWD")}</strong>
                    </div>
                  </div>
                ) : null}

                {selectedNode.type === "Contract" ? (
                  <div className="drawer-section">
                    <p className="label-caps">{t("graph.overview")}</p>
                    <article className="clause-card contract-overview-card">
                      <p>{selectedNode.overview || t("graph.noOverview")}</p>
                      <small>{[selectedNode.overview_label, selectedNode.doc_category ? translateContractType(selectedNode.doc_category, t) : null, selectedNode.source_file].filter(Boolean).join(" • ")}</small>
                    </article>
                  </div>
                ) : null}

                {selectedNode.type === "ValidationWarning" ? (
                  <div className="drawer-section">
                    <p className="label-caps">{t("graph.warningDetail")}</p>
                    <article className="clause-card warning">
                      <p>{translateValidationMessage(selectedNode.message, t) || "-"}</p>
                      <small>{String(selectedNode.severity || "info").toUpperCase()}</small>
                    </article>
                  </div>
                ) : null}

                {selectedNode.type === "Clause" ? (
                  <div className="drawer-section">
                    <p className="label-caps">{t("graph.clauseDetail")}</p>
                    <article className="clause-card">
                      <p>{selectedNode.text || nodeLabel(selectedNode, t)}</p>
                      <small>{[selectedNode.clause_type, selectedNode.location, selectedNode.source_file].filter(Boolean).join(" • ")}</small>
                    </article>
                  </div>
                ) : null}

                {selectedNode.type === "ClauseBundle" ? (
                  <div className="drawer-section">
                    <p className="label-caps">{t("graph.supportingClauses")}</p>
                    <article className="clause-card">
                      <p>{formatTranslation(t, "graph.supportingClauseCount", { count: selectedNode.clause_count || 0 })}</p>
                      <small>{t("graph.supportingClauses")}</small>
                    </article>
                    <div className="drawer-clause-stack">
                      {(selectedNode.clauses || []).map((clause) => (
                        <article key={clause.id} className="clause-card">
                          <p>{clause.text || "-"}</p>
                          <small>{[clause.clause_type, clause.location, clause.source_file].filter(Boolean).join(" • ")}</small>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="drawer-section">
                  <p className="label-caps">{t("graph.directRelationships")}</p>
                  <div className="relation-list">
                    {directPeerNodes.map((peer, index) => {
                      const PeerIcon = typeToIcon[peer.type] || Network;
                      const edge = neighborhoodEdges.find((item) => item.source === peer.id || item.target === peer.id);
                      return (
                        <button key={`${peer.id}-${index}`} type="button" className="relation-card" onClick={() => handleNodeSelect(peer.id)}>
                          <div className={`relation-icon ${toneByType[peer.type]}`}><PeerIcon size={16} /></div>
                          <div>
                            <span>{edge?.type ? translateGraphEdgeType(edge.type, t) : translateGraphNodeType(peer.type, t)}</span>
                            <strong>{nodeLabel(peer, t)}</strong>
                          </div>
                        </button>
                      );
                    })}
                    {!directPeerNodes.length ? <div className="muted">{t("graph.noDirectRelationships")}</div> : null}
                  </div>
                </div>
                <div className="drawer-section">
                  <p className="label-caps">{t("graph.relevantClauses")}</p>
                  {relatedClauses.length ? relatedClauses.map((clause) => (
                    clause.type === "ClauseBundle" ? (
                      <article key={clause.id} className="clause-card">
                        <p>{t("graph.supportingClauses")}</p>
                        <small>{formatTranslation(t, "graph.bundledClauses", { count: clause.clause_count || 0 })}</small>
                      </article>
                    ) : (
                      <article key={clause.id} className="clause-card">
                        <p>{clause.text || nodeLabel(clause, t)}</p>
                        <small>{[clause.clause_type, clause.location, clause.source_file].filter(Boolean).join(" • ")}</small>
                      </article>
                    )
                  )) : <div className="muted">{t("graph.noClauseEvidence")}</div>}
                </div>
                <div className="drawer-section">
                  <p className="label-caps">{t("graph.validationWarnings")}</p>
                  {relatedWarnings.length ? relatedWarnings.map((warning) => (
                    <article key={warning.id} className="clause-card warning">
                      <p>{translateValidationMessage(warning.message, t) || nodeLabel(warning, t)}</p>
                      <small>{String(warning.severity || "info").toUpperCase()}</small>
                    </article>
                  )) : <div className="muted">{t("graph.noWarningEdges")}</div>}
                </div>
                {queryResult ? (
                  <div className="drawer-section">
                    <p className="label-caps">{t("graph.queryResult")}</p>
                    <pre className="json-block compact">{JSON.stringify(queryResult, null, 2)}</pre>
                  </div>
                ) : null}
              </div>
              <div className="graph-drawer-footer">
                <button type="button" className="ghost-button" onClick={viewDetails}>{t("common.viewDetails")}</button>
                <button type="button" onClick={() => setPage("query")}>{t("common.runQuery")}</button>
              </div>
            </>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
