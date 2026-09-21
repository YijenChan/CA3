const requestedRound = Number(new URLSearchParams(window.location.search).get("round"));
const state = { data: null, round: [0, 1, 2].includes(requestedRound) ? requestedRound : 2 };

const $ = (id) => document.getElementById(id);
const shortId = (value, size = 18) => value && value.length > size ? `${value.slice(0, size)}…` : value;
const actionLabel = (value) => String(value || "—").replaceAll("_", " ");

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: rect.width, height: rect.height };
}

function roundAliases(round) {
  const final = state.data.rounds[state.data.rounds.length - 1];
  const persistentToFinal = Object.fromEntries(
    Object.entries(final.aliases.communities).map(([alias, id]) => [id, alias]),
  );
  return Object.fromEntries(round.communities.map((item) => [item.id, persistentToFinal[item.id] || item.alias]));
}

function drawArrow(ctx, x1, y1, x2, y2, color, dashed = false) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  if (dashed) ctx.setLineDash([5, 4]);
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  const angle = Math.atan2(y2 - y1, x2 - x1);
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - 7 * Math.cos(angle - Math.PI / 6), y2 - 7 * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(x2 - 7 * Math.cos(angle + Math.PI / 6), y2 - 7 * Math.sin(angle + Math.PI / 6));
  ctx.closePath(); ctx.fill(); ctx.restore();
}

function drawCommunity(ctx, x, y, label, role, active) {
  const fill = role === "entry" ? "#fff2e3" : role === "seed" ? "#edf3ff" : "#f2effc";
  const stroke = active ? "#d69a43" : role === "entry" ? "#d99a48" : role === "seed" ? "#6f91d2" : "#8d7cc8";
  ctx.save();
  ctx.shadowColor = "rgba(60,75,110,.12)"; ctx.shadowBlur = 8; ctx.shadowOffsetY = 3;
  ctx.fillStyle = fill; ctx.strokeStyle = stroke; ctx.lineWidth = active ? 2.5 : 1.5;
  ctx.beginPath(); ctx.roundRect(x - 28, y - 21, 56, 42, 12); ctx.fill(); ctx.stroke();
  ctx.shadowColor = "transparent";
  ctx.fillStyle = "#31405c"; ctx.font = "700 11px Inter, sans-serif"; ctx.textAlign = "center";
  ctx.fillText(label, x, y - 2);
  ctx.fillStyle = "#7c8799"; ctx.font = "8px Inter, sans-serif";
  ctx.fillText(role, x, y + 11);
  if (active) { ctx.fillStyle = "#d69a43"; ctx.beginPath(); ctx.arc(x + 22, y - 16, 4, 0, Math.PI * 2); ctx.fill(); }
  ctx.restore();
}

function drawFMG(round) {
  const canvas = $("fmg-canvas");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const finalAliases = roundAliases(round);
  const final = state.data.rounds[2];
  const roleById = {};
  Object.entries(final.aliases.communities).forEach(([alias, id]) => {
    roleById[id] = alias === "C01" ? "entry" : alias === "C04" ? "seed" : "bridge";
  });
  const positions = {
    C01: [0.14, 0.63], C02: [0.38, 0.25], C03: [0.56, 0.63], C04: [0.84, 0.63],
  };
  const nodes = round.communities.map((item, index) => {
    const alias = finalAliases[item.id];
    const pos = positions[alias] || [0.18 + index * 0.22, 0.6];
    return { item, alias, x: pos[0] * width, y: pos[1] * height, role: roleById[item.id] || "evidence" };
  });
  const nodeById = Object.fromEntries(nodes.map((node) => [node.item.id, node]));
  round.backbone.edges.forEach((edge) => {
    const source = nodeById[edge.source_id]; const target = nodeById[edge.target_id];
    if (!source || !target) return;
    drawArrow(ctx, source.x + 29, source.y, target.x - 29, target.y, edge.retrieval_only ? "#927fc4" : "#c76f80", edge.retrieval_only);
  });
  const scheduled = round.scheduled_coi.community_id;
  nodes.forEach((node) => drawCommunity(ctx, node.x, node.y, node.alias, node.role, node.item.id === scheduled));
}

