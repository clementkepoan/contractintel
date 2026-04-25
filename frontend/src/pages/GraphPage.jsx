import { useEffect, useState } from "react";
import { Boxes, CircleDollarSign, FileText, Flag, Minus, Network, ReceiptText, ScanSearch, Scale, ZoomIn, ZoomOut } from "lucide-react";
import { api, formatDate, formatMoney } from "../api/client.js";
import { ErrorBlock, LoadingBlock } from "../components/Ui.jsx";
import { StatusBadge } from "../components/StatusBadge.jsx";

const typeToIcon = {
  Contract: FileText,
  Milestone: Flag,
  WorkItem: Boxes,
  Invoice: ReceiptText,
  Payment: CircleDollarSign,
  Clause: Scale,
};

const toneByType = {
  Contract: "contract",
  Milestone: "milestone",
  WorkItem: "work",
  Invoice: "invoice",
  Payment: "payment",
  Clause: "clause",
};

function nodeLabel(node) {
  return node?.name || node?.description || node?.text || node?.id || "Unknown";
}

function layoutGraph(graph) {
  const lanes = { Contract: 0, Milestone: 1, WorkItem: 2, Invoice: 1, Payment: 3, Clause: 2 };
  const buckets = new Map();
  for (const node of graph.nodes) {
    const lane = lanes[node.type] ?? 4;
    if (!buckets.has(lane)) buckets.set(lane, []);
    buckets.get(lane).push(node);
  }
  const positions = {};
  for (const [lane, nodes] of buckets.entries()) {
    nodes.forEach((node, index) => {
      const yBase = 90 + lane * 150;
      const xBase = lane === 1 && node.type === "Invoice" ? 780 : 180 + index * 210;
      const y = node.type === "Invoice" ? 170 : node.type === "Clause" ? 390 + (index % 2) * 28 : yBase;
      positions[node.id] = { x: xBase, y };
    });
  }
  return positions;
}

