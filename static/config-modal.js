function showConfigModal(id) {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === id);
  if (!node) return;
  const fieldDefs = {
    VoltageSource: [
      { label: "Nominal Voltage (kV)", key: "nominal_voltage_kv" },
      { label: "Nominal Power (MVA)", key: "nominal_power_mva" },
      { label: "Power Factor (0-1)", key: "pf" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Winding / Connection",
        key: "winding_type",
        type: "select",
        options: [
          { value: "Y",  label: "Y — Wye" },
          { value: "YG", label: "YG — Wye Grounded" },
          { value: "D",  label: "D — Delta" },
        ],
      },
    ],
    CircuitBreaker: [
      { label: "Single Pole Mode", key: "is_single_pole", type: "checkbox" },
      { label: "Continuous Amps (A)", key: "continuous_amps" },
      { label: "Interrupt (kA)", key: "interrupt_ka" },
    ],
    VoltageRegulator: [
      { label: "Nominal Voltage (kV)", key: "nominal_kv" },
      { label: "Tap Position (-16 to +16)", key: "tap_pos" },
      { label: "Step % (default 0.625)", key: "step_percent" },
      { label: "Max Steps (default 16)", key: "max_steps" },
      { label: "Auto Voltage Regulation (AVR)", key: "avr_enabled", type: "checkbox" },
      { label: "AVR Deadband (%)", key: "avr_deadband_pct" },
      { label: "AVR Step Delay (ms)", key: "avr_delay_ms" },
    ],
    PowerTransformer: [
      { label: "Pri (kV)", key: "pri_kv" },
      { label: "Sec (kV)", key: "sec_kv" },
    ],
    CTTB: [
      {
        label: "CTTB Mode",
        key: "mode",
        type: "select",
        options: [
          { value: "SUM", label: "SUM (Totalization)" },
          { value: "DIFFERENTIAL", label: "DIFFERENTIAL (I1 - I2 - ...)" },
        ],
      },
    ],
    Meter: [],
    AuxiliaryTransformer: [
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      { label: "Ratio Correction", key: "ratio" },
    ],
    Relay: [
      {
        label: "Relay Category",
        key: "category",
        type: "select",
        options: [
          { value: "Numerical", label: "Microprocessor / Numerical" },
          { value: "Electromechanical", label: "Electromechanical (Latching)" },
        ],
      },
      {
        label: "Relay Function",
        key: "function",
        type: "select",
        options: [
          { value: "Differential", label: "87 — Differential" },
          { value: "Overcurrent", label: "50/51 — Overcurrent" },
          { value: "Distance", label: "21 — Distance" },
          { value: "Lockout", label: "86 — Lockout" },
        ],
      },
    ],
    CurrentTransformer: [
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Position", key: "position", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Secondary Wiring",
        key: "secondary_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (Standard)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
          { value: "RESIDUAL", label: "3I₀ — Residual" },
          { value: "A", label: "Phase A Only" },
          { value: "B", label: "Phase B Only" },
          { value: "C", label: "Phase C Only" },
          { value: "N", label: "Neutral / Ground" },
        ],
      },
      { label: "Phase A Ratio Override", key: "ratio_a" },
      { label: "Phase B Ratio Override", key: "ratio_b" },
      { label: "Phase C Ratio Override", key: "ratio_c" },
    ],
    VoltageTransformer: [
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Primary Winding",
        key: "primary_winding",
        type: "select",
        options: [
          { value: "Y",  label: "Y — Wye (measures L-N)" },
          { value: "YG", label: "YG — Wye Grounded (measures L-N)" },
          { value: "D",  label: "Δ — Delta (measures L-L)" },
        ],
      },
      {
        label: "Secondary Wiring",
        key: "secondary_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (LN)" },
          { value: "D", label: "Δ — Delta (LL)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
        ],
      },
    ],
    DualWindingVT: [
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Primary Winding",
        key: "primary_winding",
        type: "select",
        options: [
          { value: "Y",  label: "Y — Wye (measures L-N)" },
          { value: "YG", label: "YG — Wye Grounded (measures L-N)" },
          { value: "D",  label: "Δ — Delta (measures L-L)" },
        ],
      },
      { label: "W2 Ratio (e.g. 2000:1)", key: "sec2_ratio", type: "text" },
      {
        label: "W1 Secondary Wiring",
        key: "secondary_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (LN)" },
          { value: "D", label: "Δ — Delta (LL)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
        ],
      },
      {
        label: "W2 Secondary Wiring",
        key: "secondary2_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (LN)" },
          { value: "D", label: "Δ — Delta (LL)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
        ],
      },
    ],
    ShuntCapacitor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Rated Voltage (kV)", key: "kv_rating" },
    ],
    ShuntReactor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Rated Voltage (kV)", key: "kv_rating" },
    ],
    SurgeArrester: [
      { label: "Rated kV (MCOV)", key: "kv_rating" },
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
    ],
    SeriesCapacitor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Reactance Xc (Ω)", key: "impedance_ohm" },
    ],
    SeriesReactor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Reactance XL (Ω)", key: "impedance_ohm" },
    ],
    NeutralGroundingResistor: [
      { label: "Resistance (Ω)", key: "resistance_ohm" },
      { label: "Rated kV", key: "kv_rating" },
    ],
    SVC: [
      { label: "MVAr Min", key: "mvar_min" },
      { label: "MVAr Max", key: "mvar_max" },
      { label: "MVAr Setting (+cap / −ind)", key: "mvar_setting" },
      { label: "Rated kV", key: "kv_rating" },
    ],
    PowerLine: [
      { label: 'Length (km)', key: 'length_km' },
      { label: 'R (Ω/km)', key: 'r_per_km' },
      { label: 'X (Ω/km)', key: 'x_per_km' },
    ],
    Line: [
      { label: 'Length (km)', key: 'length_km' },
      { label: 'R (Ω/km)', key: 'r_per_km' },
      { label: 'X (Ω/km)', key: 'x_per_km' },
    ],

    LineTrap: [
      { label: "Carrier Frequency (Hz)", key: "carrier_frequency_hz" },
    ],
  };
  // Always append serial_number as a universal editable field
  const typeFields = fieldDefs[node.type] || [];
  const serialField = { label: "Serial Number", key: "serial_number", type: "text" };
  const fields = [...typeFields, serialField];
  const params = {...(node.params || {})};
  if (node.type === "CurrentTransformer" && params.phase_ratios) {
    params.ratio_a = params.phase_ratios.a;
    params.ratio_b = params.phase_ratios.b;
    params.ratio_c = params.phase_ratios.c;
  }
  _resetConfigModalPos();
  d3.select("#config-modal").style("display", "flex");
  d3.select("#modal-title").text("CONFIGURE [" + id + "]");
  const body = d3.select("#modal-body").html("");
  fields.forEach((f) => {
    body
      .append("label")
      .text(f.label)
      .style("font-size", "9px")
      .style("color", "#888")
      .style("margin-top", "6px");

    if (f.type === "select") {
      const sel = body
        .append("select")
        .attr("id", "conf-" + f.key)
        .style("width", "100%")
        .style("background", "#222")
        .style("color", "#eee")
        .style("border", "1px solid #444")
        .style("padding", "4px")
        .style("margin-bottom", "4px");
      (f.options || []).forEach((opt) => {
        sel
          .append("option")
          .attr("value", opt.value)
          .text(opt.label)
          .property("selected", (params[f.key] ?? "") === opt.value);
      });
    } else if (f.type === "checkbox") {
      body
        .append("input")
        .attr("id", "conf-" + f.key)
        .attr("type", "checkbox")
        .property("checked", params[f.key] !== false); // default to true if undefined
      body.append("span").text(" (Active)").style("font-size", "9px").style("color", "#555");
    } else {
      body
        .append("input")
        .attr("id", "conf-" + f.key)
        .attr("type", f.type || "number")
        .property("value", params[f.key] ?? "");
    }
  });

  // CT/VT/DualWindingVT: tap ratio selector + add/remove tap management
  if (["CurrentTransformer", "VoltageTransformer", "DualWindingVT", "VoltageRegulator"].includes(node.type)) {
    _appendTapSelector(body, params, node.type);
  }

  // PowerTransformer: tap selector + winding type selectors
  if (node.type === "PowerTransformer") {
    _appendPTTapSelector(body, params);
    _appendWindingSelects(body, params);
  }

  d3.select("#modal-save").on("click", () => {
    const props = {};
    fields.forEach((f) => {
      const el = d3.select("#conf-" + f.key);
      if (f.type === "checkbox") {
        props[f.key] = el.property("checked");
      } else {
        const v = el.property("value");
        if (v !== "") {
          if (f.type === "text" || f.type === "select") {
            props[f.key] = v;
          } else {
            props[f.key] = parseFloat(v);
          }
        }
      }
    });
    if (["CurrentTransformer", "VoltageTransformer", "DualWindingVT", "VoltageRegulator"].includes(node.type)) {
      const selTap = document.getElementById("conf-selected_tap");
      if (selTap) props.selected_tap = selTap.value;
      // collect tap_ratios from the editable list; parse "N:M" strings into floats
      const tapRows = document.querySelectorAll(".tap-ratio-row");
      if (tapRows.length > 0) {
        const tapRatios = {};
        tapRows.forEach(row => {
          const lbl = row.querySelector(".tap-lbl")?.value?.trim();
          if (!lbl) return;
          const parts = lbl.split(":");
          if (parts.length === 2) {
            const ratio = parseFloat(parts[0]) / parseFloat(parts[1]);
            if (!isNaN(ratio) && ratio > 0) tapRatios[lbl] = ratio;
          }
        });
        if (Object.keys(tapRatios).length > 0) props.tap_ratios = tapRatios;
      }
    }
    if (node.type === "CurrentTransformer") {
      const pr = {};
      if (props.ratio_a) pr.a = props.ratio_a;
      if (props.ratio_b) pr.b = props.ratio_b;
      if (props.ratio_c) pr.c = props.ratio_c;
      if (Object.keys(pr).length > 0) props.phase_ratios = pr;
    }
    if (node.type === "PowerTransformer") {
      props.h_winding = document.getElementById("conf-h_winding").value;
      props.x_winding = document.getElementById("conf-x_winding").value;
      props.polarity_reversed = document.getElementById(
        "conf-polarity_reversed",
      ).checked;
      const selIdx = document.getElementById("conf-selected_tap_index");
      if (selIdx) props.selected_tap_index = parseInt(selIdx.value, 10);
    }
    reconfigureAPI(id, "update_device", { properties: props }).then(() => {
      d3.select("#config-modal").style("display", "none");
      refreshData();
    });
  });
}