function drawAttackGraph(round) {
  const canvas = $("attack-canvas");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const graph = state.data.attack_summary;
  const visible = round.round === 2;
  const positions = [
    [0.12, 0.33], [0.38, 0.33], [0.64, 0.33], [0.88, 0.33],
  ];
  if (!visible) {
    ctx.fillStyle = "#8a94a6"; ctx.font = "600 12px Inter, sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Attack summary remains provisional until the entry boundary is resolved", width / 2, height / 2);
    return;
  }
  const nodes = Object.fromEntries(graph.nodes.map((node, i) => [node.id, { ...node, x: positions[i][0] * width, y: positions[i][1] * height }]));
  graph.edges.filter((edge) => edge.label !== "SENDTO").forEach((edge) => {
    const source = nodes[edge.source]; const target = nodes[edge.target];
    drawArrow(ctx, source.x + 39, source.y, target.x - 39, target.y, edge.stage === "ingress" ? "#d69a43" : "#c96e7f", false);
    ctx.fillStyle = "#7f899b"; ctx.font = "700 8px Inter, sans-serif"; ctx.textAlign = "center";
    ctx.fillText(edge.label, (source.x + target.x) / 2, source.y - 11);
  });
  const send = graph.edges.find((edge) => edge.label === "SENDTO");
  if (send) {
    const source = nodes[send.source]; const target = nodes[send.target];
    ctx.save(); ctx.strokeStyle = "#8d7cc8"; ctx.lineWidth = 1.8; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(source.x, source.y + 30); ctx.quadraticCurveTo((source.x + target.x) / 2, source.y + 78, target.x, target.y + 30); ctx.stroke(); ctx.restore();
    ctx.fillStyle = "#7a68ae"; ctx.font = "700 8px Inter, sans-serif"; ctx.textAlign = "center";
    ctx.fillText("CALLBACK", (source.x + target.x) / 2, source.y + 67);
  }
  Object.values(nodes).forEach((node) => {
    const colors = node.kind === "network" ? ["#fff4e7", "#d49a4c"] : node.kind === "file" ? ["#f2effb", "#8978bc"] : ["#edf4ff", "#688bd0"];
    ctx.save(); ctx.fillStyle = colors[0]; ctx.strokeStyle = colors[1]; ctx.lineWidth = 1.8;
    ctx.beginPath(); ctx.roundRect(node.x - 38, node.y - 27, 76, 54, 12); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#33415d"; ctx.font = "700 9.5px Inter, sans-serif"; ctx.textAlign = "center";
    const label = node.label.length > 14 ? `${node.label.slice(0, 13)}…` : node.label;
    ctx.fillText(label, node.x, node.y - 2);
    ctx.fillStyle = "#7e899b"; ctx.font = "7.5px Inter, sans-serif";
    ctx.fillText(node.subtitle.split(" ").slice(0, 2).join(" "), node.x, node.y + 12); ctx.restore();
  });
  ctx.fillStyle = "#8a94a6"; ctx.font = "8.5px Inter, sans-serif"; ctx.textAlign = "left";
  ctx.fillText("Controller-committed projection · not an aggregation of agent hypotheses", 12, height - 13);
}

function renderRail(round) {
  const steps = [
    ["Seed initialized", "C04 · anchor + bounded context"],
    ["Bridge recovered", "C02/C03 · admitted witnesses"],
    ["Entry verified", "C01 · ingress + callback + effect"],
    ["Summary projected", "witnessed attack graph"],
  ];
  $("state-rail").innerHTML = steps.map((step, index) => {
    const status = index < round.round + 1 ? "done" : index === round.round + 1 ? "active" : "";
    const finalActive = round.round === 2 && index === 3 ? "active" : status;
    return `<div class="state-step ${finalActive}"><span class="step-index">0${index + 1}</span><strong>${step[0]}</strong><span>${step[1]}</span></div>`;
  }).join("");
}

function renderRoundSwitcher() {
  $("round-switcher").innerHTML = state.data.rounds.map((round) => `
    <button class="round-button ${round.round === state.round ? "active" : ""}" data-round="${round.round}">
      <strong>${round.label}</strong><span>${round.phase}</span>
    </button>`).join("");
  document.querySelectorAll(".round-button").forEach((button) => {
    button.addEventListener("click", () => { state.round = Number(button.dataset.round); render(); });
  });
}

function renderBackbone(round) {
  const finalAliases = roundAliases(round);
  const edgeMarkup = round.backbone.edges.map((edge) => {
    const source = finalAliases[edge.source_id] || edge.source;
    const target = finalAliases[edge.target_id] || edge.target;
    return `<span class="edge-chip ${edge.retrieval_only ? "stitch-edge" : ""}">${source} ${edge.retrieval_only ? "⇢" : "→"} ${target}</span>`;
  });
  const retained = round.backbone.community_ids.map((id) => finalAliases[id]).filter(Boolean);
  $("backbone-path").innerHTML = edgeMarkup.length
    ? edgeMarkup.join("")
    : retained.length
      ? retained.map((alias) => `<span class="path-node">${alias}</span>`).join("")
      : '<span class="inline-note">No retained community yet</span>';
  const gates = [
    ["IC evidence", round.ic_assessment.status === "supported"],
    ["Entry → seed", round.round === 2],
    ["Witnessed transitions", round.backbone.edges.length > 0],
    ["Critical frontiers", round.frontiers.length === 0],
  ];
  $("gate-list").innerHTML = gates.map(([name, pass]) => `<div class="gate ${pass ? "pass" : "open"}">${pass ? "✓" : "○"} ${name}</div>`).join("");
  $("backbone-status").textContent = round.controller.terminal ? "WITNESSED" : "PROVISIONAL";
}