function filterByContract(graph, contractId) {
  if (!contractId) return graph;
  const visible = new Set([contractId]);
  for (const edge of graph.edges) {
    if (edge.source === contractId || edge.target === contractId) {
      visible.add(edge.source);
      visible.add(edge.target);
    }
  }
  for (const edge of graph.edges) {
    if (visible.has(edge.source)) visible.add(edge.target);
  }
  return {
    nodes: graph.nodes.filter((node) => visible.has(node.id)),
    edges: graph.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

function filterByNodeIds(graph, ids) {
  if (!ids?.size) return graph;
  return {
    nodes: graph.nodes.filter((node) => ids.has(node.id)),
    edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
  };
}

function relationshipSummary(graph, selectedId) {
  return {
    outgoing: graph.edges.filter((edge) => edge.source === selectedId),
    incoming: graph.edges.filter((edge) => edge.target === selectedId),
  };
}

export function GraphPage({ contractId, milestoneId, setSelectedContractId, setSelectedMilestoneId, setPage }) {
  const [contracts, setContracts] = useState([]);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [queryResult, setQueryResult] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [preset, setPreset] = useState("default");
  const [zoom, setZoom] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load(focusContractId = contractId) {
    setLoading(true);
    setError(null);
    try {
      const [contractList, graphData] = await Promise.all([api.contracts(), api.graph()]);
      const focused = filterByContract(graphData, focusContractId || null);
      setContracts(contractList);
      setGraph(focused);
      setQueryResult(null);
      setPreset("default");
      setSelectedNodeId((current) => current || focused.nodes.find((node) => node.type === "Milestone")?.id || focused.nodes[0]?.id || "");
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [contractId]);

  async function runPreset(name) {
    setPreset(name);
    if (name === "default") {
      await load(contractId);
      return;
    }
    if (name === "accepted") {
      const payload = await api.graphAcceptedNotPaid();
      const ids = new Set(payload.items.map((item) => item.id));
      setQueryResult(payload);
      setGraph((current) => filterByNodeIds(current, ids));
      setSelectedNodeId(payload.items[0]?.id || "");
      return;
    }
    if (name === "risk") {
      const payload = await api.graphHighRiskClauses();
      const ids = new Set(payload.items.map((item) => item.id));
      setQueryResult(payload);
      setGraph((current) => filterByNodeIds(current, ids));
      setSelectedNodeId(payload.items[0]?.id || "");
      return;
    }
    if (name === "trail" && milestoneId) {
      const payload = await api.graphPaymentTrail(milestoneId);
      setQueryResult(payload);
      setGraph(payload);
      setSelectedNodeId(milestoneId);
    }
  }

  if (loading) return <LoadingBlock />;

  const positions = layoutGraph(graph);
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) || null;
  const { outgoing, incoming } = relationshipSummary(graph, selectedNodeId);
  const connectedIds = new Set([selectedNodeId, ...outgoing.map((edge) => edge.target), ...incoming.map((edge) => edge.source)]);
  const relatedClauses = outgoing
    .map((edge) => graph.nodes.find((node) => node.id === edge.target))
    .filter((node) => node?.type === "Clause");
  const invoiceNodes = outgoing
    .map((edge) => graph.nodes.find((node) => node.id === edge.target))
    .filter((node) => node?.type === "Invoice");
  const invoicedTotal = invoiceNodes.reduce((sum, node) => sum + Number(node.amount || 0), 0);

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

  return (
    <div className="page-stack graph-screen">
      <ErrorBlock error={error} />
      <div className="graph-layout">
        <div className="graph-workspace">
          <div className="graph-overlay top">
            <div className="graph-chip-row">
              <button type="button" className={preset === "accepted" ? "graph-chip active warning" : "graph-chip"} onClick={() => runPreset("accepted")}><span className="dot amber" />Accepted but not paid</button>
              <button type="button" className={preset === "risk" ? "graph-chip active danger" : "graph-chip"} onClick={() => runPreset("risk")}><span className="dot red" />High-risk clauses</button>
              <button type="button" className={preset === "trail" ? "graph-chip active info" : "graph-chip"} disabled={!milestoneId} onClick={() => runPreset("trail")}><span className="dot blue" />Milestone Dependencies</button>
              <button type="button" className={preset === "default" ? "graph-chip active" : "graph-chip"} onClick={() => runPreset("default")}><Network size={14} />Full graph</button>
            </div>
            <select className="graph-contract-filter" value={contractId || ""} onChange={(event) => { setSelectedContractId(event.target.value); load(event.target.value); }}>
              <option value="">All contracts</option>
              {contracts.map((item) => <option key={item.contract_id} value={item.contract_id}>{item.contract_name}</option>)}
            </select>
          </div>
          <div className="graph-tools">
            <button type="button" className="tool-button" onClick={() => setZoom((current) => Math.min(current + 0.1, 1.6))}><ZoomIn size={18} /></button>
            <button type="button" className="tool-button" onClick={() => setZoom((current) => Math.max(current - 0.1, 0.7))}><ZoomOut size={18} /></button>
            <button type="button" className="tool-button" onClick={() => setZoom(1)}><ScanSearch size={18} /></button>
            <button type="button" className="tool-button" onClick={() => setZoom(0.85)}><Minus size={18} /></button>
          </div>
          <div className="graph-canvas">
            <div className="graph-stage" style={{ transform: `scale(${zoom})` }}>
              <svg className="graph-edges" viewBox="0 0 1000 640" preserveAspectRatio="none">
                {graph.edges.map((edge) => {
                  const from = positions[edge.source];
                  const to = positions[edge.target];
                  if (!from || !to) return null;
                  const active = connectedIds.has(edge.source) && connectedIds.has(edge.target);
                  return (
                    <line
                      key={`${edge.source}-${edge.target}-${edge.type}`}
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      className={active ? "edge-line active" : "edge-line"}
                      strokeDasharray={edge.type === "GOVERNS" ? "6 6" : undefined}
                    />
                  );
                })}
              </svg>
              {graph.nodes.map((node) => {
                const Icon = typeToIcon[node.type] || Network;
                const position = positions[node.id];
                if (!position) return null;
                const active = node.id === selectedNodeId;
                return (
                  <button
                    key={node.id}
                    type="button"
                    className={active ? `graph-node ${toneByType[node.type]} active` : `graph-node ${toneByType[node.type]}`}
                    style={{ left: `${position.x}px`, top: `${position.y}px` }}
                    onClick={() => setSelectedNodeId(node.id)}
                  >
                    <span className="graph-node-bubble"><Icon size={18} /></span>
                    <span className="graph-node-label">{nodeLabel(node)}</span>
                  </button>
                );
              })}
            </div>
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
                  <p className="label-caps">{selectedNode.type}</p>
                  <h2>{nodeLabel(selectedNode)}</h2>
                </div>
              </div>
              <div className="graph-drawer-body">
                <div className="drawer-metrics">
                  <div className="drawer-metric">
                    <span>Status</span>
                    <div>{selectedNode.status ? <StatusBadge status={selectedNode.status} /> : "-"}</div>
                  </div>
                  <div className="drawer-metric">
                    <span>Date</span>
                    <div>{formatDate(selectedNode.date)}</div>
                  </div>
                  <div className="drawer-wide">
                    <span>Financial Value</span>
                    <strong>{formatMoney(selectedNode.amount, "TWD")}</strong>
                  </div>
                  <div className="drawer-wide align-end">
                    <span>Invoiced</span>
                    <strong>{formatMoney(invoicedTotal, "TWD")}</strong>
                  </div>
                </div>
                <div className="drawer-section">
                  <p className="label-caps">Direct Relationships</p>
                  <div className="relation-list">
                    {outgoing.concat(incoming).map((edge, index) => {
                      const peerId = edge.source === selectedNodeId ? edge.target : edge.source;
                      const peer = graph.nodes.find((node) => node.id === peerId);
                      if (!peer) return null;
                      const PeerIcon = typeToIcon[peer.type] || Network;
                      return (
                        <button key={`${edge.type}-${peerId}-${index}`} type="button" className="relation-card" onClick={() => setSelectedNodeId(peerId)}>
                          <div className={`relation-icon ${toneByType[peer.type]}`}><PeerIcon size={16} /></div>
                          <div>
                            <span>{edge.type.replaceAll("_", " ")}</span>
                            <strong>{nodeLabel(peer)}</strong>
                          </div>
                        </button>
                      );
                    })}
                    {!outgoing.length && !incoming.length ? <div className="muted">No direct relationships in current scope.</div> : null}
                  </div>
                </div>
                <div className="drawer-section">
                  <p className="label-caps">Relevant Clauses</p>
                  {relatedClauses.length ? relatedClauses.map((clause) => (
                    <article key={clause.id} className="clause-card">
                      <p>{clause.text || nodeLabel(clause)}</p>
                    </article>
                  )) : <div className="muted">No clause edges in current scope.</div>}
                </div>
                {queryResult ? (
                  <div className="drawer-section">
                    <p className="label-caps">Query Result</p>
                    <pre className="json-block compact">{JSON.stringify(queryResult, null, 2)}</pre>
                  </div>
                ) : null}
              </div>
              <div className="graph-drawer-footer">
                <button type="button" className="ghost-button" onClick={viewDetails}>View Details</button>
                <button type="button" onClick={() => setPage("query")}>Run Query</button>
              </div>
            </>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
