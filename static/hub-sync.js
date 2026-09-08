"use strict";

/**
 * hub-sync.js — the SUBSTATION side of the Poneglyph Hub (Phase 2/3).
 *
 * The heavy lifting (version graph, 3-way structural merge) lives in the desktop
 * server at /api/hub-sync/*.  This module is the panel that drives it: link,
 * pull, push, and a conflict resolver.
 */

function _hsGET() {
  return fetch("/api/hub-sync/status").then((r) => r.json());
}

function _hsPOST(action, body) {
  return fetch("/api/hub-sync/" + action, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }).then((r) => r.json());
}

function _hsEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

function showHubSyncPanel() {
  if (typeof getActiveSiteInfo === "function" && !getActiveSiteInfo()) {
    alert("Load a site first.");
    return;
  }
  let overlay = document.getElementById("hub-sync-overlay");
  if (overlay) overlay.remove();

  overlay = document.createElement("div");
  overlay.id = "hub-sync-overlay";
  overlay.style.cssText =
    "position:fixed; inset:0; background:rgba(0,0,0,0.8); z-index:11300; " +
    "display:flex; align-items:center; justify-content:center; font-family:'Consolas','Courier New',monospace;";
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) overlay.remove(); });

  const panel = document.createElement("div");
  panel.style.cssText =
    "background:#0c0c0c; border:1px solid #3fdc8f; width:600px; max-height:84vh; " +
    "overflow-y:auto; color:#ccc; display:flex; flex-direction:column;";
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  _hsRender(panel);
}

