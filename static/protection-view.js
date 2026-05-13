let _bpSISelectedPhase = "A";
let _bpInSIMode = false;
let compareData = null;

// ── Protection View Filter ─────────────────────────────────────────────────────
// When active, hides "infrastructure" node types (wires, raw CT/VT sensors) so
// only the protection chain and primary switching equipment remains visible.
// This makes it easier to trace CTTB → Relay → Breaker paths without clutter.

let _protViewActive = false;

// Types that are HIDDEN in protection view — physical wiring / low-level sensors
const PROT_VIEW_HIDDEN_TYPES = new Set([
  "Wire",
  "CurrentTransformer",
  "VoltageTransformer",
  "DualWindingVT",
  "PowerLine",
  "Line",
]);

function toggleProtectionView() {
  _protViewActive = !_protViewActive;
  const btn = document.getElementById("prot-view-btn");
  if (btn) {
    btn.style.color       = _protViewActive ? "#0f0" : "";
    btn.style.borderColor = _protViewActive ? "#0f0" : "";
    btn.style.background  = _protViewActive ? "#001a00" : "";
  }
  applyProtectionViewFilter();
}

/**
 * Show/hide SVG node groups and wire paths based on the protection view filter.
 * Edges are individual <path> elements with data-src / data-tgt attributes so
 * we select by attribute rather than by bound datum.
 */
function applyProtectionViewFilter() {
  if (!_protViewActive) {
    d3.select("#zoom-group").selectAll(".node").style("display", null);
    d3.select("#zoom-group").selectAll("[data-src]").style("display", null);
    return;
  }

  // Hide nodes whose type is in the hidden set
  d3.select("#zoom-group").selectAll(".node").each(function(d) {
    d3.select(this).style("display", (d && PROT_VIEW_HIDDEN_TYPES.has(d.type)) ? "none" : null);
  });

  // Build set of hidden IDs for edge path filtering
  const hiddenIds = new Set();
  if (currentData && currentData.nodes) {
    currentData.nodes.forEach(n => { if (PROT_VIEW_HIDDEN_TYPES.has(n.type)) hiddenIds.add(n.id); });
  }

  // Hide wire paths that connect to or from a hidden device
  d3.select("#zoom-group").selectAll("[data-src]").each(function() {
    const el = d3.select(this);
    const hidden = hiddenIds.has(el.attr("data-src")) || hiddenIds.has(el.attr("data-tgt"));
    el.style("display", hidden ? "none" : null);
  });
}