function renderCollaboration(round) {
  const task = round.assistant_task;
  const hasTask = task.task_id !== "not-requested";
  const finalAliases = roundAliases(round);
  const retainedAliases = round.backbone.community_ids.map((id) => finalAliases[id]).filter(Boolean);
  $("lead-input").textContent = `Snapshot: retained {${retainedAliases.join(", ") || "none"}}. IC=${round.ic_assessment.status}; ${round.frontiers.length} critical frontier(s); COI=${shortId(round.scheduled_coi.community_id, 24)}.`;
  $("lead-action").textContent = actionLabel(round.lead.recommended_action);
  $("lead-assessment").textContent = round.lead.assessment;
  $("lead-gap").textContent = `Gap: ${Array.isArray(round.lead.gaps) ? (round.lead.gaps.join(", ") || "none") : round.lead.gaps}`;
  $("task-id").textContent = hasTask ? `TASK · ${task.task_id}` : "TASK · NOT REQUESTED";
  $("assistant-question").textContent = hasTask ? task.question : "No bounded verification task in this round.";
  $("assistant-verdict").textContent = round.assistant.verdict;
  $("assistant-findings").textContent = round.assistant.findings;
  const evidenceAliases = hasTask ? task.evidence_ids.map((id) => Object.entries(round.aliases.evidence).find(([, value]) => value === id)?.[0] || shortId(id, 8)) : [];
  $("evidence-row").innerHTML = evidenceAliases.length
    ? evidenceAliases.map((alias) => `<span class="evidence-chip active">${alias}</span>`).join("")
    : '<span class="evidence-chip">scope closed</span>';
  $("controller-action").textContent = actionLabel(round.controller.action);
  $("controller-reason").textContent = actionLabel(round.controller.reason_code);
  const checks = [
    ["Schema + aliases", "PASS"],
    ["FMG witness gate", round.backbone.edges.length ? "PASS" : "OPEN"],
    ["IC state", round.ic_assessment.status.toUpperCase()],
    ["Agent controls action", "NO"],
  ];
  $("controller-checks").innerHTML = checks.map(([name, value]) => `<div class="control-check"><span>${name}</span><b>${value}</b></div>`).join("");
  $("ledger-event").textContent = round.ledger_delta.event_id;
}

function renderSummary(round) {
  $("summary-status").textContent = round.round === 2 ? "ENTRY RESOLVED" : "PENDING";
  drawAttackGraph(round);
  const events = state.data.attack_summary.edges;
  $("attack-evidence").innerHTML = events.map((edge) => `
    <div class="attack-event"><small>${edge.alias} · ${edge.stage}</small><strong>${edge.label} · ${new Date(edge.timestamp_ns / 1e6).toISOString().slice(11, 19)} UTC</strong></div>`).join("");
}

function render() {
  const round = state.data.rounds[state.round];
  renderRoundSwitcher(); renderRail(round);
  $("case-id").textContent = state.data.case.id;
  $("run-mode").textContent = `${state.data.case.mode} · ${state.data.case.model}`;
  $("ic-state").textContent = round.ic_assessment.status;
  $("control-status").textContent = actionLabel(round.controller.action);
  $("community-count").textContent = `${round.communities.length} communities · ${round.backbone.edges.length} edges`;
  $("phase-badge").textContent = round.phase;
  const reverse = roundAliases(round);
  $("coi-alias").textContent = reverse[round.scheduled_coi.community_id] || "COI";
  $("coi-id").textContent = round.scheduled_coi.community_id;
  $("bridge-status").textContent = round.round === 0 ? "request" : `${Math.max(0, round.communities.length - 1)} retrieved`;
  $("denoise-status").textContent = round.denoising.withdrawn_count
    ? `${round.denoising.withdrawn_count} withdrawn`
    : "0 · no conflict";
  $("entry-status").textContent = round.ic_assessment.status;
  $("frontier-status").textContent = `${round.frontiers.length} open`;
  $("scope-callout").textContent = round.scope_request.kind === "none"
    ? "Scope closed · upstream entry boundary resolved"
    : `${actionLabel(round.scope_request.kind)} · ${round.controller.reason_code.replaceAll("_", " ")}`;
  drawFMG(round); renderBackbone(round); renderCollaboration(round); renderSummary(round);
}

fetch("data/case-study.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => { state.data = data; render(); })
  .catch((error) => {
    document.body.innerHTML = `<main class="load-error"><h1>CA3 data could not be loaded</h1><pre>${error}</pre></main>`;
  });

window.addEventListener("resize", () => { if (state.data) { drawFMG(state.data.rounds[state.round]); drawAttackGraph(state.data.rounds[state.round]); } });
