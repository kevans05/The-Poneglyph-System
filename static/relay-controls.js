"use strict";

function showTerminalPicker(title, options, callback) {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:20000;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText = "background:#111;border:1px solid #0af;padding:20px;display:flex;flex-direction:column;gap:8px;min-width:200px;";
  box.innerHTML = '<div style="font-size:10px;color:#888;margin-bottom:8px;">' + title + '</div>';
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.className = "eng-btn";
    btn.textContent = opt;
    btn.onclick = () => { document.body.removeChild(overlay); callback(opt); };
    box.appendChild(btn);
  });
  const cancel = document.createElement("button");
  cancel.className = "eng-btn";
  cancel.style.marginTop = "8px";
  cancel.style.borderColor = "#555";
  cancel.textContent = "CANCEL";
  cancel.onclick = () => { document.body.removeChild(overlay); cancelConnectionMode(); };
  box.appendChild(cancel);
  overlay.appendChild(box);
  document.body.appendChild(overlay);
}

function breakConnection(sourceId, targetId) {
  if (confirm("Break wire between " + sourceId + " and " + targetId + "?")) {
    reconfigureAPI(sourceId, "delete_connection", { target_id: targetId }).then(() => refreshData());
  }
}

