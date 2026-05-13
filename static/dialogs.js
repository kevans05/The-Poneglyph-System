"use strict";

// ── Generic input dialog (replaces all browser prompt() calls) ─────────────────

function showInputDialog(label, defaultVal, callback) {
  const dialog = document.getElementById("input-dialog");
  const field = document.getElementById("input-dialog-field");
  const labelEl = document.getElementById("input-dialog-label");
  labelEl.textContent = label;
  field.value = defaultVal || "";
  dialog.style.display = "flex";
  field.focus();
  field.select();

  const finish = (ok) => {
    dialog.style.display = "none";
    document.getElementById("input-dialog-ok").onclick = null;
    document.getElementById("input-dialog-cancel").onclick = null;
    field.onkeydown = null;
    if (ok) callback(field.value.trim());
  };

  document.getElementById("input-dialog-ok").onclick = () => finish(true);
  document.getElementById("input-dialog-cancel").onclick = () => finish(false);
  field.onkeydown = (e) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  };
}

function showRenameDialog(id) {
  showInputDialog("NEW DEVICE NAME / ID", id, (newId) => {
    if (!newId || newId === id) return;
    renameDevice(id, newId).then(() => {
      if (openWindows[id]) {
        closeWindow(id);
      }
      refreshData();
    });
  });
}

