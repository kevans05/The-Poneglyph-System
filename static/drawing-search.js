"use strict";

/**
 * Corporate drawing-search picker.
 *
 *   _openDrawingSearch({ deviceType, deviceId, station }, onPick)
 *
 * Opens an overlay that searches the corporate drawing system via
 * /api/drawing-search. Pre-fills facility (from the loaded site), and drawing
 * type / subject from a per-device-type hint — every field stays editable.
 * `onPick(result)` fires with the chosen { drawing_number, title, revision,
 * document_url, drawing_subject, ... } and the overlay closes.
 *
 * Degrades gracefully: if the search backend isn't configured, shows a short
 * "how to configure" note and nothing else.
 */

let _dwgMeta = null; // { config, options } cached for the session

function _dwgLoadMeta() {
  if (_dwgMeta) return Promise.resolve(_dwgMeta);
  return Promise.all([
    fetch("/api/drawing-search/config").then((r) => r.json()),
    fetch("/api/drawing-search/options").then((r) => r.json()),
  ]).then(([config, options]) => {
    _dwgMeta = { config: config || {}, options: options || {} };
    return _dwgMeta;
  });
}

function _openDrawingSearch(ctx, onPick) {
  ctx = ctx || {};
  const prev = document.getElementById("_dwg-overlay");
  if (prev) prev.remove();

  const overlay = document.createElement("div");
  overlay.id = "_dwg-overlay";
  overlay.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:12000;" +
    "display:flex;align-items:center;justify-content:center;" +
    "font-family:'Consolas','Courier New',monospace;";
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);

  const box = document.createElement("div");
  box.style.cssText =
    "background:#0b0b10;border:1px solid #2a3a4a;width:min(92vw,820px);max-height:88vh;" +
    "display:flex;flex-direction:column;box-shadow:0 24px 70px rgba(0,0,0,0.95);";
  overlay.appendChild(box);

  box.innerHTML =
    '<div style="display:flex;justify-content:space-between;align-items:center;' +
    'padding:12px 16px;background:#101820;border-bottom:1px solid #1e2e3a;">' +
    '<span style="color:#7fd0ff;font-size:11px;letter-spacing:1px;">🔍 SEARCH CORPORATE DRAWINGS' +
    (ctx.deviceId ? ' — <span style="color:#fff;">' + ctx.deviceId + "</span>" : "") +
    "</span>" +
    '<span id="_dwg-close" style="cursor:pointer;color:#556;font-size:16px;padding:0 4px;">✕</span>' +
    "</div>" +
    '<div id="_dwg-body" style="flex:1;overflow-y:auto;padding:14px 16px;color:#cdd;font-size:11px;">Loading…</div>';
  box.querySelector("#_dwg-close").onclick = () => overlay.remove();

  _dwgLoadMeta()
    .then(({ config, options }) => {
      const body = box.querySelector("#_dwg-body");
      if (!config.configured) {
        body.innerHTML =
          '<div style="color:#a86;line-height:1.6;">' +
          "Drawing search is not configured on this server.<br><br>" +
          '<span style="color:#889;">Set it up with either:</span><br>' +
          "• a JSON file at <code style=\"color:#7fd0ff;\">~/.poneglyph_drawing_search.json</code> " +
          '(<code style="color:#889;">{ "base_url": "...", "cookies": { "filenet-es": "..." } }</code>)<br>' +
          "• or env vars <code style=\"color:#7fd0ff;\">PONEGLYPH_DWG_BASE_URL</code> / " +
          "<code style=\"color:#7fd0ff;\">PONEGLYPH_DWG_COOKIES</code><br><br>" +
          '<span style="color:#889;">Until then, add drawings manually.</span></div>';
        return;
      }
      _dwgRenderForm(body, config, options, ctx, onPick, overlay);
    })
    .catch(() => {
      box.querySelector("#_dwg-body").innerHTML =
        '<div style="color:#c66;">Could not reach the drawing-search backend.</div>';
    });
}

