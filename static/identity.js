"use strict";

/**
 * identity.js — Per-user identity + stable signature.
 *
 * On startup the operator is asked who they are. The name is paired with a
 * UUID generated once and kept in localStorage, so that when this client is
 * pointed at a shared server every operator carries their own signature
 * (technician_id) on the sessions and measurements they record.
 *
 * Storage: localStorage["poneglyph.identity"] = {id, name, created}
 */
(function () {
  const KEY = "poneglyph.identity";

  function _uuid() {
    try {
      if (window.crypto && typeof crypto.randomUUID === "function")
        return crypto.randomUUID();
    } catch (e) {}
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function _read() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw);
      if (!obj || typeof obj.name !== "string" || !obj.name.trim()) return null;
      if (!obj.id) obj.id = _uuid(); // migrate a name-only record
      return obj;
    } catch (e) {
      return null;
    }
  }

  function _write(obj) {
    try {
      localStorage.setItem(KEY, JSON.stringify(obj));
    } catch (e) {}
  }

  // Shared with the measurement wizard's technician picker.
  const TECH_HIST_KEY = "bp_tech_history";

  function _knownNames() {
    try {
      const arr = JSON.parse(localStorage.getItem(TECH_HIST_KEY));
      return Array.isArray(arr) ? arr.filter((n) => typeof n === "string" && n.trim()) : [];
    } catch (e) {
      return [];
    }
  }

  function _rememberName(name) {
    name = String(name || "").trim();
    if (!name) return;
    try {
      const h = _knownNames().filter((n) => n !== name);
      h.unshift(name);
      localStorage.setItem(TECH_HIST_KEY, JSON.stringify(h.slice(0, 8)));
    } catch (e) {}
  }

  function _apply(obj) {
    if (!obj) return;
    // Feed the measurement wizard / tests, which read _technicianName lazily.
    try {
      window._technicianName = obj.name;
    } catch (e) {}
    const chip = document.getElementById("user-identity-chip");
    if (chip) {
      chip.textContent = "◆ " + obj.name;
      chip.title =
        "Signature " + String(obj.id).slice(0, 8) + " — click to change name";
    }
    // Register with the backend so topology changes get signed with this operator.
    try {
      fetch("/api/operator", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: obj.name, id: obj.id }),
      }).catch(() => {});
    } catch (e) {}
  }

  // Minimal self-contained prompt (no dependency on the shared dialog DOM).
  function _promptName(current, opts, done) {
    opts = opts || {};
    const overlay = document.createElement("div");
    overlay.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:11000;display:flex;" +
      "align-items:center;justify-content:center;";
    const box = document.createElement("div");
    box.style.cssText =
      "background:#0c0c0c;border:1px solid #0a0;padding:22px;min-width:360px;max-width:460px;" +
      "font-family:'Consolas','Courier New',monospace;display:flex;flex-direction:column;gap:10px;";

    const title = document.createElement("div");
    title.textContent = opts.title || "WHO ARE YOU?";
    title.style.cssText =
      "font-size:11px;color:#0f0;letter-spacing:2px;border-bottom:1px solid #1a1a1a;padding-bottom:8px;";
    box.appendChild(title);

    const hint = document.createElement("div");
    hint.textContent =
      opts.hint ||
      "Your name is stamped on every reading you record. A unique signature is kept for this device.";
    hint.style.cssText = "font-size:9px;color:#666;line-height:1.5;";
    box.appendChild(hint);

    let closed = false;
    const close = (val) => {
      if (closed) return;
      closed = true;
      document.body.removeChild(overlay);
      done(val);
    };

    // Suggestions from the shared technician history ("the user file"), plus
    // — once it loads — everyone else signed in on the hub, so a name can be
    // picked without ever having used this device before.
    const lbl = document.createElement("div");
    lbl.textContent = "KNOWN OPERATORS";
    lbl.style.cssText = "font-size:8px;color:#555;letter-spacing:2px;margin-top:2px;display:none;";
    box.appendChild(lbl);

    const list = document.createElement("div");
    list.style.cssText =
      "display:flex;flex-direction:column;gap:4px;max-height:180px;overflow-y:auto;";
    box.appendChild(list);

    const or = document.createElement("div");
    or.textContent = "— or type a new name —";
    or.style.cssText = "font-size:8px;color:#444;text-align:center;margin:2px 0;display:none;";
    box.appendChild(or);

    const shown = new Set();
    const addRow = (name, isHub) => {
      if (!name || name === current || shown.has(name)) return;
      shown.add(name);
      lbl.style.display = "block";
      or.style.display = "block";
      const r = document.createElement("div");
      r.style.cssText =
        "padding:8px 10px;border:1px solid #1a1a1a;color:#0f0;cursor:pointer;font-size:11px;" +
        "display:flex;justify-content:space-between;align-items:center;gap:8px;";
      const nameSpan = document.createElement("span");
      nameSpan.textContent = name;
      r.appendChild(nameSpan);
      if (isHub) {
        const tag = document.createElement("span");
        tag.textContent = "☁";
        tag.title = "signed in on the hub";
        tag.style.cssText = "color:#3fdc8f;font-size:10px;";
        r.appendChild(tag);
      }
      r.addEventListener("mouseenter", () => (r.style.background = "#0d1a0d"));
      r.addEventListener("mouseleave", () => (r.style.background = "transparent"));
      r.addEventListener("click", () => close(name));
      list.appendChild(r);
    };

    _knownNames().forEach((n) => addRow(n, false));
    if (window.PoneglyphHub && typeof PoneglyphHub.listUsers === "function") {
      PoneglyphHub.listUsers()
        .then((roster) => {
          (roster || []).forEach((u) => addRow((u.display_name || u.username || "").trim(), true));
        })
        .catch(() => {});
    }

    const field = document.createElement("input");
    field.type = "text";
    field.value = current || "";
    field.placeholder = "e.g. Cutty Flamm";
    field.style.cssText =
      "background:#111;border:1px solid #333;color:#0f0;padding:8px 10px;font-family:inherit;" +
      "font-size:12px;outline:none;";
    box.appendChild(field);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;margin-top:4px;";

    if (opts.allowCancel) {
      const cancel = document.createElement("button");
      cancel.textContent = "CANCEL";
      cancel.className = "wiz-secondary";
      cancel.onclick = () => close(null);
      row.appendChild(cancel);
    }
    const ok = document.createElement("button");
    ok.textContent = opts.okLabel || "CONFIRM";
    ok.className = "wiz-save";
    ok.onclick = () => {
      const v = field.value.trim();
      if (!v) {
        field.style.borderColor = "#a00";
        return;
      }
      close(v);
    };
    row.appendChild(ok);
    box.appendChild(row);

    field.addEventListener("keydown", (e) => {
      if (e.key === "Enter") ok.onclick();
      if (e.key === "Escape" && opts.allowCancel) close(null);
    });

    overlay.appendChild(box);
    document.body.appendChild(overlay);
    setTimeout(() => {
      field.focus();
      field.select();
    }, 0);
  }

  const API = {
    /** @returns {{id:string,name:string,created:number}|null} */
    get() {
      return _read();
    },
    getId() {
      const o = _read();
      return o ? o.id : "";
    },
    getName() {
      const o = _read();
      return o ? o.name : "";
    },
    /** Set / update the operator name, keeping the same signature id. */
    set(name) {
      name = String(name || "").trim();
      if (!name) return _read();
      const cur = _read();
      const obj = {
        id: cur && cur.id ? cur.id : _uuid(),
        name: name,
        created: cur && cur.created ? cur.created : Date.now(),
      };
      _write(obj);
      _rememberName(name);
      _apply(obj);
      return obj;
    },
    /**
     * Ensure an identity exists, prompting once if not, then invoke cb(identity).
     * Safe to call with no cb.
     */
    ensure(cb) {
      const existing = _read();
      if (existing) {
        _apply(existing);
        if (cb) cb(existing);
        return;
      }
      const ask = (prefill) => {
        _promptName(
          prefill || "",
          {
            title: "WHO ARE YOU?",
            okLabel: "BEGIN",
            allowCancel: false,
          },
          (name) => {
            const obj = API.set(name || prefill || "Operator");
            if (cb) cb(obj);
          },
        );
      };
      // Pre-fill with the OS login name (getpass on the backend), still editable.
      fetch("/api/whoami")
        .then((r) => r.json())
        .then((d) => ask(d && d.user))
        .catch(() => ask(""));
    },
    /** Re-prompt for the name (keeps the signature id). */
    promptChange() {
      const cur = _read();
      _promptName(
        cur ? cur.name : "",
        {
          title: "CHANGE OPERATOR NAME",
          hint:
            "Your signature id stays the same — only the displayed name changes.",
          okLabel: "SAVE",
          allowCancel: true,
        },
        (name) => {
          if (name) API.set(name);
        },
      );
    },
  };

  window.PoneglyphIdentity = API;

  // Apply a stored identity as early as possible so _technicianName is ready.
  document.addEventListener("DOMContentLoaded", () => {
    const o = _read();
    if (o) _apply(o);
  });
})();