function _hsRender(panel) {
  panel.innerHTML =
    '<div style="display:flex; justify-content:space-between; align-items:center;' +
    ' border-bottom:1px solid #1a1a1a; padding:10px 14px; color:#3fdc8f;' +
    ' letter-spacing:2px; font-size:11px;"><span>☁ SUBSTATION SYNC</span>' +
    '<span id="hs-x" style="cursor:pointer; color:#666;">[X]</span></div>' +
    '<div id="hs-body" style="padding:14px; font-size:11px; line-height:1.7;">Loading…</div>';
  panel.querySelector("#hs-x").onclick = () =>
    document.getElementById("hub-sync-overlay").remove();

  const body = panel.querySelector("#hs-body");

  Promise.all([_hsGET(), Promise.resolve(PoneglyphHub.status())])
    .then(([st, hub]) => {
      if (!hub.connected) {
        body.innerHTML =
          '<div style="color:#888;">Not signed in to a hub.<br>' +
          '<span style="color:#555;">Open ⚙ SETTINGS → PONEGLYPH HUB to sign in, then reopen this panel.</span></div>';
        return;
      }

      const btn = (label, color) =>
        '<button style="background:#04121c; border:1px solid ' + color + "; color:" + color +
        "; font-family:inherit; font-size:10px; letter-spacing:1px; padding:6px 12px;" +
        ' cursor:pointer; margin-right:8px;">' + label + "</button>";

      if (!st.linked) {
        const site =
          (typeof getActiveSiteInfo === "function" && getActiveSiteInfo()) || {};
        const defId = site.number_code || site.station || "";
        body.innerHTML =
          '<div style="margin-bottom:12px;">This site is <b>not linked</b> to a hub substation.</div>' +
          '<div style="color:#888; margin-bottom:10px;">Hub: ' + _hsEsc(hub.url) +
          " &nbsp;·&nbsp; signed in as " + _hsEsc(hub.user) + "</div>" +
          '<div style="display:flex; flex-direction:column; gap:10px;">' +
          '<div><label style="color:#888; font-size:10px;">SUBSTATION ID</label><br>' +
          '<input id="hs-subid" value="' + _hsEsc(defId) +
          '" style="background:#111; border:1px solid #333; color:#eee; padding:5px 8px;' +
          ' font-family:inherit; font-size:11px; width:220px;"></div>' +
          "<div>" +
          btn("⇪ CREATE ON HUB", "#3fdc8f") +
          btn("⇩ ATTACH TO EXISTING", "#4aa8d8") +
          "</div>" +
          '<div id="hs-sublist" style="color:#666; font-size:10px;"></div>' +
          '<div id="hs-msg" style="color:#8a8; min-height:14px;"></div></div>';

        const subid = () => body.querySelector("#hs-subid").value.trim();
        const msg = body.querySelector("#hs-msg");
        const btns = body.querySelectorAll("button");
        btns[0].onclick = () => {
          if (!subid()) { msg.textContent = "Enter a substation id."; return; }
          msg.textContent = "Creating on hub…";
          _hsPOST("link", {
            ...PoneglyphHub.creds(), mode: "create",
            substation_id: subid(), name: site.site_name || subid(),
          }).then((r) => {
            if (r.error) { msg.textContent = "✗ " + r.error; return; }
            _hsRender(panel);
          });
        };
        btns[1].onclick = () => {
          if (!subid()) { msg.textContent = "Enter the substation id to attach to."; return; }
          if (!confirm("Attach replaces this site's topology with the hub's version. Continue?")) return;
          msg.textContent = "Attaching…";
          _hsPOST("link", {
            ...PoneglyphHub.creds(), mode: "attach", substation_id: subid(),
          }).then((r) => {
            if (r.error) { msg.textContent = "✗ " + r.error; return; }
            if (typeof refreshData === "function") refreshData();
            _hsRender(panel);
          });
        };

        PoneglyphHub.browseSubstations()
          .then((subs) => {
            const el = body.querySelector("#hs-sublist");
            if (!el) return;
            el.innerHTML = subs.length
              ? "On this hub: " +
                subs.map((s) =>
                  '<a href="#" data-s="' + _hsEsc(s.id) + '" style="color:#4aa8d8;"' +
                  ' title="' + _hsEsc(s.summary || "") + '">' +
                  _hsEsc(s.id) + "</a> (" + s.version_count + ")").join(" · ")
              : "No substations on this hub yet.";
            el.querySelectorAll("a[data-s]").forEach((a) => {
              a.onclick = (e) => {
                e.preventDefault();
                body.querySelector("#hs-subid").value = a.getAttribute("data-s");
              };
            });
          })
          .catch(() => {});
        return;
      }

      // ---- linked ----
      const rows = [
        ["Hub", _hsEsc(hub.url)],
        ["Substation", _hsEsc(st.substation_id)],
        ["Branch", _hsEsc(st.branch)],
        ["Local head", (st.head_id || "").slice(0, 10) || "—"],
        ["Synced to", (st.base_id || "").slice(0, 10) || "—"],
        ["Unpushed commits", String(st.ahead)],
      ];
      if (st.pending_conflicts) rows.push(["Pending conflicts", String(st.pending_conflicts)]);

      body.innerHTML =
        '<table style="border-collapse:collapse; margin-bottom:14px;">' +
        rows.map((r) =>
          '<tr><td style="color:#888; padding:2px 14px 2px 0;">' + r[0] +
          '</td><td style="color:#ddd;">' + r[1] + "</td></tr>").join("") +
        "</table>" +
        "<div>" +
        btn("⇩ PULL", "#4aa8d8") +
        btn("⇪ PUSH", "#3fdc8f") +
        btn("UNLINK", "#a66") +
        "</div>" +
        '<div id="hs-msg" style="color:#8a8; margin-top:12px; min-height:14px;"></div>';

      const msg = body.querySelector("#hs-msg");
      const [pullB, pushB, unlinkB] = body.querySelectorAll("button");

      if (st.pending_conflicts) {
        msg.innerHTML =
          '<span style="color:#d8a24a;">A pull is waiting on ' + st.pending_conflicts +
          " conflict(s).</span>";
        _hsShowConflicts(panel);
      }

      pullB.onclick = () => {
        msg.textContent = "Pulling…";
        _hsPOST("pull", PoneglyphHub.creds()).then((r) => {
          if (r.error) { msg.textContent = "✗ " + r.error; return; }
          if (r.conflicts && r.conflicts.length) {
            msg.innerHTML = '<span style="color:#d8a24a;">' + r.conflicts.length +
              " conflict(s) — resolve below.</span>";
            _hsShowConflicts(panel, r.conflicts);
            return;
          }
          if (typeof refreshData === "function") refreshData();
          msg.textContent = r.up_to_date
            ? "✓ already up to date"
            : r.fast_forward ? "✓ fast-forwarded" : "✓ merged";
          setTimeout(() => _hsRender(panel), 700);
        });
      };
      pushB.onclick = () => {
        msg.textContent = "Pushing…";
        _hsPOST("push", PoneglyphHub.creds()).then((r) => {
          if (r.error) { msg.textContent = "✗ " + r.error; return; }
          if (r.conflict) {
            msg.innerHTML = '<span style="color:#d8a24a;">Hub moved on — pull first, then push.</span>';
            return;
          }
          msg.textContent = r.up_to_date ? "✓ nothing to push" : "✓ pushed " + r.pushed;
          setTimeout(() => _hsRender(panel), 700);
        });
      };
      unlinkB.onclick = () => {
        if (!confirm("Unlink from the hub? Local version history is kept.")) return;
        _hsPOST("unlink", {}).then(() => _hsRender(panel));
      };
    })
    .catch(() => {
      body.innerHTML = '<div style="color:#c66;">Could not read sync status.</div>';
    });
}

