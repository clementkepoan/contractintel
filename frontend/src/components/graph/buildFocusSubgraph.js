const EVIDENCE_TYPES = new Set(["Clause", "ClauseBundle", "ValidationWarning"]);

function sortBySourceOrder(left, right) {
  return Number(left.source_order || 0) - Number(right.source_order || 0);
}

function sortEvidence(left, right) {
  const leftKey = `${left.type}:${left.severity || ""}:${left.clause_type || ""}:${left.text || left.message || left.id}`;
  const rightKey = `${right.type}:${right.severity || ""}:${right.clause_type || ""}:${right.text || right.message || right.id}`;
  return leftKey.localeCompare(rightKey, "zh-Hant");
}

function nodesById(graph) {
  return new Map(graph.nodes.map((node) => [node.id, node]));
}

function buildAdjacency(graph) {
  const incoming = new Map();
  const outgoing = new Map();

  for (const edge of graph.edges) {
    const sourceEdges = outgoing.get(edge.source) || [];
    sourceEdges.push(edge);
    outgoing.set(edge.source, sourceEdges);

    const targetEdges = incoming.get(edge.target) || [];
    targetEdges.push(edge);
    incoming.set(edge.target, targetEdges);
  }

  return { incoming, outgoing };
}

function subgraphFromIds(graph, includeIds) {
  return {
    nodes: graph.nodes.filter((node) => includeIds.has(node.id)),
    edges: graph.edges.filter((edge) => includeIds.has(edge.source) && includeIds.has(edge.target)),
  };
}

export function buildPortfolioOverviewSubgraph(graph) {
  const includeIds = new Set(graph.nodes.filter((node) => node.type === "Contract").map((node) => node.id));
  return subgraphFromIds(graph, includeIds);
}

export function buildContractFocusSubgraph(graph, contractId) {
  if (!contractId) return buildPortfolioOverviewSubgraph(graph);

  const includeIds = new Set([contractId]);
  const contractMilestones = graph.nodes
    .filter((node) => node.type === "Milestone" && node.contract_id === contractId)
    .sort(sortBySourceOrder);

  for (const milestone of contractMilestones) includeIds.add(milestone.id);

  const contractWarnings = graph.nodes.filter((node) => node.type === "ValidationWarning" && node.contract_id === contractId);
  for (const warning of contractWarnings) includeIds.add(warning.id);

  return subgraphFromIds(graph, includeIds);
}

export function buildMilestoneFocusSubgraph(graph, milestoneId) {
  if (!milestoneId) return { nodes: [], edges: [] };

  const byId = nodesById(graph);
  const milestone = byId.get(milestoneId);
  if (!milestone) return { nodes: [], edges: [] };

  const contractId = milestone.contract_id;
  const includeIds = new Set([milestoneId]);
  if (contractId) includeIds.add(contractId);

  const siblingMilestones = graph.nodes
    .filter((node) => node.type === "Milestone" && node.contract_id === contractId)
    .sort(sortBySourceOrder);
  for (const node of siblingMilestones) includeIds.add(node.id);

  const { incoming, outgoing } = buildAdjacency(graph);

  const milestoneOutgoing = outgoing.get(milestoneId) || [];
  const milestoneIncoming = incoming.get(milestoneId) || [];

  for (const edge of milestoneOutgoing) {
    if (["HAS_WORKITEM", "TRIGGERS_PAYMENT"].includes(edge.type)) includeIds.add(edge.target);
  }

  const supportingClauseIds = milestoneIncoming
    .filter((edge) => edge.type === "SUPPORTS")
    .map((edge) => edge.source);

  const invoiceIds = [...includeIds].filter((id) => byId.get(id)?.type === "Invoice");
  for (const invoiceId of invoiceIds) {
    const invoiceOutgoing = outgoing.get(invoiceId) || [];
    for (const edge of invoiceOutgoing) {
      if (edge.type === "SETTLED_BY") includeIds.add(edge.target);
    }
  }

  const baseSubgraph = subgraphFromIds(graph, includeIds);

  if (!supportingClauseIds.length) {
    return baseSubgraph;
  }

  const supportingClauses = supportingClauseIds
    .map((id) => byId.get(id))
    .filter(Boolean)
    .sort(sortEvidence);

  const clauseBundleId = `bundle_clause_${milestoneId}`;
  const clauseBundleNode = {
    id: clauseBundleId,
    type: "ClauseBundle",
    contract_id: contractId,
    milestone_id: milestoneId,
    name: `Supporting clauses (${supportingClauses.length})`,
    text: supportingClauses.map((clause) => clause.text).filter(Boolean).join("\n\n"),
    clause_count: supportingClauses.length,
    clause_type: "supporting_clauses",
    clauses: supportingClauses.map((clause) => ({
      id: clause.id,
      text: clause.text,
      clause_type: clause.clause_type,
      location: clause.location,
      source_file: clause.source_file,
    })),
  };

  return {
    nodes: [
      ...baseSubgraph.nodes.filter((node) => !supportingClauseIds.includes(node.id)),
      clauseBundleNode,
    ],
    edges: [
      ...baseSubgraph.edges.filter((edge) => !(edge.type === "SUPPORTS" && supportingClauseIds.includes(edge.source) && edge.target === milestoneId)),
      { source: clauseBundleId, target: milestoneId, type: "SUPPORTS" },
    ],
  };
}

export function isEvidenceNode(node) {
  return EVIDENCE_TYPES.has(node?.type);
}