function _appendTapSelector(body, params, deviceType) {
  const tapRatios = params.tap_ratios || {};
  const tapKeys = Object.keys(tapRatios);
  const selectedTap = params.selected_tap || tapKeys[0] || "";

  body.append("div")
    .style("font-size", "9px").style("color", "#0af")
    .style("margin-top", "12px").style("border-top", "1px solid #1a1a1a")
    .style("padding-top", "8px").style("letter-spacing", "1px")
    .text("TAP RATIOS");

  // Active tap selector
  body.append("label").text("ACTIVE TAP")
    .style("font-size", "9px").style("color", "#888").style("margin-top", "6px");
  const sel = body.append("select").attr("id", "conf-selected_tap")
    .style("width", "100%").style("background", "#222").style("color", "#eee")
    .style("border", "1px solid #444").style("padding", "4px").style("margin-bottom", "6px");
  tapKeys.forEach(k => {
    sel.append("option").attr("value", k).text(k)
      .property("selected", k === selectedTap);
  });
  if (tapKeys.length === 0) {
    sel.append("option").attr("value", selectedTap).text(selectedTap || "(none)")
      .property("selected", true);
  }

  // Editable tap list
  body.append("label").text("ALL TAPS (one per line, label:ratio format)")
    .style("font-size", "9px").style("color", "#888").style("margin-top", "4px");

  const listDiv = body.append("div").attr("id", "tap-list-container")
    .style("display", "flex").style("flex-direction", "column").style("gap", "3px")
    .style("margin-bottom", "4px");

  const renderTapList = (taps) => {
    listDiv.html("");
    taps.forEach((k, i) => {
      const row = listDiv.append("div").attr("class", "tap-ratio-row")
        .style("display", "flex").style("gap", "4px").style("align-items", "center");
      row.append("input").attr("class", "tap-lbl").attr("type", "text")
        .property("value", k)
        .style("flex", "1").style("background", "#111").style("border", "1px solid #333")
        .style("color", "#eee").style("padding", "3px 6px").style("font-size", "10px")
        .on("input", function() {
          // update the active-tap selector live
          const selEl = document.getElementById("conf-selected_tap");
          if (selEl && selEl.options[i]) selEl.options[i].value = this.value;
          if (selEl && selEl.options[i]) selEl.options[i].textContent = this.value;
        });
      row.append("button").text("✕")
        .style("background", "none").style("border", "1px solid #522")
        .style("color", "#f44").style("cursor", "pointer").style("font-size", "10px")
        .style("padding", "2px 6px")
        .on("click", () => {
          const remaining = Array.from(document.querySelectorAll(".tap-ratio-row .tap-lbl"))
            .map(el => el.value).filter((_, j) => j !== i);
          renderTapList(remaining);
        });
    });
  };
  renderTapList(tapKeys.length > 0 ? tapKeys : (selectedTap ? [selectedTap] : []));

  body.append("button").text("+ ADD TAP")
    .style("background", "#0a0a0a").style("border", "1px solid #333").style("color", "#888")
    .style("font-size", "9px").style("padding", "4px 10px").style("cursor", "pointer")
    .style("margin-bottom", "6px")
    .on("click", () => {
      const existing = Array.from(document.querySelectorAll(".tap-ratio-row .tap-lbl"))
        .map(el => el.value);
      renderTapList([...existing, deviceType === "CurrentTransformer" ? "2000:5" : "2000:1"]);
    });
}

