"""Right-side properties panel.

Shows editable fields for whatever is selected in the diagram.
Calls an on_change callback whenever the user applies an edit.
"""

from __future__ import annotations

import cmath
import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from poneglyph.ui.diagram import (
    DiagramBus, DiagramConnection, DiagramCT, DiagramVT,
    DiagramTransformer, DiagramSource, DiagramLoad,
    DiagramBreaker, DiagramDisconnect,
    DiagramCTTB, DiagramTestBlock,
    DiagramRelay, DiagramRelayWire, DiagramDrawing,
)


class DrawingPickerDialog(tk.Toplevel):
    """Modal popup to attach drawings from project registry to a device."""

    def __init__(self, parent, device, diagram, on_change):
        super().__init__(parent)
        self.title("Attach Drawings")
        self.resizable(True, True)
        self.grab_set()
        self._device = device
        self._diagram = diagram
        self._on_change = on_change
        self._build()

    def _build(self):
        # Left: project drawings registry listbox
        # Right: device's current drawings list
        # Buttons: Add >> and << Remove, plus a manual entry

        main = tk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(2, weight=1)

        tk.Label(main, text="Project drawings", font=("TkDefaultFont", 9, "bold")).grid(
            row=0, column=0, sticky="w")
        tk.Label(main, text="Attached to device", font=("TkDefaultFont", 9, "bold")).grid(
            row=0, column=2, sticky="w")

        # Registry listbox
        reg_frame = tk.Frame(main)
        reg_frame.grid(row=1, column=0, sticky="nsew", pady=(4,0))
        reg_lb = tk.Listbox(reg_frame, height=12, selectmode=tk.EXTENDED, exportselection=False)
        reg_sb = ttk.Scrollbar(reg_frame, orient="vertical", command=reg_lb.yview)
        reg_lb.configure(yscrollcommand=reg_sb.set)
        reg_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        reg_sb.pack(side=tk.RIGHT, fill=tk.Y)
        drawings = {}
        if self._diagram is not None:
            drawings = getattr(self._diagram, "_drawings", {})
        for dname in sorted(drawings.keys()):
            reg_lb.insert(tk.END, dname)

        # Middle buttons
        mid = tk.Frame(main)
        mid.grid(row=1, column=1, padx=8)
        tk.Button(mid, text="Add >>", command=lambda: self._add(reg_lb, dev_lb)).pack(pady=4)
        tk.Button(mid, text="<< Remove", command=lambda: self._remove(dev_lb)).pack(pady=4)

        # Device drawings listbox
        dev_frame = tk.Frame(main)
        dev_frame.grid(row=1, column=2, sticky="nsew", pady=(4,0))
        dev_lb = tk.Listbox(dev_frame, height=12, selectmode=tk.EXTENDED, exportselection=False)
        dev_sb = ttk.Scrollbar(dev_frame, orient="vertical", command=dev_lb.yview)
        dev_lb.configure(yscrollcommand=dev_sb.set)
        dev_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dev_sb.pack(side=tk.RIGHT, fill=tk.Y)
        for d in getattr(self._device, "device_drawings", []):
            dev_lb.insert(tk.END, d)

        # Manual entry row
        manual_frame = tk.Frame(self)
        manual_frame.pack(fill=tk.X, padx=8, pady=(0,4))
        tk.Label(manual_frame, text="Add manually:").pack(side=tk.LEFT)
        manual_var = tk.StringVar()
        tk.Entry(manual_frame, textvariable=manual_var, width=20).pack(side=tk.LEFT, padx=4)
        tk.Button(manual_frame, text="Add",
                  command=lambda: self._add_manual(manual_var, dev_lb)).pack(side=tk.LEFT)

        # Bottom buttons
        btn_row = tk.Frame(self)
        btn_row.pack(fill=tk.X, padx=8, pady=(0,8))
        tk.Button(btn_row, text="OK", command=lambda: self._ok(dev_lb)).pack(side=tk.RIGHT, padx=4)
        tk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _add(self, reg_lb, dev_lb):
        existing = set(dev_lb.get(0, tk.END))
        for i in reg_lb.curselection():
            name = reg_lb.get(i)
            if name not in existing:
                dev_lb.insert(tk.END, name)
                existing.add(name)

    def _remove(self, dev_lb):
        for i in reversed(dev_lb.curselection()):
            dev_lb.delete(i)

    def _add_manual(self, var, dev_lb):
        name = var.get().strip()
        if name and name not in dev_lb.get(0, tk.END):
            dev_lb.insert(tk.END, name)
            var.set("")

    def _ok(self, dev_lb):
        self._device.device_drawings = list(dev_lb.get(0, tk.END))
        if self._on_change:
            self._on_change()
        self.destroy()


class _RowCounter:
    """Hands out monotonically increasing grid row indices."""

    def __init__(self) -> None:
        self._r = -1

    def next(self) -> int:
        self._r += 1
        return self._r


