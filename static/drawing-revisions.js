"use strict";

/**
 * drawing-revisions.js — the sibling-revision list bound to an attached drawing.
 *
 * When a drawing carries a drawing_number, the corporate search can enumerate
 * every revision that number has ever had.  This renders that set inline under a
 * drawing row:
 *   • device drawings (a drawing_id is passed) → clicking a sibling swaps the
 *     attachment to it, logging the old revision to drawing_revision_log.
 *   • test drawings (no drawing_id) → read-only context; the pinned revision
 *     stays as the field record.
 *
 *   renderDrawingRevisions(containerEl, {
 *       drawingNumber, currentRevision,
 *       drawingId,          // optional — enables swap
 *       onSwapped(rev),     // optional callback after a successful swap
 *   })
 */

function _drEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

function renderDrawingRevisions(container, opts) {
  if (!container) return;
  const number = (opts && opts.drawingNumber) || "";
  if (!number) {
    container.innerHTML =
      '<span style="color:#444;font-size:9px;">no drawing number — attach from corporate search to track revisions</span>';
    return;
  }
  container.innerHTML =
    '<span style="color:#556;font-size:9px;">loading revisions…</span>';
  fetchDrawingRevisions(number).then((res) => _render(res));

  function _refreshLink() {
    return (
      ' <a href="#" data-dr-refresh="1" title="re-query the corporate system"' +
      ' style="color:#4aa8d8;font-size:9px;text-decoration:none;">↻</a>'
    );
  }

  function _render(res) {
    const revs = (res && res.revisions) || [];
    if (!revs.length) {
      const why = res && res.error
        ? "revision lookup failed: " + _drEsc(res.error)
        : res && res.configured === false
          ? "drawing search not configured"
          : "no other revisions on record";
      container.innerHTML =
        '<span style="color:#556;font-size:9px;">' + why + "</span>" + _refreshLink();
      _wire();
      return;
    }

    const cur = (opts.currentRevision || "").trim();
    let html =
      '<div style="font-size:9px;color:#556;letter-spacing:1px;margin-bottom:3px;">' +
      revs.length + " REVISION" + (revs.length !== 1 ? "S" : "") + " ON RECORD" +
      _refreshLink() + "</div>" +
      '<div style="display:flex;flex-wrap:wrap;gap:4px;">';

    revs.forEach((r) => {
      const rv = (r.revision || "").trim();
      const isCur = rv === cur;
      const canSwap = !!opts.drawingId && !isCur;
      const stateTag =
        r.state && r.state.toLowerCase() !== "released"
          ? " · " + _drEsc(r.state)
          : "";
      html +=
        '<span data-dr-rev="' + _drEsc(rv) + '" data-dr-url="' + _drEsc(r.document_url || "") + '"' +
        ' title="' + _drEsc((r.state || "") + "  " + (r.title || "")) + '"' +
        ' style="font-size:9px;padding:2px 7px;border-radius:2px;border:1px solid ' +
        (isCur ? "#3fdc8f" : "#333") + ";color:" +
        (isCur ? "#3fdc8f" : canSwap ? "#7fd0ff" : "#888") + ";" +
        (canSwap ? "cursor:pointer;" : "") + '">' +
        (rv ? _drEsc(rv) : "(no rev)") + stateTag + (isCur ? " ◄" : "") +
        "</span>";
    });
    html += "</div>";
    if (opts.drawingId && revs.length > 1) {
      html +=
        '<div style="color:#444;font-size:8px;margin-top:3px;">click a revision to swap this attachment — the current one is logged</div>';
    }
    container.innerHTML = html;
    _wire();
  }

  function _wire() {
    const rb = container.querySelector("[data-dr-refresh]");
    if (rb)
      rb.onclick = (e) => {
        e.preventDefault();
        container.innerHTML =
          '<span style="color:#556;font-size:9px;">re-querying…</span>';
        fetchDrawingRevisions(number, true).then((res) => _render(res));
      };

    if (!opts.drawingId) return;
    container.querySelectorAll("span[data-dr-rev]").forEach((s) => {
      const rev = s.getAttribute("data-dr-rev");
      if (rev === (opts.currentRevision || "").trim()) return;
      s.onclick = () => {
        if (!confirm(
          "Swap this drawing to revision " + (rev || "(no rev)") +
          "?\nThe current revision is written to the change log.")) return;
        updateDeviceDrawing(
          opts.drawingId, rev, s.getAttribute("data-dr-url") || null,
          window._technicianName || "",
        ).then((r) => {
          if (r && r.error) { alert("Swap failed: " + r.error); return; }
          if (typeof opts.onSwapped === "function") opts.onSwapped(rev);
        });
      };
    });
  }
}

window.renderDrawingRevisions = renderDrawingRevisions;