function _dwgRenderForm(body, config, options, ctx, onPick, overlay) {
  const hint = (config.type_hints || {})[ctx.deviceType] || {};
  const facDefault = config.facility_default || ctx.station || "";
  const opt = (map, sel, blank) => {
    let h = '<option value="">' + (blank || "— any —") + "</option>";
    Object.entries(map || {}).forEach(([code, label]) => {
      const s = code === sel ? " selected" : "";
      h += `<option value="${_dwgEsc(code)}"${s}>${_dwgEsc(code)} — ${_dwgEsc(label)}</option>`;
    });
    return h;
  };
  const facList = Object.entries(options.facilities || {})
    .map(([c, l]) => `<option value="${_dwgEsc(c)}">${_dwgEsc(l)}</option>`)
    .join("");

  body.innerHTML =
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 10px;">' +
    _dwgField("FACILITY", `<input id="_dwg-facility" list="_dwg-fac-list" value="${_dwgEsc(facDefault)}" ` +
      'style="' + _DWG_INP + '" /><datalist id="_dwg-fac-list">' + facList + "</datalist>") +
    _dwgField("DRAWING TYPE", `<select id="_dwg-type" style="${_DWG_INP}">` +
      opt(options.drawing_types, hint.drawing_type) + "</select>") +
    _dwgField("SUBJECT", `<select id="_dwg-subject" style="${_DWG_INP}">` +
      opt(options.drawing_subjects, hint.drawing_subject) + "</select>") +
    _dwgField("STATE", `<select id="_dwg-state" style="${_DWG_INP}">` +
      '<option>Released</option><option>Draft</option><option value="">— any —</option></select>') +
    _dwgField("TITLE CONTAINS", `<input id="_dwg-title" placeholder="free text" style="${_DWG_INP}" />`) +
    _dwgField("DRAWING # STARTS WITH", `<input id="_dwg-num" style="${_DWG_INP}" />`) +
    _dwgField("SHEET #", `<input id="_dwg-sheet" style="${_DWG_INP}" />`) +
    _dwgField("&nbsp;",
      '<button id="_dwg-go" style="' + _DWG_BTN + 'width:100%;">SEARCH ▸</button>') +
    "</div>" +
    '<div id="_dwg-status" style="font-size:9px;color:#667;margin:8px 0 4px;min-height:12px;"></div>' +
    '<div id="_dwg-results"></div>';

  if (ctx.deviceId) {
    const t = body.querySelector("#_dwg-title");
    const chip = document.createElement("span");
    chip.textContent = "use “" + ctx.deviceId + "”";
    chip.style.cssText =
      "display:inline-block;margin-top:3px;font-size:8px;color:#7fd0ff;border:1px solid #244;" +
      "border-radius:2px;padding:1px 5px;cursor:pointer;";
    chip.onclick = () => { t.value = ctx.deviceId; };
    t.parentElement.appendChild(chip);
  }

  let page = 0;
  const run = (append) => {
    const status = body.querySelector("#_dwg-status");
    const results = body.querySelector("#_dwg-results");
    const payload = {
      facility: body.querySelector("#_dwg-facility").value.trim(),
      drawing_type: body.querySelector("#_dwg-type").value,
      drawing_subject: body.querySelector("#_dwg-subject").value,
      state: body.querySelector("#_dwg-state").value,
      title: body.querySelector("#_dwg-title").value.trim(),
      drawing_num: body.querySelector("#_dwg-num").value.trim(),
      sheet_number: body.querySelector("#_dwg-sheet").value.trim(),
      page: append ? page : 0,
    };
    if (!append) { page = 0; results.innerHTML = ""; }
    status.textContent = "searching…";
    fetch("/api/drawing-search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((res) => {
        if (res.error) { status.textContent = "✗ " + res.error; return; }
        const rows = res.results || [];
        status.textContent =
          (res.total_count ? res.total_count + " match(es)" : rows.length + " result(s)") +
          (rows.length === 0 ? " — nothing found" : "");
        rows.forEach((d) => results.appendChild(_dwgResultRow(d, onPick, overlay)));
        const old = body.querySelector("#_dwg-more");
        if (old) old.remove();
        if (res.has_next) {
          const more = document.createElement("button");
          more.id = "_dwg-more";
          more.textContent = "LOAD MORE";
          more.style.cssText = _DWG_BTN + "width:100%;margin-top:8px;";
          more.onclick = () => { page += 1; run(true); };
          results.appendChild(more);
        }
      })
      .catch(() => { status.textContent = "✗ search failed"; });
  };
  body.querySelector("#_dwg-go").onclick = () => run(false);
  body.querySelectorAll("input").forEach((el) =>
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") run(false); }),
  );
}

function _dwgResultRow(d, onPick, overlay) {
  const row = document.createElement("div");
  row.style.cssText =
    "display:flex;align-items:center;gap:10px;padding:6px 8px;border-bottom:1px solid #14202a;cursor:pointer;";
  row.onmouseenter = () => (row.style.background = "#111a22");
  row.onmouseleave = () => (row.style.background = "transparent");
  row.innerHTML =
    '<div style="flex:1;min-width:0;">' +
    `<div style="color:#fff;font-size:11px;">${_dwgEsc(d.drawing_number)}` +
    (d.revision ? ` <span style="color:#7fd0ff;">${_dwgEsc(d.revision)}</span>` : "") +
    (d.signed_out ? ' <span style="color:#f80;">◆ signed out</span>' : "") +
    "</div>" +
    `<div style="color:#9ab;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_dwgEsc(d.title || "—")}</div>` +
    `<div style="color:#556;font-size:8px;">${_dwgEsc(d.facility)} · ${_dwgEsc(d.drawing_type)}/${_dwgEsc(d.drawing_subject)} · ${_dwgEsc(d.state)}</div>` +
    "</div>" +
    '<button style="' + _DWG_BTN + 'flex-shrink:0;">USE →</button>';
  const pick = () => { overlay.remove(); onPick(d); };
  row.querySelector("button").onclick = (e) => { e.stopPropagation(); pick(); };
  row.onclick = pick;
  return row;
}

const _DWG_INP =
  "width:100%;box-sizing:border-box;background:#111;border:1px solid #2a3a44;color:#dbe;" +
  "font-family:inherit;font-size:10px;padding:4px 6px;";
const _DWG_BTN =
  "background:#04121c;border:1px solid #3af;color:#7fd0ff;font-family:inherit;font-size:10px;" +
  "letter-spacing:1px;padding:5px 12px;cursor:pointer;";

function _dwgField(label, control) {
  return (
    '<label style="display:flex;flex-direction:column;gap:2px;font-size:8px;color:#778;letter-spacing:0.5px;">' +
    label +
    control +
    "</label>"
  );
}

function _dwgEsc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