function _appendPTTapSelector(body, params) {
  const tapConfigs = params.tap_configs || [{ label: "Nominal", pri_kv: params.pri_kv || 230, sec_kv: params.sec_kv || 115 }];
  const selectedIdx = params.selected_tap_index ?? 0;

  body.append("div")
    .style("font-size", "9px").style("color", "#0af")
    .style("margin-top", "12px").style("border-top", "1px solid #1a1a1a")
    .style("padding-top", "8px").style("letter-spacing", "1px")
    .text("TAP POSITIONS");

  body.append("label").text("ACTIVE TAP POSITION")
    .style("font-size", "9px").style("color", "#888").style("margin-top", "6px");
  const sel = body.append("select").attr("id", "conf-selected_tap_index")
    .style("width", "100%").style("background", "#222").style("color", "#eee")
    .style("border", "1px solid #444").style("padding", "4px").style("margin-bottom", "6px");
  tapConfigs.forEach((tap, i) => {
    const label = tap.label || `Tap ${i + 1}`;
    const detail = ` (${tap.pri_kv}kV / ${tap.sec_kv}kV)`;
    sel.append("option").attr("value", i).text(label + detail)
      .property("selected", i === selectedIdx);
  });
}

const _WINDING_OPTIONS = [
  { value: "Y", label: "Y — Wye" },
  { value: "YG", label: "YG — Wye Grounded" },
  { value: "D", label: "D — Delta" },
  { value: "Z", label: "Z — Zigzag" },
  { value: "ZG", label: "ZG — Zigzag Grounded" },
];