class PropertiesPanel(tk.Frame):
    """Displays and edits properties of the selected diagram element."""

    def __init__(self, parent: tk.Widget, on_change: Optional[Callable] = None) -> None:
        super().__init__(parent, relief="groove", bd=1)
        self._on_change = on_change
        self._current: Optional[object] = None
        self._diagram = None

        # Top-level notebook: Properties | Meter Readings
        self._panel_nb = ttk.Notebook(self)
        self._panel_nb.pack(fill=tk.BOTH, expand=True)

        # ── Properties tab ──────────────────────────────────────────────
        _props_tab = tk.Frame(self._panel_nb)
        self._panel_nb.add(_props_tab, text="Properties")

        self._canvas_frame = tk.Canvas(_props_tab, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(_props_tab, orient="vertical",
                                        command=self._canvas_frame.yview)
        self._canvas_frame.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas_frame.pack(fill=tk.BOTH, expand=True)
        self._body = tk.Frame(self._canvas_frame)
        self._body_win = self._canvas_frame.create_window(
            (0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>", lambda e: self._canvas_frame.configure(
            scrollregion=self._canvas_frame.bbox("all")))
        self._canvas_frame.bind("<Configure>", lambda e: self._canvas_frame.itemconfig(
            self._body_win, width=e.width))

        # ── Meter Readings tab ───────────────────────────────────────────
        _mr_tab = tk.Frame(self._panel_nb)
        self._panel_nb.add(_mr_tab, text="Meter Readings")

        self._mr_canvas = tk.Canvas(_mr_tab, highlightthickness=0)
        self._mr_scrollbar = ttk.Scrollbar(_mr_tab, orient="vertical",
                                           command=self._mr_canvas.yview)
        self._mr_canvas.configure(yscrollcommand=self._mr_scrollbar.set)
        self._mr_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._mr_canvas.pack(fill=tk.BOTH, expand=True)
        self._mr_body = tk.Frame(self._mr_canvas)
        self._mr_body_win = self._mr_canvas.create_window(
            (0, 0), window=self._mr_body, anchor="nw")
        self._mr_body.bind("<Configure>", lambda e: self._mr_canvas.configure(
            scrollregion=self._mr_canvas.bbox("all")))
        self._mr_canvas.bind("<Configure>", lambda e: self._mr_canvas.itemconfig(
            self._mr_body_win, width=e.width))

        # ── Predictions tab ──────────────────────────────────────────────
        _pred_tab = tk.Frame(self._panel_nb)
        self._panel_nb.add(_pred_tab, text="Predictions")

        self._pred_canvas = tk.Canvas(_pred_tab, highlightthickness=0)
        self._pred_scrollbar = ttk.Scrollbar(_pred_tab, orient="vertical",
                                             command=self._pred_canvas.yview)
        self._pred_canvas.configure(yscrollcommand=self._pred_scrollbar.set)
        self._pred_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._pred_canvas.pack(fill=tk.BOTH, expand=True)
        self._pred_body = tk.Frame(self._pred_canvas)
        self._pred_body_win = self._pred_canvas.create_window(
            (0, 0), window=self._pred_body, anchor="nw")
        self._pred_body.bind("<Configure>", lambda e: self._pred_canvas.configure(
            scrollregion=self._pred_canvas.bbox("all")))
        self._pred_canvas.bind("<Configure>", lambda e: self._pred_canvas.itemconfig(
            self._pred_body_win, width=e.width))

        self._show_empty()

    # ── Public ────────────────────────────────────────────────────────────

    def set_diagram(self, diagram) -> None:
        """Store a reference to the diagram for accessing the drawings registry."""
        self._diagram = diagram

    def show_bus(self, bus: DiagramBus) -> None:
        self._current = bus
        self._populate_mr(bus)
        self._populate_predictions(bus)
        self._clear()

        v_name = tk.StringVar(value=bus.name)
        v_kv   = tk.StringVar(value=str(bus.kv))

        self._row("ID",       tk.StringVar(value=bus.id), readonly=True)
        self._row("Name",     v_name)
        self._row("Base kV",  v_kv)
        self._row("Nodes",    tk.StringVar(value=str(len(bus.nodes))),    readonly=True)
        self._row("Segments", tk.StringVar(value=str(len(bus.edges))),    readonly=True)

        def apply():
            bus.name = v_name.get().strip() or bus.name
            try:
                bus.kv = float(v_kv.get())
            except ValueError:
                pass
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_connection(self, conn: DiagramConnection) -> None:
        self._current = conn
        self._populate_mr(conn)
        self._populate_predictions(conn)
        self._clear()

        kind_label = {"tline": "Transmission Line", "feeder": "Feeder",
                      "transformer": "Transformer"}.get(conn.kind, conn.kind)
        tk.Label(self._body, text=kind_label, font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        v_name = tk.StringVar(value=conn.name)
        v_r    = tk.StringVar(value=str(conn.r_pu))
        v_x    = tk.StringVar(value=str(conn.x_pu))
        v_bkr  = tk.BooleanVar(value=conn.has_breaker_from)

        self._row("ID",          tk.StringVar(value=conn.id), readonly=True, start_row=1)
        self._row("Name",        v_name, start_row=2)
        self._row("R (pu)",      v_r,    start_row=3)
        self._row("X (pu)",      v_x,    start_row=4)
        tk.Checkbutton(self._body, text="Breaker at source end", variable=v_bkr).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=2,
        )

        def apply():
            conn.name = v_name.get().strip() or conn.name
            try:
                conn.r_pu = float(v_r.get())
                conn.x_pu = float(v_x.get())
            except ValueError:
                pass
            conn.has_breaker_from = v_bkr.get()
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    _WINDING_TYPES = ("wye", "delta", "zigzag")
    _TAP_CHANGERS  = ("None", "LTC", "DETC")

    def show_transformer(self, xfmr: DiagramTransformer) -> None:
        if xfmr is None:
            return
        self._current = xfmr
        self._populate_mr(xfmr)
        self._populate_predictions(xfmr)
        self._clear()

        row = _RowCounter()
        tk.Label(self._body, text="Power Transformer", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=row.next(), column=0, columnspan=2, sticky="w", pady=(0, 6))

        v_name = tk.StringVar(value=xfmr.name)
        v_mva  = tk.StringVar(value=str(xfmr.mva))
        v_hvkv = tk.StringVar(value=str(xfmr.hv_kv))
        v_lvkv = tk.StringVar(value=str(xfmr.lv_kv))
        v_z    = tk.StringVar(value=str(xfmr.z_pct))
        v_ratio = tk.StringVar()

        def recompute_ratio(*_a):
            try:
                hv, lv = float(v_hvkv.get()), float(v_lvkv.get())
                v_ratio.set(f"{hv:g} : {lv:g} kV" if hv and lv else "—")
            except ValueError:
                v_ratio.set("—")
        v_hvkv.trace_add("write", recompute_ratio)
        v_lvkv.trace_add("write", recompute_ratio)
        recompute_ratio()

        self._row("ID",             tk.StringVar(value=xfmr.id), readonly=True, start_row=row.next())
        self._row("Name",           v_name, start_row=row.next())
        self._row("Power (MVA)",    v_mva,  start_row=row.next())
        self._row("HV winding (kV)", v_hvkv, start_row=row.next())
        self._row("LV winding (kV)", v_lvkv, start_row=row.next())
        self._row("Voltage Ratio",  v_ratio, readonly=True, start_row=row.next())
        self._row("Impedance (%Z)", v_z,    start_row=row.next())

        r_tap = row.next()
        tk.Label(self._body, text="Tap Changer", anchor="w").grid(
            row=r_tap, column=0, sticky="w", pady=2, padx=(0, 8))
        v_tap = tk.StringVar(value=xfmr.tap_changer)
        ttk.Combobox(self._body, textvariable=v_tap, values=self._TAP_CHANGERS,
                     state="readonly", width=9).grid(row=r_tap, column=1, sticky="ew", pady=2)

        # ── Winding configuration ──────────────────────────────────────────
        ttk.Separator(self._body).grid(row=row.next(), column=0, columnspan=2,
                                       sticky="ew", pady=(8, 4))
        tk.Label(self._body, text="Winding Configuration",
                 font=("TkDefaultFont", 9, "bold"), anchor="w").grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=(0, 4))

        v_hv_type = tk.StringVar(value=xfmr.hv_winding)
        v_lv_type = tk.StringVar(value=xfmr.lv_winding)
        v_hv_gnd  = tk.BooleanVar(value=xfmr.hv_grounded)
        v_lv_gnd  = tk.BooleanVar(value=xfmr.lv_grounded)

        r_hv = row.next()
        tk.Label(self._body, text="HV side", anchor="w").grid(
            row=r_hv, column=0, sticky="w", pady=2, padx=(0, 8))
        ttk.Combobox(self._body, textvariable=v_hv_type, values=self._WINDING_TYPES,
                     state="readonly", width=9).grid(row=r_hv, column=1, sticky="ew", pady=2)
        tk.Checkbutton(self._body, text="HV neutral grounded", variable=v_hv_gnd).grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=2)

        r_lv = row.next()
        tk.Label(self._body, text="LV side", anchor="w").grid(
            row=r_lv, column=0, sticky="w", pady=2, padx=(0, 8))
        ttk.Combobox(self._body, textvariable=v_lv_type, values=self._WINDING_TYPES,
                     state="readonly", width=9).grid(row=r_lv, column=1, sticky="ew", pady=2)
        tk.Checkbutton(self._body, text="LV neutral grounded", variable=v_lv_gnd).grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=2)

        def apply():
            xfmr.name = v_name.get().strip() or xfmr.name
            try:
                xfmr.mva   = float(v_mva.get())
                xfmr.hv_kv = float(v_hvkv.get())
                xfmr.lv_kv = float(v_lvkv.get())
                xfmr.z_pct = float(v_z.get())
            except ValueError:
                pass
            xfmr.tap_changer = v_tap.get()
            xfmr.hv_winding  = v_hv_type.get()
            xfmr.lv_winding  = v_lv_type.get()
            xfmr.hv_grounded = v_hv_gnd.get()
            xfmr.lv_grounded = v_lv_gnd.get()
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_source(self, src: DiagramSource) -> None:
        if src is None:
            return
        self._current = src
        self._populate_mr(src)
        self._populate_predictions(src)
        self._clear()
        tk.Label(self._body, text="Power Source (slack)", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name  = tk.StringVar(value=src.name)
        v_vpu   = tk.StringVar(value=str(src.v_pu))
        v_angle = tk.StringVar(value=str(src.angle_deg))
        self._row("ID",         tk.StringVar(value=src.id), readonly=True, start_row=1)
        self._row("Name",       v_name,  start_row=2)
        self._row("Voltage (pu)", v_vpu,  start_row=3)
        tk.Label(self._body, text="  1.0 pu = bus nominal kV (e.g. 1.0 = 11 kV on an 11 kV bus).\n"
                                  "  Typical range 0.95–1.05 pu.",
                 justify="left", fg="#888888",
                 font=("TkDefaultFont", 7), wraplength=180).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=(4, 0), pady=(0, 4))
        self._row("Angle (deg)", v_angle, start_row=5)
        bus_txt = src.bus if src.bus else "(not attached)"
        self._row("Bus",        tk.StringVar(value=bus_txt), readonly=True, start_row=6)

        def apply():
            src.name = v_name.get().strip() or src.name
            try:
                src.v_pu      = float(v_vpu.get())
                src.angle_deg = float(v_angle.get())
            except ValueError:
                pass
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_load(self, ld: DiagramLoad) -> None:
        if ld is None:
            return
        self._current = ld
        self._populate_mr(ld)
        self._populate_predictions(ld)
        self._clear()
        import math

        MODES = ["P+Q", "P+PF", "kVAR+PF", "kVA+PF", "V+I+PF"]
        MODE_FIELDS = {
            "P+Q":     [("P",   "p_kw",   "kW"),   ("Q",   "q_kvar", "kVAR")],
            "P+PF":    [("P",   "p_kw",   "kW"),   ("PF",  "pf",     "0–1")],
            "kVAR+PF": [("Q",   "q_kvar", "kVAR"), ("PF",  "pf",     "0–1")],
            "kVA+PF":  [("kVA", "s_kva",  "kVA"),  ("PF",  "pf",     "0–1")],
            "V+I+PF":  [("V",   "v_kv",   "kV"),   ("I",   "i_amps", "A"),
                        ("PF",  "pf",     "0–1")],
        }
        # per-phase attr suffixes
        PH_SUFFIX = {"A": "_a", "B": "_b", "C": "_c"}

        tk.Label(self._body, text="Load", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        v_name = tk.StringVar(value=ld.name)
        self._row("ID",   tk.StringVar(value=ld.id), readonly=True, start_row=1)
        self._row("Name", v_name, start_row=2)

        # Phase mode toggle
        tk.Label(self._body, text="Phase mode", anchor="e").grid(
            row=3, column=0, sticky="e", padx=(0, 4))
        v_phase = tk.StringVar(value=ld.phase_mode)
        ttk.Combobox(self._body, textvariable=v_phase,
                     values=["balanced", "individual"],
                     state="readonly", width=11).grid(row=3, column=1, sticky="w")

        # Container for either balanced fields or per-phase notebook
        _spec_frame = tk.Frame(self._body)
        _spec_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        _spec_frame.columnconfigure(1, weight=1)

        # Solved summary
        tk.Label(self._body, text="Solved", font=("TkDefaultFont", 9, "bold"),
                 fg="#444").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        v_solved = tk.StringVar()
        tk.Label(self._body, textvariable=v_solved, justify="left",
                 font=("TkFixedFont", 8), fg="#0044AA").grid(
            row=6, column=0, columnspan=2, sticky="w")

        bus_txt = ld.bus if ld.bus else "(not attached)"
        self._row("Bus", tk.StringVar(value=bus_txt), readonly=True, start_row=7)

        # Tracks vars for apply()
        _bal_vars: dict = {}            # balanced mode: attr → StringVar
        _bal_lag_var: tk.StringVar | None = None
        _bal_mode_var: tk.StringVar | None = None
        _ph_vars: dict = {}             # individual: (phase, attr) → StringVar
        _ph_lag_vars: dict = {}         # phase → StringVar
        _ph_mode_vars: dict = {}        # phase → StringVar

        def _refresh_solved(*_):
            # Apply current widget values to a scratch object for live preview
            _apply_to_load(ld, preview=True)
            p, q = ld._resolved()
            s = math.sqrt(p**2 + q**2)
            pf_val = p / s if s > 0 else 0.0
            lag = "lag" if q >= 0 else "lead"
            if ld.phase_mode == "individual":
                phases = ld._resolved_phases()
                lines = []
                for ph, (pp, pq) in zip("ABC", phases):
                    ps = math.sqrt(pp**2 + pq**2)
                    ppf = pp / ps if ps > 0 else 0.0
                    lines.append(f"Ph{ph}: {pp:.0f} kW  {pq:.0f} kVAR  PF={ppf:.3f}")
                lines.append(f"Tot : {p:.0f} kW  {q:.0f} kVAR")
                v_solved.set("\n".join(lines))
            else:
                v_solved.set(
                    f"P  = {p:>9.1f} kW\n"
                    f"Q  = {q:>9.1f} kVAR\n"
                    f"S  = {s:>9.1f} kVA\n"
                    f"PF = {pf_val:>9.3f} {lag}"
                )

        def _apply_to_load(target, preview=False):
            """Write current widget state into target DiagramLoad."""
            target.phase_mode = v_phase.get()
            if target.phase_mode == "balanced":
                if _bal_mode_var:
                    target.spec_mode = _bal_mode_var.get()
                if _bal_lag_var:
                    target.lagging = _bal_lag_var.get().startswith("Lagging")
                for attr, var in _bal_vars.items():
                    try: setattr(target, attr, float(var.get()))
                    except ValueError: pass
            else:
                for (ph, attr), var in _ph_vars.items():
                    suffix = PH_SUFFIX[ph]
                    try: setattr(target, attr + suffix, float(var.get()))
                    except ValueError: pass
                for ph, var in _ph_lag_vars.items():
                    suffix = PH_SUFFIX[ph]
                    setattr(target, "lagging" + suffix, var.get().startswith("Lagging"))
                for ph, var in _ph_mode_vars.items():
                    suffix = PH_SUFFIX[ph]
                    setattr(target, "spec_mode" + suffix, var.get())

        def _build_balanced_fields(parent):
            _bal_vars.clear()
            nonlocal _bal_lag_var, _bal_mode_var
            for w in parent.winfo_children():
                w.destroy()

            _bal_mode_var = tk.StringVar(value=ld.spec_mode)
            tk.Label(parent, text="Spec mode", anchor="e").grid(
                row=0, column=0, sticky="e", padx=(0, 4))
            mode_cb = ttk.Combobox(parent, textvariable=_bal_mode_var,
                                   values=MODES, state="readonly", width=12)
            mode_cb.grid(row=0, column=1, sticky="w")

            tk.Label(parent, text="Q sign", anchor="e").grid(
                row=1, column=0, sticky="e", padx=(0, 4))
            _bal_lag_var = tk.StringVar(
                value="Lagging (ind)" if ld.lagging else "Leading (cap)")
            ttk.Combobox(parent, textvariable=_bal_lag_var,
                         values=["Lagging (ind)", "Leading (cap)"],
                         state="readonly", width=14).grid(row=1, column=1, sticky="w")

            input_f = tk.Frame(parent)
            input_f.grid(row=2, column=0, columnspan=2, sticky="ew")
            input_f.columnconfigure(1, weight=1)

            def _rebuild_bal_inputs(*_):
                for w in input_f.winfo_children():
                    w.destroy()
                _bal_vars.clear()
                for r, (lbl, attr, hint) in enumerate(MODE_FIELDS.get(_bal_mode_var.get(), [])):
                    tk.Label(input_f, text=f"{lbl} ({hint})", anchor="e").grid(
                        row=r, column=0, sticky="e", padx=(0, 4), pady=1)
                    var = tk.StringVar(value=str(getattr(ld, attr)))
                    tk.Entry(input_f, textvariable=var, width=12).grid(
                        row=r, column=1, sticky="w", pady=1)
                    var.trace_add("write", _refresh_solved)
                    _bal_vars[attr] = var

            _bal_mode_var.trace_add("write", _rebuild_bal_inputs)
            _bal_lag_var.trace_add("write", _refresh_solved)
            _rebuild_bal_inputs()

        def _build_individual_fields(parent):
            _ph_vars.clear(); _ph_lag_vars.clear(); _ph_mode_vars.clear()
            for w in parent.winfo_children():
                w.destroy()

            nb = ttk.Notebook(parent)
            nb.pack(fill="both", expand=True)

            for ph in ("A", "B", "C"):
                suffix = PH_SUFFIX[ph]
                tab = tk.Frame(nb)
                nb.add(tab, text=f" Phase {ph} ")
                tab.columnconfigure(1, weight=1)

                ph_mode_var = tk.StringVar(value=getattr(ld, "spec_mode" + suffix))
                _ph_mode_vars[ph] = ph_mode_var
                tk.Label(tab, text="Spec mode", anchor="e").grid(
                    row=0, column=0, sticky="e", padx=(0, 4), pady=2)
                ttk.Combobox(tab, textvariable=ph_mode_var, values=MODES,
                             state="readonly", width=12).grid(row=0, column=1, sticky="w")

                lag_var = tk.StringVar(
                    value="Lagging (ind)" if getattr(ld, "lagging" + suffix)
                    else "Leading (cap)")
                _ph_lag_vars[ph] = lag_var
                tk.Label(tab, text="Q sign", anchor="e").grid(
                    row=1, column=0, sticky="e", padx=(0, 4), pady=2)
                ttk.Combobox(tab, textvariable=lag_var,
                             values=["Lagging (ind)", "Leading (cap)"],
                             state="readonly", width=14).grid(row=1, column=1, sticky="w")
                lag_var.trace_add("write", _refresh_solved)

                input_f = tk.Frame(tab)
                input_f.grid(row=2, column=0, columnspan=2, sticky="ew")
                input_f.columnconfigure(1, weight=1)

                def _rebuild_ph_inputs(*_, _ph=ph, _suffix=suffix, _frm=input_f,
                                       _mvar=ph_mode_var):
                    for w in _frm.winfo_children():
                        w.destroy()
                    for key in list(_ph_vars.keys()):
                        if key[0] == _ph:
                            del _ph_vars[key]
                    for r, (lbl, base_attr, hint) in enumerate(
                            MODE_FIELDS.get(_mvar.get(), [])):
                        tk.Label(_frm, text=f"{lbl} ({hint})", anchor="e").grid(
                            row=r, column=0, sticky="e", padx=(0, 4), pady=1)
                        full_attr = base_attr + _suffix
                        var = tk.StringVar(value=str(getattr(ld, full_attr)))
                        tk.Entry(_frm, textvariable=var, width=12).grid(
                            row=r, column=1, sticky="w", pady=1)
                        var.trace_add("write", _refresh_solved)
                        _ph_vars[(_ph, base_attr)] = var

                ph_mode_var.trace_add("write", _rebuild_ph_inputs)
                _rebuild_ph_inputs()

        def _rebuild_spec_area(*_):
            for w in _spec_frame.winfo_children():
                w.destroy()
            if v_phase.get() == "balanced":
                _build_balanced_fields(_spec_frame)
            else:
                _build_individual_fields(_spec_frame)
            _refresh_solved()

        v_phase.trace_add("write", _rebuild_spec_area)
        _rebuild_spec_area()

        def apply():
            ld.name = v_name.get().strip() or ld.name
            _apply_to_load(ld)
            _refresh_solved()
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

    def show_ct(self, ct: DiagramCT) -> None:
        if ct is None:
            return
        self._current = ct
        self._populate_mr(ct)
        self._populate_predictions(ct)
        self._clear()

        RELAY_CLASSES   = ["C50", "C100", "C200", "C400", "C800"]
        METER_CLASSES   = ["0.1", "0.3", "0.6", "1.2"]
        PRI_CONFIGS     = ["Series", "Parallel", "Window (core-balance)"]
        SEC_CONFIGS     = ["Wye", "Delta", "Open-Delta", "Zero-Sequence"]

        tk.Label(self._body, text="Current Transformer",
                 font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        # ── Identity ──────────────────────────────────────────────────────
        v_name = tk.StringVar(value=ct.name)
        self._row("ID",   tk.StringVar(value=ct.id), readonly=True, start_row=1)
        self._row("Name", v_name, start_row=2)

        # ── Ratio ─────────────────────────────────────────────────────────
        tk.Label(self._body, text="Ratio", font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        v_pri = tk.StringVar(value=str(ct.ratio_primary))
        v_sec = tk.StringVar(value=str(ct.ratio_secondary))
        self._row("Primary A",   v_pri, start_row=4)
        self._row("Secondary A", v_sec, start_row=5)

        # ── Multi-tap ─────────────────────────────────────────────────────
        v_taps     = tk.StringVar(value=str(ct.num_taps))
        v_tap_list = tk.StringVar(value=ct.tap_ratios)
        self._row("# Taps",     v_taps,     start_row=6)
        self._row("Tap ratios", v_tap_list, start_row=7)

        # ── Accuracy & burden ─────────────────────────────────────────────
        tk.Label(self._body, text="Accuracy & Burden",
                 font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))

        tk.Label(self._body, text="Relay class", anchor="e").grid(
            row=9, column=0, sticky="e", padx=(0, 4))
        v_relay = tk.StringVar(value=ct.accuracy_class_relay)
        ttk.Combobox(self._body, textvariable=v_relay, values=RELAY_CLASSES,
                     state="readonly", width=8).grid(row=9, column=1, sticky="w")

        tk.Label(self._body, text="Metering class", anchor="e").grid(
            row=10, column=0, sticky="e", padx=(0, 4))
        v_meter = tk.StringVar(value=ct.accuracy_class_metering)
        ttk.Combobox(self._body, textvariable=v_meter, values=METER_CLASSES,
                     state="readonly", width=8).grid(row=10, column=1, sticky="w")

        v_burden = tk.StringVar(value=str(ct.burden_va))
        v_rf     = tk.StringVar(value=str(ct.rating_factor))
        self._row("Burden (VA)", v_burden, start_row=11)
        self._row("Rating factor", v_rf,   start_row=12)

        # ── Winding configuration ─────────────────────────────────────────
        tk.Label(self._body, text="Winding configuration",
                 font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=13, column=0, columnspan=2, sticky="w", pady=(6, 0))

        tk.Label(self._body, text="Primary", anchor="e").grid(
            row=14, column=0, sticky="e", padx=(0, 4))
        v_pri_cfg = tk.StringVar(value=ct.primary_config)
        ttk.Combobox(self._body, textvariable=v_pri_cfg, values=PRI_CONFIGS,
                     state="readonly", width=20).grid(row=14, column=1, sticky="w")

        tk.Label(self._body, text="Secondary", anchor="e").grid(
            row=15, column=0, sticky="e", padx=(0, 4))
        v_sec_cfg = tk.StringVar(value=ct.secondary_config)
        ttk.Combobox(self._body, textvariable=v_sec_cfg, values=SEC_CONFIGS,
                     state="readonly", width=20).grid(row=15, column=1, sticky="w")

        # ── Polarity ──────────────────────────────────────────────────────
        tk.Label(self._body, text="Polarity", font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=16, column=0, columnspan=2, sticky="w", pady=(6, 0))
        v_polarity = tk.BooleanVar(value=ct.polarity_standard)
        tk.Checkbutton(self._body, text="Show dot (standard IEEE/IEC)",
                       variable=v_polarity).grid(
            row=17, column=0, columnspan=2, sticky="w")
        v_flipped = tk.BooleanVar(value=ct.polarity_flipped)
        tk.Checkbutton(self._body, text="Flip — secondary exits opposite end  (P key)",
                       variable=v_flipped).grid(
            row=18, column=0, columnspan=2, sticky="w")

        next_row, dev_vars = self._device_fields(ct, 19)

        def apply():
            ct.name  = v_name.get().strip() or ct.name
            try: ct.ratio_primary   = int(v_pri.get())
            except ValueError: pass
            try: ct.ratio_secondary = int(v_sec.get())
            except ValueError: pass
            try: ct.num_taps        = int(v_taps.get())
            except ValueError: pass
            ct.tap_ratios              = v_tap_list.get().strip()
            ct.accuracy_class_relay    = v_relay.get()
            ct.accuracy_class_metering = v_meter.get()
            try: ct.burden_va      = float(v_burden.get())
            except ValueError: pass
            try: ct.rating_factor  = float(v_rf.get())
            except ValueError: pass
            ct.primary_config   = v_pri_cfg.get()
            ct.secondary_config = v_sec_cfg.get()
            ct.polarity_standard = v_polarity.get()
            ct.polarity_flipped  = v_flipped.get()
            for attr, var in dev_vars.items():
                setattr(ct, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=next_row, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

    def show_vt(self, vt: DiagramVT) -> None:
        if vt is None:
            return
        self._current = vt
        self._populate_mr(vt)
        self._populate_predictions(vt)
        self._clear()
        tk.Label(self._body, text="Voltage Transformer / CVT",
                 font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        v_name     = tk.StringVar(value=vt.name)
        v_type     = tk.StringVar(value=vt.vt_type)
        v_pri      = tk.StringVar(value=str(vt.ratio_primary))
        v_sec      = tk.StringVar(value=str(vt.ratio_secondary))
        v_acc      = tk.StringVar(value=vt.accuracy_class)
        v_burden   = tk.StringVar(value=str(vt.burden_va))
        v_num_sec  = tk.StringVar(value=str(vt.num_secondaries))

        self._row("ID",   tk.StringVar(value=vt.id), readonly=True, start_row=1)
        self._row("Name", v_name,  start_row=2)

        # Type dropdown
        row = 3
        tk.Label(self._body, text="Type").grid(row=row, column=0, sticky="w", pady=2)
        tk.OptionMenu(self._body, v_type, "VT", "CVT").grid(
            row=row, column=1, sticky="ew", pady=2)

        # Voltage ratio
        row = 4
        tk.Label(self._body, text="Ratio", font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8,2))
        self._row("Primary (V)",   v_pri,  start_row=5)
        self._row("Secondary (V)", v_sec,  start_row=6)

        # Protection / metering data
        row = 7
        tk.Label(self._body, text="Nameplate", font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8,2))
        self._row("Accuracy Class", v_acc,    start_row=8)
        self._row("Burden (VA)",    v_burden,  start_row=9)

        row = 10
        tk.Label(self._body, text="# Secondaries").grid(row=row, column=0, sticky="w", pady=2)
        tk.OptionMenu(self._body, v_num_sec, "1", "2").grid(
            row=row, column=1, sticky="ew", pady=2)

        next_row, dev_vars = self._device_fields(vt, 12)

        def apply():
            vt.name  = v_name.get().strip() or vt.name
            vt.vt_type = v_type.get()
            try:
                vt.ratio_primary   = float(v_pri.get())
                vt.ratio_secondary = float(v_sec.get())
            except ValueError:
                pass
            vt.accuracy_class  = v_acc.get().strip() or vt.accuracy_class
            try:
                vt.burden_va      = float(v_burden.get())
                vt.num_secondaries = int(v_num_sec.get())
            except ValueError:
                pass
            for attr, var in dev_vars.items():
                setattr(vt, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=next_row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_cttb(self, cttb: DiagramCTTB) -> None:
        if cttb is None:
            return
        self._current = cttb
        self._populate_mr(cttb)
        self._populate_predictions(cttb)
        self._clear()
        tk.Label(self._body, text="CT Test Block (CTTB)",
                 font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        v_name    = tk.StringVar(value=cttb.name)
        v_mode    = tk.StringVar(value=cttb.mode)
        v_circuits = tk.StringVar(value=str(cttb.num_circuits))

        self._row("ID",   tk.StringVar(value=cttb.id),     readonly=True, start_row=1)
        self._row("Name", v_name,                                          start_row=2)
        self._row("Source", tk.StringVar(value=f"{cttb.source_type}:{cttb.source_id}"), readonly=True, start_row=3)

        tk.Label(self._body, text="Mode").grid(row=4, column=0, sticky="w", pady=2)
        tk.OptionMenu(self._body, v_mode, "Pass", "Sum", "Subtract").grid(
            row=4, column=1, sticky="ew", pady=2)

        self._row("# CT Circuits", v_circuits, start_row=5)

        next_row, dev_vars = self._device_fields(cttb, 6)

        def apply():
            cttb.name         = v_name.get().strip() or cttb.name
            cttb.mode         = v_mode.get()
            try:
                cttb.num_circuits = int(v_circuits.get())
            except ValueError:
                pass
            for attr, var in dev_vars.items():
                setattr(cttb, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=next_row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_testblock(self, tb: DiagramTestBlock) -> None:
        if tb is None:
            return
        self._current = tb
        self._populate_mr(tb)
        self._populate_predictions(tb)
        self._clear()
        tk.Label(self._body, text="FT / ISO Test Block",
                 font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        v_name  = tk.StringVar(value=tb.name)
        v_type  = tk.StringVar(value=tb.block_type)
        v_fused = tk.BooleanVar(value=tb.fused)

        self._row("ID",  tk.StringVar(value=tb.id),    readonly=True, start_row=1)
        self._row("Name", v_name,                                       start_row=2)
        self._row("Source", tk.StringVar(value=f"{tb.source_type}:{tb.source_id}"), readonly=True, start_row=3)

        tk.Label(self._body, text="Type").grid(row=4, column=0, sticky="w", pady=2)
        tk.OptionMenu(self._body, v_type, "FT", "ISO").grid(
            row=4, column=1, sticky="ew", pady=2)

        tk.Checkbutton(self._body, text="Fused", variable=v_fused).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=2)

        next_row, dev_vars = self._device_fields(tb, 6)

        def apply():
            tb.name       = v_name.get().strip() or tb.name
            tb.block_type = v_type.get()
            tb.fused      = v_fused.get()
            for attr, var in dev_vars.items():
                setattr(tb, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=next_row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_breaker(self, br: DiagramBreaker) -> None:
        if br is None:
            return
        self._current = br
        self._populate_mr(br)
        self._populate_predictions(br)
        self._clear()
        tk.Label(self._body, text="Circuit Breaker", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name   = tk.StringVar(value=br.name)
        v_closed = tk.BooleanVar(value=br.closed)
        self._row("ID",         tk.StringVar(value=br.id),           readonly=True, start_row=1)
        self._row("Name",       v_name,                                              start_row=2)
        self._row("Connection", tk.StringVar(value=br.connection_id), readonly=True, start_row=3)
        self._row("Position",   tk.StringVar(value=f"{br.t * 100:.1f}%"), readonly=True, start_row=4)
        tk.Checkbutton(self._body, text="Closed", variable=v_closed).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=2)

        next_row, dev_vars = self._device_fields(br, 6)

        def apply():
            br.name   = v_name.get().strip() or br.name
            br.closed = v_closed.get()
            for attr, var in dev_vars.items():
                setattr(br, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=next_row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_disconnect(self, dc: DiagramDisconnect) -> None:
        if dc is None:
            return
        self._current = dc
        self._populate_mr(dc)
        self._populate_predictions(dc)
        self._clear()
        tk.Label(self._body, text="Disconnect Switch", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name   = tk.StringVar(value=dc.name)
        v_closed = tk.BooleanVar(value=dc.closed)
        self._row("ID",         tk.StringVar(value=dc.id),           readonly=True, start_row=1)
        self._row("Name",       v_name,                                              start_row=2)
        self._row("Connection", tk.StringVar(value=dc.connection_id), readonly=True, start_row=3)
        self._row("Position",   tk.StringVar(value=f"{dc.t * 100:.1f}%"), readonly=True, start_row=4)
        tk.Checkbutton(self._body, text="Closed", variable=v_closed).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=2)

        next_row, dev_vars = self._device_fields(dc, 6)

        def apply():
            dc.name   = v_name.get().strip() or dc.name
            dc.closed = v_closed.get()
            for attr, var in dev_vars.items():
                setattr(dc, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=next_row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_relay(self, relay: "DiagramRelay") -> None:
        if relay is None:
            return
        self._current = relay
        self._populate_mr(relay)
        self._populate_predictions(relay)
        self._clear()
        row = _RowCounter()

        tk.Label(self._body, text="Protection Relay",
                 font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=row.next(), column=0, columnspan=2,
                                   sticky="w", pady=(0, 4))

        v_name = tk.StringVar(value=relay.name)
        v_func = tk.StringVar(value=relay.function_code)
        self._row("ID",             tk.StringVar(value=relay.id), readonly=True, start_row=row.next())
        self._row("Name",           v_name,  start_row=row.next())
        self._row("Function code",  v_func,  start_row=row.next())

        # ── Windings list ────────────────────────────────────────────────
        ttk.Separator(self._body, orient="horizontal").grid(
            row=row.next(), column=0, columnspan=2, sticky="ew", pady=4)
        tk.Label(self._body, text="Windings", font=("TkDefaultFont", 9, "bold"),
                 fg="#333").grid(row=row.next(), column=0, columnspan=2, sticky="w")

        winding_vars = []
        winding_frame = tk.Frame(self._body)
        winding_frame.grid(row=row.next(), column=0, columnspan=2, sticky="ew")

        def _refresh_windings():
            for w in winding_frame.winfo_children():
                w.destroy()
            winding_vars.clear()
            for wi, label in enumerate(relay.windings):
                v = tk.StringVar(value=label)
                winding_vars.append(v)
                tk.Entry(winding_frame, textvariable=v, width=8).grid(
                    row=wi, column=0, padx=(0, 2), pady=1)
                tk.Button(winding_frame, text="✕", width=2, font=("TkDefaultFont", 7),
                          command=lambda i=wi: _remove_winding(i)).grid(row=wi, column=1)

        def _add_winding():
            relay.windings.append(f"W{len(relay.windings)+1}")
            _refresh_windings()

        def _remove_winding(i):
            if len(relay.windings) > 1:
                relay.windings.pop(i)
                _refresh_windings()

        _refresh_windings()

        tk.Button(self._body, text="+ Add winding", command=_add_winding).grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ── Flags ────────────────────────────────────────────────────────
        ttk.Separator(self._body, orient="horizontal").grid(
            row=row.next(), column=0, columnspan=2, sticky="ew", pady=4)
        v_mirrored = tk.BooleanVar(value=relay.mirrored_bit)
        tk.Checkbutton(self._body, text="Mirrored bit",
                       variable=v_mirrored).grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=2)

        dev_start = row.next()
        dev_next, dev_vars = self._device_fields(relay, dev_start)

        def apply():
            relay.name          = v_name.get().strip() or relay.name
            relay.function_code = v_func.get().strip() or relay.function_code
            relay.mirrored_bit  = v_mirrored.get()
            for wi, v in enumerate(winding_vars):
                lbl = v.get().strip()
                if lbl and wi < len(relay.windings):
                    relay.windings[wi] = lbl
            for attr, var in dev_vars.items():
                setattr(relay, attr, var.get())
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=dev_next, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def show_relay_wire(self, rw: "DiagramRelayWire") -> None:
        if rw is None:
            return
        self._current = rw
        self._populate_mr(rw)
        self._populate_predictions(rw)
        self._clear()
        row = _RowCounter()
        tk.Label(self._body, text="Relay Wire",
                 font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=row.next(), column=0, columnspan=2,
                                   sticky="w", pady=(0, 6))
        self._row("ID",          tk.StringVar(value=rw.id),          readonly=True, start_row=row.next())
        self._row("Source",      tk.StringVar(value=rw.source_id),   readonly=True, start_row=row.next())
        self._row("Source type", tk.StringVar(value=rw.source_type), readonly=True, start_row=row.next())
        self._row("Relay",       tk.StringVar(value=rw.relay_id),    readonly=True, start_row=row.next())

        r = row.next()
        v_wind = tk.StringVar(value=str(rw.winding))
        tk.Label(self._body, text="Winding", anchor="w").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Combobox(self._body, textvariable=v_wind, values=["1", "2"],
                     state="readonly", width=5).grid(row=r, column=1, sticky="w", pady=2)
        self._row("Waypoints", tk.StringVar(value=str(len(rw.waypoints))), readonly=True,
                  start_row=row.next())

        def apply():
            try:
                rw.winding = int(v_wind.get())
            except ValueError:
                pass
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=row.next(), column=0, columnspan=2, sticky="w", pady=(12, 0))

    def clear(self) -> None:
        self._current = None
        self._show_empty()
        self._show_mr_na()

    def _device_fields(self, obj, start_row: int):
        """Add extended location/drawing fields. Returns (next_row, vars_dict)."""
        row = start_row
        fields = []
        if hasattr(obj, "location"):    fields.append(("Location",     "location"))
        if hasattr(obj, "panel"):       fields.append(("Panel",        "panel"))
        if hasattr(obj, "drawing_cell") and getattr(obj, "drawing_cell", None) is not None:
            fields.append(("Drawing cell", "drawing_cell"))
        if hasattr(obj, "notes"):       fields.append(("Notes",        "notes"))
        vars_: dict = {}
        if fields:
            ttk.Separator(self._body, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="ew", pady=4)
            row += 1
            tk.Label(self._body, text="Location & Drawing",
                     font=("TkDefaultFont", 9, "bold"), fg="#333").grid(
                row=row, column=0, columnspan=2, sticky="w")
            row += 1
        for label, attr in fields:
            v = tk.StringVar(value=getattr(obj, attr, ""))
            vars_[attr] = v
            self._row(label, v, start_row=row)
            row += 1
        if hasattr(obj, "device_drawings"):
            tk.Button(self._body, text="Drawings…",
                      command=lambda: DrawingPickerDialog(self, obj, getattr(self, "_diagram", None), self._on_change)
                      ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
            row += 1
            count = len(getattr(obj, "device_drawings", []))
            tk.Label(self._body, text=f"{count} drawing(s) attached",
                     fg="#666666", font=("TkDefaultFont", 8)).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
        return row, vars_

    # ── Internal ──────────────────────────────────────────────────────────

    def _clear(self) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        self._body.columnconfigure(0, minsize=120)
        self._body.columnconfigure(1, weight=1)

    def _show_empty(self) -> None:
        self._clear()
        tk.Label(self._body, text="Nothing selected.",
                 fg="#888888", font=("TkDefaultFont", 9)).pack(anchor="w")

    # ── Meter readings helpers ────────────────────────────────────────────

    def _clear_mr(self) -> None:
        for w in self._mr_body.winfo_children():
            w.destroy()

    def _show_mr_na(self) -> None:
        self._clear_mr()
        tk.Label(self._mr_body,
                 text="Meter readings are not\navailable for this device type.",
                 fg="#888888", font=("TkDefaultFont", 9), justify="center"
                 ).pack(expand=True, pady=20)

    def _populate_mr(self, device) -> None:
        """Dispatch to the right MR builder based on device type."""
        if isinstance(device, DiagramCTTB):
            self._build_mr_cttb(device)
        elif isinstance(device, DiagramRelay):
            self._build_mr_relay(device)
        elif isinstance(device, DiagramTestBlock):
            self._build_mr_testblock(device)
        else:
            self._show_mr_na()

    _PHASES = (("A", 0.0), ("B", 240.0), ("C", 120.0))

    def _build_mr_channels(self, channels: list, unit: str, save_fn) -> None:
        """Populate _mr_body with one LabelFrame per channel, 3 phases each.

        channels: list of dicts with keys pred_mag_a/b/c, pred_ang_a/b/c,
                  meas_mag_a/b/c, meas_ang_a/b/c, plus 'label'.
        unit: 'A' or 'V'
        save_fn: callable(list_of_updated_dicts)
        """
        self._clear_mr()
        body = self._mr_body
        body.columnconfigure(0, weight=1)

        ch_vars: list[dict] = []

        for i, ch in enumerate(channels):
            lf = tk.LabelFrame(body, text=ch["label"],
                               font=("TkDefaultFont", 9, "bold"), padx=4, pady=2)
            lf.grid(row=i, column=0, sticky="ew", padx=4, pady=(4, 0))
            # cols: 0=phase, 1=row-label, 2=mag-entry, 3=unit, 4=ang-entry, 5=°
            lf.columnconfigure(2, weight=1)
            lf.columnconfigure(4, weight=1)

            phase_vars: dict = {}   # ph -> {pred_mag, pred_ang, meas_mag, meas_ang}
            grid_row = 0

            for ph, _default_ang in self._PHASES:
                sfx = ph.lower()
                v_pm = tk.StringVar(value=str(ch.get(f"pred_mag_{sfx}", 0.0)))
                v_pa = tk.StringVar(value=str(ch.get(f"pred_ang_{sfx}", 0.0)))
                v_mm = tk.StringVar(value=str(ch.get(f"meas_mag_{sfx}", 0.0)))
                v_ma = tk.StringVar(value=str(ch.get(f"meas_ang_{sfx}", 0.0)))
                v_dv = tk.StringVar(value="—")
                phase_vars[ph] = {"pred_mag": v_pm, "pred_ang": v_pa,
                                  "meas_mag": v_mm, "meas_ang": v_ma}

                # Phase header label
                tk.Label(lf, text=f"Ph {ph}", font=("TkDefaultFont", 9, "bold"),
                         fg="#333333").grid(row=grid_row, column=0, rowspan=2,
                                           sticky="nw", padx=(0, 4))

                # Pred row
                tk.Label(lf, text="Pred", fg="#666666",
                         font=("TkDefaultFont", 8)).grid(
                    row=grid_row, column=1, sticky="e", padx=(0, 2))
                tk.Entry(lf, textvariable=v_pm, width=6).grid(
                    row=grid_row, column=2, sticky="ew", padx=1)
                tk.Label(lf, text=unit, fg="#666666",
                         font=("TkDefaultFont", 8)).grid(
                    row=grid_row, column=3, sticky="w")
                tk.Entry(lf, textvariable=v_pa, width=6).grid(
                    row=grid_row, column=4, sticky="ew", padx=1)
                tk.Label(lf, text="°", fg="#666666",
                         font=("TkDefaultFont", 8)).grid(
                    row=grid_row, column=5, sticky="w")
                grid_row += 1

                # Meas row
                tk.Label(lf, text="Meas", fg="#333333",
                         font=("TkDefaultFont", 9, "bold")).grid(
                    row=grid_row, column=1, sticky="e", padx=(0, 2))
                tk.Entry(lf, textvariable=v_mm, width=6).grid(
                    row=grid_row, column=2, sticky="ew", padx=1)
                tk.Label(lf, text=unit, fg="#333333",
                         font=("TkDefaultFont", 8)).grid(
                    row=grid_row, column=3, sticky="w")
                tk.Entry(lf, textvariable=v_ma, width=6).grid(
                    row=grid_row, column=4, sticky="ew", padx=1)
                tk.Label(lf, text="°", fg="#333333",
                         font=("TkDefaultFont", 8)).grid(
                    row=grid_row, column=5, sticky="w")
                grid_row += 1

                # Delta row
                tk.Label(lf, textvariable=v_dv, fg="#0044AA",
                         font=("TkFixedFont", 7), justify="left").grid(
                    row=grid_row, column=1, columnspan=5, sticky="w")
                grid_row += 1

                def _upd(*_, _pm=v_pm, _pa=v_pa, _mm=v_mm, _ma=v_ma,
                         _dv=v_dv, _u=unit):
                    try:
                        pm = float(_pm.get()); pa = float(_pa.get())
                        mm = float(_mm.get()); ma = float(_ma.get())
                        d_mag = mm - pm
                        pct = f"({abs(d_mag)/pm*100:.1f}%)" if pm != 0 else ""
                        d_ang = (ma - pa + 180) % 360 - 180
                        _dv.set(f"Δ{d_mag:+.3f}{_u} {pct}  Δang{d_ang:+.1f}°")
                    except ValueError:
                        _dv.set("—")

                for v in (v_pm, v_pa, v_mm, v_ma):
                    v.trace_add("write", _upd)
                _upd()

                # Thin separator between phases (not after last)
                if ph != "C":
                    ttk.Separator(lf, orient="horizontal").grid(
                        row=grid_row, column=0, columnspan=6,
                        sticky="ew", pady=(2, 2))
                    grid_row += 1

            ch_vars.append(phase_vars)

        def _save():
            data = []
            for pv in ch_vars:
                pt: dict = {}
                for ph in ("A", "B", "C"):
                    sfx = ph.lower()
                    vs = pv[ph]
                    try:
                        pt[f"pred_mag_{sfx}"] = float(vs["pred_mag"].get())
                        pt[f"pred_ang_{sfx}"] = float(vs["pred_ang"].get())
                        pt[f"meas_mag_{sfx}"] = float(vs["meas_mag"].get())
                        pt[f"meas_ang_{sfx}"] = float(vs["meas_ang"].get())
                    except ValueError:
                        pt[f"pred_mag_{sfx}"] = 0.0
                        pt[f"pred_ang_{sfx}"] = 0.0
                        pt[f"meas_mag_{sfx}"] = 0.0
                        pt[f"meas_ang_{sfx}"] = 0.0
                data.append(pt)
            save_fn(data)
            if self._on_change:
                self._on_change()

        tk.Button(body, text="Save Readings", command=_save).grid(
            row=len(channels), column=0, sticky="w", padx=4, pady=(8, 4))

    def _blank_pt(self) -> dict:
        return {
            "pred_mag_a": 0.0, "pred_ang_a": 0.0,
            "meas_mag_a": 0.0, "meas_ang_a": 0.0,
            "pred_mag_b": 0.0, "pred_ang_b": 0.0,
            "meas_mag_b": 0.0, "meas_ang_b": 0.0,
            "pred_mag_c": 0.0, "pred_ang_c": 0.0,
            "meas_mag_c": 0.0, "meas_ang_c": 0.0,
        }

    def _build_mr_cttb(self, cttb: DiagramCTTB) -> None:
        n = max(1, cttb.num_circuits)
        while len(cttb.meas_points) < n:
            cttb.meas_points.append(self._blank_pt())
        channels = [{"label": f"Circuit {i+1}", **cttb.meas_points[i]} for i in range(n)]
        self._build_mr_channels(channels, "A", lambda data: setattr(cttb, "meas_points", data))

    def _build_mr_relay(self, relay: DiagramRelay) -> None:
        n = max(1, len(relay.windings))
        while len(relay.meas_points) < n:
            relay.meas_points.append(self._blank_pt())
        channels = [{"label": relay.windings[i], **relay.meas_points[i]} for i in range(n)]
        self._build_mr_channels(channels, "A", lambda data: setattr(relay, "meas_points", data))

    def _build_mr_testblock(self, tb: DiagramTestBlock) -> None:
        while len(tb.meas_points) < 1:
            tb.meas_points.append(self._blank_pt())
        channels = [{"label": "Channel 1", **tb.meas_points[0]}]
        self._build_mr_channels(channels, "V", lambda data: setattr(tb, "meas_points", data))

    # ── Predictions helpers ───────────────────────────────────────────────

    def _clear_pred(self) -> None:
        for w in self._pred_body.winfo_children():
            w.destroy()

    def _show_pred_pending(self, device) -> None:
        self._clear_pred()
        supported = isinstance(device, (DiagramBus, DiagramConnection,
                                        DiagramTransformer, DiagramSource, DiagramLoad,
                                        DiagramCT, DiagramVT, DiagramCTTB,
                                        DiagramTestBlock, DiagramRelay))
        msg = ("Run power flow to\nsee predictions."
               if supported else
               "Predictions not available\nfor this device type.")
        tk.Label(self._pred_body, text=msg, fg="#888888",
                 font=("TkDefaultFont", 9), justify="center"
                 ).pack(expand=True, pady=20)

    def _populate_predictions(self, device) -> None:
        pf = getattr(device, "pf_solved", None)
        if pf is None:
            self._show_pred_pending(device)
        else:
            self._build_predictions(pf)

    def _build_predictions(self, pf: dict) -> None:
        """Render the unified predictions table + phasor canvas(es).

        Row order for every device type:  V LN · ∠V · V LL · I · ∠I · S · Q · P · PF
        Columns: label | A | B | C | N   (N = neutral / 3-phase total depending on row)
        Missing quantities show '—'.
        """
        self._clear_pred()
        body = self._pred_body
        body.columnconfigure(0, weight=0)
        for c in range(1, 5):
            body.columnconfigure(c, weight=1)

        dtype = pf.get("type", "")

        # ── Column headers ────────────────────────────────────────────
        for col, txt in enumerate(("", "A", "B", "C", "N")):
            tk.Label(body, text=txt, font=("TkDefaultFont", 9, "bold"),
                     fg="#333333", anchor="center").grid(
                row=0, column=col, sticky="ew", padx=1, pady=(4, 2))
        ttk.Separator(body, orient="horizontal").grid(
            row=1, column=0, columnspan=5, sticky="ew")

        r = 2

        def _val(v, fmt):
            if v is None or v == "—":
                return "—"
            if isinstance(v, str):
                return v
            try:
                return fmt.format(v)
            except Exception:
                return "—"

        def data_row(label, a, b, c, n, fmt="{:.4g}"):
            nonlocal r
            tk.Label(body, text=label, font=("TkDefaultFont", 8),
                     fg="#555555", anchor="w").grid(
                row=r, column=0, sticky="w", padx=(4, 6), pady=1)
            for col, v in enumerate([a, b, c, n], start=1):
                tk.Label(body, text=_val(v, fmt), font=("TkFixedFont", 8),
                         fg="#003388", anchor="center").grid(
                    row=r, column=col, sticky="ew", padx=1, pady=1)
            r += 1

        def note_row(text: str) -> None:
            nonlocal r
            tk.Label(body, text=text, font=("TkDefaultFont", 7),
                     fg="#888888", anchor="w").grid(
                row=r, column=0, columnspan=5, sticky="w", padx=4, pady=(0, 2))
            r += 1

        def ang_str(deg):
            return None if deg is None else f"{deg:.1f}°"

        def _render_block(v_a, v_b, v_c, i_a, i_b, i_c,
                          p_kw, q_kvar, s_kva, pf_val,
                          v_unit: str, v_fmt: str) -> None:
            """Render the 9-row data block into body starting at current r."""

            # ── Voltage ──────────────────────────────────────────────
            if v_a is not None:
                vln_a = abs(v_a)
                vln_b = abs(v_b) if v_b is not None else None
                vln_c = abs(v_c) if v_c is not None else None
                data_row(f"V LN ({v_unit})", vln_a, vln_b, vln_c, 0.0, fmt=v_fmt)
                ang_va = math.degrees(cmath.phase(v_a))
                ang_vb = math.degrees(cmath.phase(v_b)) if v_b is not None else None
                ang_vc = math.degrees(cmath.phase(v_c)) if v_c is not None else None
                data_row("∠V (°)",
                         ang_str(ang_va), ang_str(ang_vb), ang_str(ang_vc), "—")
                if v_b is not None and v_c is not None:
                    vll_ab = abs(v_a - v_b)
                    vll_bc = abs(v_b - v_c)
                    vll_ca = abs(v_c - v_a)
                    data_row(f"V LL ({v_unit})", vll_ab, vll_bc, vll_ca, "—", fmt=v_fmt)
                else:
                    data_row(f"V LL ({v_unit})", "—", "—", "—", "—")
            else:
                data_row(f"V LN ({v_unit})", "—", "—", "—", "—")
                data_row("∠V (°)",           "—", "—", "—", "—")
                data_row(f"V LL ({v_unit})", "—", "—", "—", "—")

            # ── Current ──────────────────────────────────────────────
            if i_a is not None:
                ima = abs(i_a)
                imb = abs(i_b) if i_b is not None else None
                imc = abs(i_c) if i_c is not None else None
                imn = abs(i_a + i_b + i_c) if (i_b is not None and i_c is not None) else None
                data_row("I (A)", ima, imb, imc, imn, fmt="{:.3f}")
                ang_ia = math.degrees(cmath.phase(i_a))
                ang_ib = math.degrees(cmath.phase(i_b)) if i_b is not None else None
                ang_ic = math.degrees(cmath.phase(i_c)) if i_c is not None else None
                data_row("∠I (°)",
                         ang_str(ang_ia), ang_str(ang_ib), ang_str(ang_ic), "—")
            else:
                data_row("I (A)",   "—", "—", "—", "—")
                data_row("∠I (°)", "—", "—", "—", "—")

            # ── Power ────────────────────────────────────────────────
            if s_kva is not None:
                data_row("S (kVA)",  s_kva/3, s_kva/3, s_kva/3, s_kva,  fmt="{:.2f}")
            else:
                data_row("S (kVA)",  "—", "—", "—", "—")
            if q_kvar is not None:
                data_row("Q (kVAR)", q_kvar/3, q_kvar/3, q_kvar/3, q_kvar, fmt="{:.2f}")
            else:
                data_row("Q (kVAR)", "—", "—", "—", "—")
            if p_kw is not None:
                data_row("P (kW)",   p_kw/3, p_kw/3, p_kw/3, p_kw,     fmt="{:.2f}")
            else:
                data_row("P (kW)",   "—", "—", "—", "—")
            if pf_val is not None:
                data_row("PF",       pf_val, pf_val, pf_val, pf_val,    fmt="{:.3f}")
            else:
                data_row("PF",       "—", "—", "—", "—")

        # ── Relay: per-winding sections ───────────────────────────────
        if dtype == "relay":
            windings = pf.get("windings", [])
            i_ph_list: list = []   # (complex, colour, label) for first I winding
            v_ph_list: list = []   # (complex, colour, label) for first V winding
            i_ph_label = v_ph_label = ""

            for wd in windings:
                lbl = wd.get("label", "W?")
                # section divider
                ttk.Separator(body, orient="horizontal").grid(
                    row=r, column=0, columnspan=5, sticky="ew", pady=(4, 0))
                r += 1
                tk.Label(body, text=lbl, font=("TkDefaultFont", 9, "bold"),
                         fg="#333333", anchor="w").grid(
                    row=r, column=0, columnspan=5, sticky="w", padx=4, pady=(2, 2))
                r += 1
                w_va = wd.get("v_a"); w_vb = wd.get("v_b"); w_vc = wd.get("v_c")
                w_ia = wd.get("i_a"); w_ib = wd.get("i_b"); w_ic = wd.get("i_c")
                _render_block(w_va, w_vb, w_vc, w_ia, w_ib, w_ic,
                              None, None, None, None, "V", "{:.2f}")
                # Collect phasors from first populated winding
                if not i_ph_list and w_ia is not None:
                    i_ph_list = [(w_ia, "#CC2200", f"{lbl}-A"),
                                 (w_ib, "#009900", f"{lbl}-B"),
                                 (w_ic, "#0055CC", f"{lbl}-C")]
                    i_ph_label = f"Current – {lbl} (A)"
                if not v_ph_list and w_va is not None:
                    v_ph_list = [(w_va, "#CC2200", f"{lbl}-A"),
                                 (w_vb, "#009900", f"{lbl}-B"),
                                 (w_vc, "#0055CC", f"{lbl}-C")]
                    v_ph_label = f"Voltage – {lbl} (V)"

            # Phasors
            ttk.Separator(body, orient="horizontal").grid(
                row=r, column=0, columnspan=5, sticky="ew", pady=(8, 4))
            r += 1
            for ph_list, ph_lbl in ((i_ph_list, i_ph_label), (v_ph_list, v_ph_label)):
                if ph_list:
                    tk.Label(body, text=ph_lbl, font=("TkDefaultFont", 9, "bold"),
                             fg="#333333").grid(row=r, column=0, columnspan=5,
                                               sticky="w", padx=4)
                    r += 1
                    self._draw_phasors(body, r, ph_list)
                    r += 1
            return

        # ── All other device types ────────────────────────────────────
        v_a = pf.get("v_a"); v_b = pf.get("v_b"); v_c = pf.get("v_c")
        i_a = pf.get("i_a"); i_b = pf.get("i_b"); i_c = pf.get("i_c")

        # Secondary devices (VT, TestBlock) store voltage in V; primaries in kV
        if dtype in ("vt", "testblock"):
            v_unit, v_fmt = "V", "{:.2f}"
        else:
            v_unit, v_fmt = "kV", "{:.3f}"

        _render_block(v_a, v_b, v_c, i_a, i_b, i_c,
                      pf.get("p_kw"), pf.get("q_kvar"),
                      pf.get("s_kva"), pf.get("pf"),
                      v_unit, v_fmt)

        # Device-specific annotation line
        if dtype == "ct":
            note_row(f"CT ratio: {pf.get('ratio', '?')}")
        elif dtype == "vt":
            delta = pf.get("delta_primary", False)
            note_row(f"VT ratio: {pf.get('ratio', '?')}"
                     + ("  [Δ primary — V LL shown]" if delta else ""))
        elif dtype == "cttb":
            note_row(f"Mode: {pf.get('mode', '?')}")

        # ── Phasor canvas(es) ─────────────────────────────────────────
        ttk.Separator(body, orient="horizontal").grid(
            row=r, column=0, columnspan=5, sticky="ew", pady=(8, 4))
        r += 1
        phasor_sets = []
        if v_a is not None:
            phasor_sets.append(([(v_a, "#CC2200", "A"),
                                  (v_b, "#009900", "B"),
                                  (v_c, "#0055CC", "C")],
                                 f"Voltage Phasors ({v_unit})"))
        if i_a is not None:
            phasor_sets.append(([(i_a, "#CC2200", "A"),
                                  (i_b, "#009900", "B"),
                                  (i_c, "#0055CC", "C")],
                                 "Current Phasors (A)"))
        for ph_list, ph_lbl in phasor_sets:
            tk.Label(body, text=ph_lbl, font=("TkDefaultFont", 9, "bold"),
                     fg="#333333").grid(row=r, column=0, columnspan=5,
                                       sticky="w", padx=4)
            r += 1
            self._draw_phasors(body, r, ph_list)
            r += 1

    def _draw_phasors(self, parent, grid_row: int, phasors: list) -> None:
        """Draw arrow phasors on a canvas placed in parent at grid_row."""
        size = 260
        cv = tk.Canvas(parent, width=size, height=size, bg="#F8F8F8",
                       highlightthickness=1, highlightbackground="#CCCCCC")
        cv.grid(row=grid_row, column=0, columnspan=5, pady=6, padx=4)

        cx, cy = size // 2, size // 2
        radius = size // 2 - 22

        max_mag = max((abs(p) for p, _, _ in phasors), default=1.0)
        if max_mag < 1e-12:
            max_mag = 1.0
        scale = radius / max_mag

        # Reference circle + thin axes
        cv.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                       outline="#DDDDDD", dash=(3, 3))
        cv.create_line(cx, cy - radius - 4, cx, cy + radius + 4,
                       fill="#CCCCCC", width=1)
        cv.create_line(cx - radius - 4, cy, cx + radius + 4, cy,
                       fill="#CCCCCC", width=1)
        # 0° / 90° tick labels
        cv.create_text(cx + radius + 6, cy, text="0°",
                       font=("TkDefaultFont", 8), fill="#AAAAAA", anchor="w")
        cv.create_text(cx, cy - radius - 6, text="90°",
                       font=("TkDefaultFont", 8), fill="#AAAAAA", anchor="s")

        for phasor, colour, label in phasors:
            if abs(phasor) < 1e-12:
                continue
            mag = abs(phasor) * scale
            ang = cmath.phase(phasor)
            x2 = cx + mag * math.cos(ang)
            y2 = cy - mag * math.sin(ang)   # screen y is inverted
            cv.create_line(cx, cy, x2, y2, fill=colour, width=2,
                           arrow=tk.LAST, arrowshape=(10, 12, 4))
            # Label just beyond the tip
            lmag = mag + 14
            lx = cx + lmag * math.cos(ang)
            ly = cy - lmag * math.sin(ang)
            cv.create_text(lx, ly, text=label, fill=colour,
                           font=("TkDefaultFont", 9, "bold"))

    def _row(self, label: str, var: tk.Variable,
             readonly: bool = False, start_row: int = None) -> None:
        row = start_row if start_row is not None else len(self._body.winfo_children())
        tk.Label(self._body, text=label, anchor="e").grid(
            row=row, column=0, sticky="e", pady=3, padx=(4, 6)
        )
        if readonly:
            tk.Label(self._body, textvariable=var, anchor="w",
                     fg="#888888").grid(row=row, column=1, sticky="ew", pady=3)
        else:
            tk.Entry(self._body, textvariable=var).grid(
                row=row, column=1, sticky="ew", pady=3, padx=(0, 4)
            )