function _hsShowConflicts(panel, conflicts) {
  let box = panel.querySelector("#hs-conflicts");
  if (box) box.remove();
  box = document.createElement("div");
  box.id = "hs-conflicts";
  box.style.cssText =
    "border-top:1px solid #1a1a1a; margin-top:12px; padding:12px 14px; font-size:11px;";
  panel.querySelector("#hs-body").appendChild(box);

  // If not passed, we came from a reopened panel with a stashed pending merge —
  // ask the server to replay them via a no-op resolve preview isn't available,
  // so require the caller to pass them. Reopened case: instruct a fresh pull.
  if (!conflicts) {
    box.innerHTML =
      '<div style="color:#888;">Conflicts are staged on the server. ' +
      'Click PULL again to list them, or resolve with the last choices:</div>' +
      '<button id="hs-force" style="margin-top:8px; background:#04121c; border:1px solid #d8a24a;' +
      ' color:#d8a24a; font-family:inherit; font-size:10px; padding:5px 10px; cursor:pointer;">' +
      "RESOLVE (keep server-staged choices)</button>";
    box.querySelector("#hs-force").onclick = () =>
      _hsPOST("resolve", { ...PoneglyphHub.creds() }).then(() => {
        if (typeof refreshData === "function") refreshData();
        _hsRender(panel);
      });
    return;
  }

  const rowFor = (c, i) => {
    const label =
      c.kind === "delete-edit"
        ? c.device_id + " — deleted on one side"
        : c.kind === "connection"
          ? c.device_id + " · connection → " + c.target
          : c.device_id + " · " + c.field;
    const val = (v) =>
      v == null ? '<i style="color:#666;">(removed)</i>' : _hsEsc(JSON.stringify(v));
    return (
      '<div style="border:1px solid #222; border-radius:3px; padding:8px 10px; margin-bottom:8px;">' +
      '<div style="color:#d8a24a; margin-bottom:5px;">' + _hsEsc(label) + "</div>" +
      '<label style="display:block; margin:2px 0;"><input type="radio" name="hsc' + i +
      '" value="ours" checked> ours: ' + val(c.ours) + "</label>" +
      '<label style="display:block; margin:2px 0;"><input type="radio" name="hsc' + i +
      '" value="theirs"> theirs: ' + val(c.theirs) + "</label>" +
      "</div>"
    );
  };

  box.innerHTML =
    '<div style="color:#d8a24a; letter-spacing:1px; margin-bottom:8px;">RESOLVE CONFLICTS</div>' +
    conflicts.map(rowFor).join("") +
    '<button id="hs-apply" style="background:#001a0a; border:1px solid #0f6; color:#0f6;' +
    ' font-family:inherit; font-size:10px; letter-spacing:1px; padding:6px 14px; cursor:pointer;">' +
    "APPLY RESOLUTION</button>";

  box.querySelector("#hs-apply").onclick = () => {
    const resolutions = conflicts.map((c, i) => {
      const sel = box.querySelector('input[name="hsc' + i + '"]:checked');
      return { ...c, choice: sel ? sel.value : "ours" };
    });
    _hsPOST("resolve", { ...PoneglyphHub.creds(), resolutions }).then((r) => {
      if (r.error) { alert("Resolve failed: " + r.error); return; }
      if (typeof refreshData === "function") refreshData();
      _hsRender(panel);
    });
  };
}

window.showHubSyncPanel = showHubSyncPanel;