function _appendWindingSelects(body, params) {
  [
    { label: "HV Winding (H)", key: "h_winding" },
    { label: "LV Winding (X)", key: "x_winding" },
  ].forEach(({ label, key }) => {
    body
      .append("label")
      .text(label)
      .style("font-size", "9px")
      .style("color", "#888")
      .style("margin-top", "8px");
    const sel = body.append("select").attr("id", "conf-" + key);
    _WINDING_OPTIONS.forEach((o) => {
      sel
        .append("option")
        .attr("value", o.value)
        .property(
          "selected",
          (params[key] || (key === "h_winding" ? "Y" : "D")) === o.value,
        )
        .text(o.label);
    });
    sel.on("change", () => _updateAutoShiftHint());
  });

  // Polarity row (only meaningful for cross-family combos, but always shown)
  const polarityRow = body
    .append("div")
    .style("display", "flex")
    .style("align-items", "center")
    .style("gap", "8px")
    .style("margin-top", "10px");
  polarityRow
    .append("input")
    .attr("id", "conf-polarity_reversed")
    .attr("type", "checkbox")
    .property("checked", params.polarity_reversed === true)
    .on("change", () => _updateAutoShiftHint());
  polarityRow
    .append("label")
    .attr("for", "conf-polarity_reversed")
    .text("Reversed polarity (+30° instead of −30°)")
    .style("font-size", "9px")
    .style("color", "#ccc")
    .style("cursor", "pointer");

  body
    .append("div")
    .attr("id", "winding-shift-hint")
    .style("font-size", "9px")
    .style("color", "#3af")
    .style("margin-top", "4px")
    .text(
      _shiftHintText(
        params.h_winding || "Y",
        params.x_winding || "D",
        params.polarity_reversed === true,
      ),
    );
}

