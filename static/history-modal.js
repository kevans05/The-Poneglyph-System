function showHistoryModal() {
  d3.select("#history-modal").style("display", "flex");
  _renderHistoryTab("snapshots");
}

function _fmtEpoch(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleString();
}

function _fmtEpochShort(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
    + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function _dayBucket(epoch) {
  const d = new Date(epoch * 1000);
  const now = new Date();
  const diffMs = now - d;
  const diffDays = diffMs / 86400000;
  if (diffDays < 1) return "TODAY";
  if (diffDays < 2) return "YESTERDAY";
  if (diffDays < 7) return "THIS WEEK";
  return "OLDER";
}

let _historyTab = "snapshots";

function _renderHistoryTab(tab) {
  _historyTab = tab;

  // Tab bar in body header
  const body = d3.select("#history-body").html("");

  const tabBar = body.append("div")
    .style("display", "flex").style("gap", "0").style("border-bottom", "1px solid #1a1a1a")
    .style("margin-bottom", "0").style("flex-shrink", "0");

  [["snapshots", "SNAPSHOTS"], ["sessions", "SESSIONS"]].forEach(([key, label]) => {
    const active = key === tab;
    tabBar.append("button")
      .text(label)
      .style("background", active ? "#001a00" : "#050505")
      .style("border", "none").style("border-bottom", active ? "2px solid #0f0" : "2px solid transparent")
      .style("color", active ? "#0f0" : "#555")
      .style("font-family", "inherit").style("font-size", "10px")
      .style("padding", "8px 18px").style("cursor", "pointer")
      .style("letter-spacing", "1px")
      .on("click", () => _renderHistoryTab(key));
  });

  const contentArea = body.append("div").style("overflow-y", "auto").style("flex", "1");

  if (tab === "snapshots") {
    _renderSnapshotsTab(contentArea);
  } else {
    _renderSessionsTab(contentArea);
  }

  // Footer
  const footer = d3.select("#history-footer").html("");
  if (tab === "snapshots") {
    footer.append("button").attr("class", "wiz-save").text("+ TAKE SNAPSHOT")
      .on("click", () => {
        const now = new Date();
        const dateStr = now.getFullYear() + String(now.getMonth() + 1).padStart(2, "0") + String(now.getDate()).padStart(2, "0");
        const station = currentData?.site?.station || "STN";
        showInputDialog("SNAPSHOT LABEL", dateStr + "-" + station, (label) => {
          if (!label) return;
          createSnapshot(label).then(() => _renderHistoryTab("snapshots"));
        });
      });
  }
  footer.append("div").style("flex", "1");
  footer.append("button").attr("class", "wiz-secondary").text("CLOSE")
    .on("click", () => d3.select("#history-modal").style("display", "none"));
}

function _renderSnapshotsTab(container) {
  container.html('<div style="color:#555; padding:12px; font-size:10px;">Loading...</div>');
  fetchSnapshots().then((resp) => {
    container.html("");
    const snaps = (resp.snapshots || []).slice().reverse(); // newest first
    if (snaps.length === 0) {
      container.append("div").text("No snapshots yet.").style("color", "#444").style("padding", "16px").style("font-size", "10px");
      return;
    }

    // Group by day bucket
    const groups = {};
    const order = [];
    snaps.forEach(s => {
      const b = _dayBucket(s.epoch);
      if (!groups[b]) { groups[b] = []; order.push(b); }
      groups[b].push(s);
    });

    order.forEach(bucket => {
      container.append("div")
        .style("font-size", "9px").style("color", "#555").style("letter-spacing", "1px")
        .style("padding", "8px 14px 4px").style("background", "#070707")
        .style("border-bottom", "1px solid #111")
        .text(bucket);

      groups[bucket].forEach(s => {
        const row = container.append("div")
          .style("display", "flex").style("align-items", "center")
          .style("padding", "7px 14px").style("border-bottom", "1px solid #0d0d0d")
          .style("gap", "8px");

        row.append("div")
          .style("font-size", "10px").style("color", "#aaa").style("flex", "1")
          .style("min-width", "0")
          .html(`<span style="color:#eee;">${s.label || "Unnamed"}</span> <span style="color:#444; font-size:9px;">${_fmtEpochShort(s.epoch)}</span>`);

        row.append("button").attr("class", "eng-btn")
          .style("white-space", "nowrap").style("padding", "3px 10px").style("font-size", "9px")
          .text("COMPARE")
          .on("click", () => enterCompareMode(s.id, s.label));

        row.append("button").attr("class", "wiz-secondary")
          .style("white-space", "nowrap").style("padding", "3px 8px").style("font-size", "9px").style("color", "#555")
          .text("DELETE")
          .on("click", () => {
            if (!confirm(`Delete "${s.label}"?`)) return;
            deleteSnapshot(s.id).then(() => _renderHistoryTab("snapshots"));
          });
      });
    });
  });
}

function _renderSessionsTab(container) {
  container.html('<div style="color:#555; padding:12px; font-size:10px;">Loading...</div>');
  fetchSessions().then((resp) => {
    container.html("");
    const sessions = (resp.sessions || []).slice().reverse();
    if (sessions.length === 0) {
      container.append("div").text("No sessions recorded.").style("color", "#444").style("padding", "16px").style("font-size", "10px");
      return;
    }

    sessions.forEach(s => {
      const card = container.append("div")
        .style("border-bottom", "1px solid #0d0d0d");

      const header = card.append("div")
        .style("display", "flex").style("align-items", "center")
        .style("padding", "7px 14px").style("gap", "8px").style("cursor", "pointer");

      const techLabel = s.technician || "—";
      const testLabel = s.test_name || (s.test_id ? `Test #${s.test_id.slice(0, 6)}` : "No test");
      const epochLabel = s.epoch ? _fmtEpochShort(s.epoch) : "";
      const countLabel = s.reading_count != null ? `${s.reading_count} rdg` : "";

      header.append("div").style("flex", "1").style("min-width", "0")
        .html(`<span style="color:#eee; font-size:10px;">${techLabel}</span> <span style="color:#555; font-size:9px;">· ${testLabel} · ${epochLabel}</span>`)
        .append("span").style("color", "#444").style("font-size", "9px").style("margin-left", "6px").text(countLabel);

      header.append("span").style("font-size", "9px").style("color", "#333").text("▼");

      header.append("button").attr("class", "wiz-secondary")
        .style("padding", "2px 8px").style("font-size", "9px").style("color", "#555")
        .text("DELETE")
        .on("click", (e) => {
          e.stopPropagation();
          if (!confirm(`Delete this session?`)) return;
          deleteSession(s.id).then(() => _renderHistoryTab("sessions"));
        });

      // Detail panel (hidden by default)
      const detail = card.append("div").attr("class", "session-detail")
        .style("display", "none")
        .style("background", "#080808")
        .style("padding", "8px 14px 10px 24px");

      detail.append("div").style("font-size", "9px").style("color", "#555").style("margin-bottom", "6px")
        .text(`Instrument: ${s.instrument || "manual"}`);

      const measContainer = detail.append("div");
      measContainer.append("div").style("font-size", "9px").style("color", "#444").text("Loading measurements...");

      // Lazy-load measurements on first expand
      let measLoaded = false;
      header.on("click", function() {
        const det = card.select(".session-detail");
        const isVisible = det.style("display") !== "none";
        det.style("display", isVisible ? "none" : "block");
        if (!isVisible && !measLoaded) {
          measLoaded = true;
          fetchSessionMeasurements(s.id).then(resp => {
            measContainer.html("");
            const byDevice = resp.by_device || {};
            const devices = Object.keys(byDevice);
            if (devices.length === 0) {
              measContainer.append("div").style("color", "#444").style("font-size", "9px").text("No measurements.");
              return;
            }
            devices.forEach(devId => {
              measContainer.append("div")
                .style("font-size", "9px").style("color", "#888").style("margin-top", "5px")
                .text(devId);
              const entries = byDevice[devId] || [];
              entries.slice(0, 6).forEach(m => {
                measContainer.append("div")
                  .style("font-size", "9px").style("color", "#555").style("padding-left", "10px")
                  .text(`${m.key}: ${typeof m.value === "number" ? m.value.toFixed(3) : m.value}`);
              });
              if (entries.length > 6) {
                measContainer.append("div")
                  .style("font-size", "9px").style("color", "#333").style("padding-left", "10px")
                  .text(`+ ${entries.length - 6} more`);
              }
            });
          });
        }
      });
    });
  });
}

function enterCompareMode(id, label) {
  loadSnapshotData(id).then((data) => {
    compareData = { filename: label || String(id), nodes: data.nodes };
    d3.select("#history-modal").style("display", "none");
    refreshData();
  });
}

function exitCompareMode() {
  compareData = null;
  refreshData();
}

// Keep renderHistoryBody as an alias for backwards compat
function renderHistoryBody() { _renderHistoryTab(_historyTab); }

