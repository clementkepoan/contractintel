import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { forceCenter, forceCollide, forceManyBody, forceX, forceY } from "d3-force";
import { AlertTriangle, Boxes, CircleDollarSign, FileText, Flag, Network, ReceiptText, ScanSearch, Scale, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";

import { formatDate, formatMoney } from "../../api/client.js";

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

const TYPE_DIMENSIONS = {
  Contract: { width: 280, height: 96 },
  Milestone: { width: 280, height: 108 },
  WorkItem: { width: 210, height: 76 },
  Invoice: { width: 210, height: 76 },
  Payment: { width: 210, height: 76 },
  Clause: { width: 220, height: 76 },
  ClauseBundle: { width: 236, height: 84 },
  ValidationWarning: { width: 224, height: 82 },
};

const PAYMENT_STATE_LABELS = {
  no_invoice: "No invoice",
  invoiced_unpaid: "Invoiced, unpaid",
  partially_paid: "Partially paid",
  fully_paid: "Fully paid",
};

function nodeLabel(node) {
  return node?.name || node?.description || node?.message || node?.text || node?.id || "Unknown";
}

function nodeDimensions(node) {
  return TYPE_DIMENSIONS[node?.type] || { width: 220, height: 84 };
}

function edgeTone(edgeType) {
  if (edgeType === "GOVERNS" || edgeType === "SUPPORTS") return "#fb923c";
  if (edgeType === "ATTACHED_TO") return "#ef4444";
  if (edgeType === "CONFLICTS_WITH") return "#dc2626";
  if (edgeType === "TRIGGERS_PAYMENT" || edgeType === "SETTLED_BY") return "#3b82f6";
  if (edgeType === "HAS_MILESTONE") return "#94a3b8";
  return "#cbd5e1";
}

function fillForNode(node) {
  if (node.type === "Contract") return "#0f172a";
  if (node.type === "Milestone") {
    if (node.payment_state === "fully_paid") return "#ecfdf5";
    if (node.payment_state === "partially_paid") return "#eff6ff";
    if (node.payment_state === "invoiced_unpaid") return "#fffbeb";
    return "#f8fafc";
  }
  if (node.type === "Invoice") return "#fef2f2";
  if (node.type === "Payment") return "#ecfdf5";
  if (node.type === "Clause") return "#fff7ed";
  if (node.type === "ClauseBundle") return "#fff7ed";
  if (node.type === "ValidationWarning") return "#fff1f2";
  return "#ffffff";
}

function borderForNode(node) {
  if (node.type === "Contract") return "rgba(51, 65, 85, 0.85)";
  if (node.type === "Milestone") {
    if (node.payment_state === "fully_paid") return "rgba(16, 185, 129, 0.55)";
    if (node.payment_state === "partially_paid") return "rgba(59, 130, 246, 0.55)";
    if (node.payment_state === "invoiced_unpaid") return "rgba(245, 158, 11, 0.55)";
    return "rgba(148, 163, 184, 0.42)";
  }
  if (node.type === "Invoice") return "rgba(244, 63, 94, 0.35)";
  if (node.type === "Payment") return "rgba(16, 185, 129, 0.35)";
  if (node.type === "Clause") return "rgba(249, 115, 22, 0.4)";
  if (node.type === "ClauseBundle") return "rgba(249, 115, 22, 0.46)";
  if (node.type === "ValidationWarning") return "rgba(239, 68, 68, 0.38)";
  return "rgba(148, 163, 184, 0.3)";
}

function textColor(node) {
  return node.type === "Contract" ? "#f8fafc" : "#0f172a";
}

function metaForNode(node) {
  if (node.type === "Milestone") {
    return [PAYMENT_STATE_LABELS[node.payment_state] || node.payment_state, node.amount ? formatMoney(node.amount, "TWD") : null].filter(Boolean).join(" • ");
  }
  if (node.type === "Clause") return node.clause_type || "clause";
  if (node.type === "ClauseBundle") return `${node.clause_count || 0} bundled clauses`;
  if (node.type === "ValidationWarning") return String(node.severity || "info").toUpperCase();
  if (node.type === "Invoice" || node.type === "Payment") return [node.amount ? formatMoney(node.amount, "TWD") : null, node.date ? formatDate(node.date) : null].filter(Boolean).join(" • ");
  if (node.status) return String(node.status);
  return "";
}

function radiusForNode(node) {
  if (node.type === "Contract") return 240;
  if (node.type === "Milestone") return 350;
  if (node.type === "Invoice") return 410;
  if (node.type === "Payment") return 500;
  if (node.type === "WorkItem") return 430;
  if (node.type === "Clause") return 285;
  if (node.type === "ClauseBundle") return 310;
  if (node.type === "ValidationWarning") return 320;
  return 360;
}

function chargeForNode(node) {
  if (node.type === "Clause") return -180;
  if (node.type === "ClauseBundle") return -220;
  if (node.type === "ValidationWarning") return -220;
  if (node.type === "WorkItem") return -240;
  return -340;
}

function linkDistance(link) {
  const edgeType = link.type || link.edgeType;
  if (edgeType === "SUPPORTS") return 165;
  if (edgeType === "GOVERNS") return 210;
  if (edgeType === "ATTACHED_TO") return 220;
  if (edgeType === "HAS_WORKITEM") return 210;
  if (edgeType === "TRIGGERS_PAYMENT") return 225;
  if (edgeType === "SETTLED_BY") return 205;
  if (edgeType === "HAS_MILESTONE") return 250;
  return 220;
}

function linkStrength(link) {
  const edgeType = link.type || link.edgeType;
  if (edgeType === "SUPPORTS" || edgeType === "ATTACHED_TO") return 0.12;
  if (edgeType === "GOVERNS") return 0.1;
  if (edgeType === "HAS_MILESTONE") return 0.08;
  return 0.1;
}

function buildAdjacency(graph) {
  const outgoing = new Map();
  const incoming = new Map();

  for (const edge of graph.edges) {
    const sourceEdges = outgoing.get(edge.source) || [];
    sourceEdges.push(edge);
    outgoing.set(edge.source, sourceEdges);

    const targetEdges = incoming.get(edge.target) || [];
    targetEdges.push(edge);
    incoming.set(edge.target, targetEdges);
  }

  return { outgoing, incoming };
}

function spreadAngles(count, centerAngle = 0, spread = Math.PI / 2) {
  if (count <= 0) return [];
  if (count === 1) return [centerAngle];
  const step = spread / (count - 1);
  const start = centerAngle - spread / 2;
  return Array.from({ length: count }, (_, index) => start + step * index);
}

function findPrimaryContract(graph, contractId) {
  if (contractId) return graph.nodes.find((node) => node.id === contractId && node.type === "Contract") || null;
  return graph.nodes.find((node) => node.type === "Contract") || null;
}

function buildSeedLayout(graph, contractId, focusedMilestoneId) {
  const positions = new Map();
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const { outgoing, incoming } = buildAdjacency(graph);
  const contracts = graph.nodes.filter((node) => node.type === "Contract");

  if (!contractId && contracts.length) {
    const ring = Math.max(220, 180 + contracts.length * 28);
    contracts.forEach((contract, index) => {
      const angle = (-Math.PI / 2) + (index * (Math.PI * 2 / contracts.length));
      positions.set(contract.id, {
        x: Math.cos(angle) * ring,
        y: Math.sin(angle) * ring,
      });
    });
    return positions;
  }

  const contract = findPrimaryContract(graph, contractId);
  if (!contract) return positions;

  positions.set(contract.id, { x: 0, y: 0 });

  const milestones = graph.nodes
    .filter((node) => node.type === "Milestone" && node.contract_id === contract.id)
    .sort((left, right) => Number(left.source_order || 0) - Number(right.source_order || 0));

  const milestoneRing = 350;
  const milestoneAngles = spreadAngles(Math.max(milestones.length, 1), -Math.PI / 2, Math.PI * 1.35);
  const milestoneAngleById = new Map();

  milestones.forEach((milestone, index) => {
    const angle = milestoneAngles[index] ?? (-Math.PI / 2);
    milestoneAngleById.set(milestone.id, angle);
    positions.set(milestone.id, {
      x: Math.cos(angle) * milestoneRing,
      y: Math.sin(angle) * milestoneRing,
    });
  });

  const warnings = graph.nodes.filter((node) => node.type === "ValidationWarning" && node.contract_id === contract.id);
  spreadAngles(warnings.length, -Math.PI / 2, Math.PI * 0.9).forEach((angle, index) => {
    const warning = warnings[index];
    if (!warning) return;
    positions.set(warning.id, {
      x: Math.cos(angle) * 210,
      y: Math.sin(angle) * 210 - 40,
    });
  });

  if (!focusedMilestoneId || !milestoneAngleById.has(focusedMilestoneId)) {
    return positions;
  }

  const focusAngle = milestoneAngleById.get(focusedMilestoneId) ?? (-Math.PI / 2);
  const focusPoint = positions.get(focusedMilestoneId) || { x: Math.cos(focusAngle) * milestoneRing, y: Math.sin(focusAngle) * milestoneRing };

  const supportingClauses = (incoming.get(focusedMilestoneId) || [])
    .filter((edge) => edge.type === "SUPPORTS")
    .map((edge) => byId.get(edge.source))
    .filter(Boolean);

  spreadAngles(supportingClauses.length, focusAngle, Math.min(Math.PI * 0.55, 0.32 * Math.max(supportingClauses.length - 1, 1))).forEach((angle, index) => {
    const clause = supportingClauses[index];
    if (!clause) return;
    positions.set(clause.id, {
      x: Math.cos(angle) * 560,
      y: Math.sin(angle) * 560,
    });
  });

  const workItems = (outgoing.get(focusedMilestoneId) || [])
    .filter((edge) => edge.type === "HAS_WORKITEM")
    .map((edge) => byId.get(edge.target))
    .filter(Boolean);

  spreadAngles(workItems.length, focusAngle + 0.24, Math.min(Math.PI * 0.55, 0.32 * Math.max(workItems.length - 1, 1))).forEach((angle, index) => {
    const workItem = workItems[index];
    if (!workItem) return;
    positions.set(workItem.id, {
      x: Math.cos(angle) * 510,
      y: Math.sin(angle) * 510 + 36,
    });
  });

  const invoices = (outgoing.get(focusedMilestoneId) || [])
    .filter((edge) => edge.type === "TRIGGERS_PAYMENT")
    .map((edge) => byId.get(edge.target))
    .filter(Boolean);

  spreadAngles(invoices.length, focusAngle - 0.22, Math.min(Math.PI * 0.45, 0.28 * Math.max(invoices.length - 1, 1))).forEach((angle, index) => {
    const invoice = invoices[index];
    if (!invoice) return;
    positions.set(invoice.id, {
      x: Math.cos(angle) * 500,
      y: Math.sin(angle) * 500 - 36,
    });
  });

  invoices.forEach((invoice) => {
    const invoicePoint = positions.get(invoice.id);
    if (!invoicePoint) return;
    const payments = (outgoing.get(invoice.id) || [])
      .filter((edge) => edge.type === "SETTLED_BY")
      .map((edge) => byId.get(edge.target))
      .filter(Boolean);
    const paymentAngles = spreadAngles(payments.length, Math.atan2(invoicePoint.y, invoicePoint.x), Math.min(Math.PI * 0.35, 0.22 * Math.max(payments.length - 1, 1)));
    payments.forEach((payment, index) => {
      const angle = paymentAngles[index] ?? focusAngle;
      positions.set(payment.id, {
        x: Math.cos(angle) * 640,
        y: Math.sin(angle) * 640,
      });
    });
  });

  return positions;
}

function wrapLines(ctx, text, maxWidth, maxLines) {
  const source = String(text || "").trim();
  if (!source) return [];

  const tokens = /\s/.test(source)
    ? source.split(/(\s+)/).filter(Boolean)
    : Array.from(source);

  const lines = [];
  let current = "";
  let consumed = 0;

  for (const token of tokens) {
    const candidate = current ? `${current}${token}` : token;
    if (!current || ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
      consumed += token.length;
      continue;
    }

    lines.push(current.trim());
    current = token.trimStart();
    if (lines.length === maxLines - 1) break;
    consumed += token.length;
  }

  if (lines.length < maxLines && current) lines.push(current.trim());

  const joinedLength = lines.join("").length;
  const truncated = consumed < source.length || joinedLength < source.replace(/\s+/g, "").length;
  if (truncated && lines.length) {
    let last = lines[lines.length - 1];
    while (ctx.measureText(`${last}…`).width > maxWidth && last.length > 1) {
      last = last.slice(0, -1);
    }
    lines[lines.length - 1] = `${last}…`;
  }

  return lines.slice(0, maxLines);
}

function drawRoundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function iconGlyph(node) {
  if (node.type === "Contract") return "◫";
  if (node.type === "Milestone") return "⚑";
  if (node.type === "WorkItem") return "✦";
  if (node.type === "Invoice") return "▣";
  if (node.type === "Payment") return "◉";
  if (node.type === "Clause") return "§";
  if (node.type === "ClauseBundle") return "§";
  if (node.type === "ValidationWarning") return "!";
  return "•";
}

export function GraphCanvas({ graph, layoutNonce, selectedNodeId, highlightIds, onSelectNode, onRelayout, contractId, focusedMilestoneId }) {
  const graphRef = useRef(null);
  const shellRef = useRef(null);
  const positionsRef = useRef(new Map());
  const lastLayoutNonceRef = useRef(layoutNonce);
  const [viewport, setViewport] = useState({ width: 960, height: 720 });
  const seededPositions = useMemo(() => buildSeedLayout(graph, contractId, focusedMilestoneId), [contractId, focusedMilestoneId, graph]);

  const graphData = useMemo(() => ({
    nodes: graph.nodes.map((node) => {
      const saved = positionsRef.current.get(node.id);
      const seeded = seededPositions.get(node.id);
      return saved
        ? { ...node, x: saved.x, y: saved.y, vx: 0, vy: 0, fx: saved.fx, fy: saved.fy, targetX: seeded?.x ?? saved.x, targetY: seeded?.y ?? saved.y }
        : { ...node, x: seeded?.x, y: seeded?.y, targetX: seeded?.x ?? 0, targetY: seeded?.y ?? 0 };
    }),
    links: graph.edges
      .filter((edge) => edge.type !== "CONFLICTS_WITH")
      .map((edge) => ({ ...edge, edgeType: edge.type })),
  }), [graph, seededPositions]);


  useEffect(() => {
    if (!shellRef.current) return undefined;
    const element = shellRef.current;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = Math.max(480, Math.floor(entry.contentRect.width));
      const height = Math.max(520, Math.floor(entry.contentRect.height));
      setViewport((current) => (current.width === width && current.height === height ? current : { width, height }));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (lastLayoutNonceRef.current !== layoutNonce) {
      positionsRef.current = new Map();
      lastLayoutNonceRef.current = layoutNonce;
    }
  }, [layoutNonce]);

  useEffect(() => {
    if (!graphRef.current) return;

    for (const node of graphData.nodes) {
      const saved = positionsRef.current.get(node.id);
      node.fx = saved?.fx;
      node.fy = saved?.fy;
    }

    graphRef.current.d3Force("charge", forceManyBody().strength(chargeForNode));
    graphRef.current.d3Force("collision", forceCollide((node) => Math.max(nodeDimensions(node).width, nodeDimensions(node).height) * 0.44 + 22).iterations(3));
    graphRef.current.d3Force("center", forceCenter(0, 0));
    graphRef.current.d3Force("radial", null);
    graphRef.current.d3Force("forceX", forceX((node) => node.targetX ?? 0).strength((node) => (node.type === "Contract" ? 0.32 : node.type === "Clause" ? 0.28 : 0.2)));
    graphRef.current.d3Force("forceY", forceY((node) => node.targetY ?? 0).strength((node) => (node.type === "Contract" ? 0.32 : node.type === "Clause" ? 0.28 : 0.2)));

    const linkForce = graphRef.current.d3Force("link");
    if (linkForce) {
      linkForce.distance(linkDistance);
      linkForce.strength(linkStrength);
    }

    graphRef.current.d3ReheatSimulation();
  }, [graphData, layoutNonce]);

  function drawNode(node, ctx, globalScale) {
    const { width, height } = nodeDimensions(node);
    const active = node.id === selectedNodeId;
    const connected = highlightIds?.has(node.id);
    const x = node.x - width / 2;
    const y = node.y - height / 2;
    const fill = fillForNode(node);
    const border = borderForNode(node);

    ctx.save();
    if (active) {
      ctx.shadowColor = "rgba(59, 130, 246, 0.28)";
      ctx.shadowBlur = 26;
    } else if (connected) {
      ctx.shadowColor = "rgba(148, 163, 184, 0.18)";
      ctx.shadowBlur = 16;
    }

    drawRoundedRect(ctx, x, y, width, height, node.type === "Clause" || node.type === "ValidationWarning" ? height / 2 : 18);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = active ? 2.2 : connected ? 1.8 : 1.2;
    ctx.strokeStyle = active ? "rgba(59, 130, 246, 0.9)" : border;
    if (node.type === "Clause") ctx.setLineDash([5, 5]);
    ctx.stroke();
    ctx.setLineDash([]);

    const paddingX = 14;
    const headerY = y + 12;
    const compactNode = node.type === "Clause" || node.type === "ValidationWarning";
    const warningNode = node.type === "ValidationWarning";
    const iconSize = compactNode ? 18 : 24;

    ctx.fillStyle = node.type === "Contract" ? "rgba(255,255,255,0.15)" : "rgba(15, 23, 42, 0.06)";
    drawRoundedRect(ctx, x + paddingX, headerY, iconSize, iconSize, iconSize / 2);
    ctx.fill();

    ctx.fillStyle = node.type === "Contract" ? "#f8fafc" : "#334155";
    ctx.font = `${compactNode ? 10 : 12}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(iconGlyph(node), x + paddingX + iconSize / 2, headerY + iconSize / 2 + 0.5);

    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillStyle = node.type === "Contract" ? "rgba(248, 250, 252, 0.86)" : "#64748b";
    ctx.font = `${compactNode ? 8 : 10}px Inter, system-ui, sans-serif`;
    ctx.fillText(String(node.type || "NODE").toUpperCase(), x + paddingX + iconSize + 8, headerY + 2);

    ctx.fillStyle = textColor(node);
    ctx.font = `${warningNode ? 9 : compactNode ? 10 : 12}px Inter, system-ui, sans-serif`;
    const titleLines = wrapLines(ctx, nodeLabel(node), width - paddingX * 2, node.type === "Contract" ? 3 : warningNode ? 3 : 2);
    titleLines.forEach((line, index) => {
      ctx.fillText(line, x + paddingX, y + (compactNode ? 34 : 40) + index * (warningNode ? 11 : compactNode ? 12 : 13));
    });

    const meta = metaForNode(node);
    if (meta) {
      ctx.fillStyle = node.type === "Contract" ? "rgba(226, 232, 240, 0.86)" : "#475569";
      ctx.font = `${warningNode ? 7.5 : compactNode ? 8 : 9}px Inter, system-ui, sans-serif`;
      const metaLine = wrapLines(ctx, meta, width - paddingX * 2, 1)[0];
      ctx.fillText(metaLine, x + paddingX, y + height - (compactNode ? 15 : 18));
    }

    ctx.restore();
  }

  function paintPointerArea(node, color, ctx) {
    const { width, height } = nodeDimensions(node);
    ctx.fillStyle = color;
    drawRoundedRect(ctx, node.x - width / 2, node.y - height / 2, width, height, node.type === "Clause" || node.type === "ValidationWarning" ? height / 2 : 18);
    ctx.fill();
  }

  function zoomBy(multiplier) {
    if (!graphRef.current) return;
    const current = graphRef.current.zoom();
    graphRef.current.zoom(current * multiplier, 240);
  }

  return (
    <div ref={shellRef} className="force-graph-shell">
      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        width={viewport.width}
        height={viewport.height}
        backgroundColor="#f8fafc"
        nodeCanvasObject={drawNode}
        nodePointerAreaPaint={paintPointerArea}
        nodeRelSize={8}
        linkColor={(link) => edgeTone(link.edgeType)}
        linkWidth={(link) => (link.edgeType === "HAS_MILESTONE" ? 2.1 : link.edgeType === "CONFLICTS_WITH" ? 2.4 : 1.5)}
        linkLineDash={(link) => (link.edgeType === "GOVERNS" || link.edgeType === "ATTACHED_TO" || link.edgeType === "CONFLICTS_WITH" ? [5, 5] : null)}
        linkCurvature={(link) => (link.edgeType === "SUPPORTS" || link.edgeType === "ATTACHED_TO" ? 0.12 : 0)}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkDirectionalArrowColor={(link) => edgeTone(link.edgeType)}
        cooldownTicks={80}
        onNodeClick={(node) => onSelectNode(node.id)}
        onNodeDragEnd={(node) => {
          node.fx = node.x;
          node.fy = node.y;
          positionsRef.current.set(node.id, { x: node.x, y: node.y, fx: node.fx, fy: node.fy });
        }}
        onEngineStop={() => {
          for (const node of graphData.nodes) {
            positionsRef.current.set(node.id, { x: node.x, y: node.y, fx: node.fx, fy: node.fy });
          }
        }}
        enableNodeDrag
      />
      <div className="graph-force-tools">
        <button type="button" className="tool-button" onClick={() => zoomBy(1.18)}><ZoomIn size={18} /></button>
        <button type="button" className="tool-button" onClick={() => zoomBy(0.84)}><ZoomOut size={18} /></button>
        <button type="button" className="tool-button" onClick={() => graphRef.current?.zoomToFit(320, 80)}><ScanSearch size={18} /></button>
        <button type="button" className="tool-button" onClick={() => { graphRef.current?.centerAt(0, 0, 320); graphRef.current?.zoom(1, 320); }}><Network size={18} /></button>
        <button type="button" className="tool-button" onClick={onRelayout}><RotateCcw size={18} /></button>
      </div>
    </div>
  );
}