function _isCrossFamily(h, x) {
  const yFamily = new Set(["Y", "YG"]);
  return yFamily.has(h.toUpperCase()) !== yFamily.has(x.toUpperCase());
}

function _shiftHintText(h, x, reversed) {
  const names = {
    Y: "Wye",
    YG: "Wye-Grounded",
    D: "Delta",
    Z: "Zigzag",
    ZG: "Zigzag-Grounded",
  };
  const cross = _isCrossFamily(h, x);
  const shift = cross ? (reversed ? +30 : -30) : 0;
  const polNote = cross
    ? reversed
      ? " · Reversed polarity"
      : " · Normal polarity (ANSI)"
    : " · Same family — polarity has no effect";
  return `${names[h] || h} / ${names[x] || x} → ${shift > 0 ? "+" : ""}${shift}°${polNote}`;
}

function _updateAutoShiftHint() {
  const h = document.getElementById("conf-h_winding")?.value || "Y";
  const x = document.getElementById("conf-x_winding")?.value || "D";
  const reversed =
    document.getElementById("conf-polarity_reversed")?.checked || false;
  const hint = document.getElementById("winding-shift-hint");
  if (hint) hint.textContent = _shiftHintText(h, x, reversed);
}

function showLoadConfigModal(id) {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === id);
  if (!node) return;
  _resetConfigModalPos();
  d3.select("#config-modal").style("display", "flex");
  d3.select("#modal-title").text("LOAD CONFIGURATION [" + id + "]");
  const body = d3.select("#modal-body").html("");
  const params = node.params,
    totalMva = params.load_mva || 0,
    totalPf = params.pf || 1.0;
  const phaseVa = params.phase_va || {
    a: (totalMva * 1e6) / 3,
    b: (totalMva * 1e6) / 3,
    c: (totalMva * 1e6) / 3,
  };
  const phasePf = params.phase_pf || { a: totalPf, b: totalPf, c: totalPf };
  const nonZero = ["a", "b", "c"].filter((p) => (phaseVa[p] || 0) > 1);
  const isSingle = params.is_balanced === false && nonZero.length <= 1;
  const mode = isSingle ? "single" : "3phase";
  const activePh = isSingle ? nonZero[0] || "a" : "a";

  let html =
    '<div style="margin-bottom:8px;"><label style="font-size:10px;color:#fff;">MODE:</label>' +
    '<select id="load-mode-select" style="width:100%;margin-top:4px;">' +
    '<option value="3phase"' +
    (mode === "3phase" ? " selected" : "") +
    ">3-Phase</option>" +
    '<option value="single"' +
    (mode === "single" ? " selected" : "") +
    ">Single Phase</option>" +
    "</select></div>";

  // 3-phase: total at top, per-phase breakdown constrained to sum to total
  const initPhVa = (p) =>
    params.is_balanced === false ? (phaseVa[p] || 0) / 1e6 : totalMva / 3;
  const initPhPf = (p) =>
    params.is_balanced === false ? phasePf[p] || 1.0 : totalPf;
  html +=
    '<div id="load-3phase-section" style="display:' +
    (mode === "3phase" ? "block" : "none") +
    ';">';
  html += '<div class="section-title">3-PHASE TOTAL</div>';
  html +=
    createLoadRow("Total MVA", "total-mva", totalMva) +
    createLoadRow("Power Factor", "total-pf", totalPf);
  html += '<div class="section-title">PHASE BREAKDOWN</div>';
  ["a", "b", "c"].forEach((p) => {
    html += createLoadRow(
      "Phase " + p.toUpperCase() + " MVA",
      "ph-" + p + "-mva",
      initPhVa(p),
    );
    html += createLoadRow(
      "Phase " + p.toUpperCase() + " PF",
      "ph-" + p + "-pf",
      initPhPf(p),
    );
  });
  html += "</div>";

  // Single phase: choose which phase carries all the load
  html +=
    '<div id="load-single-section" style="display:' +
    (mode === "single" ? "block" : "none") +
    ';">';
  html += '<div class="section-title">SINGLE PHASE</div>';
  html +=
    '<div style="margin-bottom:6px;"><label style="font-size:9px;color:#888;display:block;">Active Phase</label>' +
    '<select id="single-ph-select" style="width:100%;">' +
    ["a", "b", "c"]
      .map(
        (p) =>
          '<option value="' +
          p +
          '"' +
          (p === activePh ? " selected" : "") +
          ">Phase " +
          p.toUpperCase() +
          "</option>",
      )
      .join("") +
    "</select></div>";
  html += createLoadRow(
    "Phase MVA",
    "single-mva",
    (phaseVa[activePh] || 0) / 1e6,
  );
  html += createLoadRow("Power Factor", "single-pf", phasePf[activePh] || 1.0);
  html += "</div>";
  body.html(html);

  d3.select("#load-mode-select").on("change", function () {
    d3.select("#load-3phase-section").style(
      "display",
      this.value === "3phase" ? "block" : "none",
    );
    d3.select("#load-single-section").style(
      "display",
      this.value === "single" ? "block" : "none",
    );
  });

  // Total changed: redistribute phases preserving their ratios; also push PF to all phases
  function onTotalChange() {
    const t = parseFloat(d3.select("#total-mva").property("value")) || 0;
    const pf = parseFloat(d3.select("#total-pf").property("value")) || 1.0;
    const a = parseFloat(d3.select("#ph-a-mva").property("value")) || 0,
      b = parseFloat(d3.select("#ph-b-mva").property("value")) || 0,
      c = parseFloat(d3.select("#ph-c-mva").property("value")) || 0;
    const s = a + b + c;
    if (s > 0) {
      d3.select("#ph-a-mva").property("value", ((t * a) / s).toFixed(3));
      d3.select("#ph-b-mva").property("value", ((t * b) / s).toFixed(3));
      d3.select("#ph-c-mva").property("value", ((t * c) / s).toFixed(3));
    } else {
      ["a", "b", "c"].forEach((p) =>
        d3.select("#ph-" + p + "-mva").property("value", (t / 3).toFixed(3)),
      );
    }
    ["a", "b", "c"].forEach((p) =>
      d3.select("#ph-" + p + "-pf").property("value", pf.toFixed(3)),
    );
  }

  // Phase MVA changed: adjust the other two (preserving their ratio) to keep sum = total
  function onPhaseChange(ch) {
    const total = parseFloat(d3.select("#total-mva").property("value")) || 0;
    let v = parseFloat(d3.select("#ph-" + ch + "-mva").property("value")) || 0;
    if (v > total) {
      v = total;
      d3.select("#ph-" + ch + "-mva").property("value", total.toFixed(3));
    }
    const rem = total - v,
      oth = ["a", "b", "c"].filter((p) => p !== ch);
    const o0 =
      parseFloat(d3.select("#ph-" + oth[0] + "-mva").property("value")) || 0;
    const o1 =
      parseFloat(d3.select("#ph-" + oth[1] + "-mva").property("value")) || 0;
    const os = o0 + o1;
    d3.select("#ph-" + oth[0] + "-mva").property(
      "value",
      (os > 0 ? (rem * o0) / os : rem / 2).toFixed(3),
    );
    d3.select("#ph-" + oth[1] + "-mva").property(
      "value",
      (os > 0 ? (rem * o1) / os : rem / 2).toFixed(3),
    );
  }

  d3.select("#total-mva").on("input", onTotalChange);
  d3.select("#total-pf").on("input", onTotalChange);
  ["a", "b", "c"].forEach((p) =>
    d3.select("#ph-" + p + "-mva").on("input", () => onPhaseChange(p)),
  );

  d3.select("#modal-save").on("click", () => {
    const m = d3.select("#load-mode-select").property("value");
    let props;
    if (m === "3phase") {
      const pva = {},
        ppf = {};
      ["a", "b", "c"].forEach((p) => {
        pva[p] =
          (parseFloat(d3.select("#ph-" + p + "-mva").property("value")) || 0) *
          1e6;
        ppf[p] =
          parseFloat(d3.select("#ph-" + p + "-pf").property("value")) || 1.0;
      });
      props = {
        is_balanced: false,
        load_mva: parseFloat(d3.select("#total-mva").property("value")) || 0,
        pf: parseFloat(d3.select("#total-pf").property("value")) || 1.0,
        phase_va: pva,
        phase_pf: ppf,
      };
    } else {
      const ph = d3.select("#single-ph-select").property("value"),
        mva =
          (parseFloat(d3.select("#single-mva").property("value")) || 0) * 1e6,
        pf = parseFloat(d3.select("#single-pf").property("value")) || 1.0;
      const pva = { a: 0, b: 0, c: 0 },
        ppf = { a: 1.0, b: 1.0, c: 1.0 };
      pva[ph] = mva;
      ppf[ph] = pf;
      props = {
        is_balanced: false,
        load_mva: mva / 1e6,
        pf,
        phase_va: pva,
        phase_pf: ppf,
      };
    }
    reconfigureAPI(id, "update_device", { properties: props }).then(() => {
      d3.select("#config-modal").style("display", "none");
      refreshData();
    });
  });
}

function createLoadRow(label, id, value) {
  return (
    '<div style="margin-bottom:6px;"><label style="font-size:9px; color:#888; display:block;">' +
    label +
    '</label><input id="' +
    id +
    '" type="number" step="0.001" style="width:100%; box-sizing:border-box;" value="' +
    value.toFixed(3) +
    '"></div>'
  );
}

