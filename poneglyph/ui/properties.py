"""Right-side properties panel.

Shows editable fields for whatever is selected in the diagram.
Calls an on_change callback whenever the user applies an edit.
"""

from __future__ import annotations

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

        tk.Label(self, text="Properties", font=("TkDefaultFont", 10, "bold"),
                 anchor="w").pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Separator(self).pack(fill=tk.X)

        # Scrollable body
        self._canvas_frame = tk.Canvas(self, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical",
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

        self._show_empty()

    # ── Public ────────────────────────────────────────────────────────────

    def set_diagram(self, diagram) -> None:
        """Store a reference to the diagram for accessing the drawings registry."""
        self._diagram = diagram

    def show_bus(self, bus: DiagramBus) -> None:
        self._current = bus
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
        self._clear()
        tk.Label(self._body, text="Power Source (slack)", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name  = tk.StringVar(value=src.name)
        v_vpu   = tk.StringVar(value=str(src.v_pu))
        v_angle = tk.StringVar(value=str(src.angle_deg))
        self._row("ID",         tk.StringVar(value=src.id), readonly=True, start_row=1)
        self._row("Name",       v_name,  start_row=2)
        self._row("Voltage (pu)", v_vpu,  start_row=3)
        self._row("Angle (deg)", v_angle, start_row=4)
        bus_txt = src.bus if src.bus else "(not attached)"
        self._row("Bus",        tk.StringVar(value=bus_txt), readonly=True, start_row=5)

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
        tk.Label(self._body, text="Solved", font=("TkDefaultFont", 8, "bold"),
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
        tk.Label(self._body, text="Ratio", font=("TkDefaultFont", 8, "bold"),
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
                 font=("TkDefaultFont", 8, "bold"),
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
                 font=("TkDefaultFont", 8, "bold"),
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
        tk.Label(self._body, text="Polarity", font=("TkDefaultFont", 8, "bold"),
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
        tk.Label(self._body, text="Ratio", font=("TkDefaultFont", 8, "bold"),
                 fg="#333").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8,2))
        self._row("Primary (V)",   v_pri,  start_row=5)
        self._row("Secondary (V)", v_sec,  start_row=6)

        # Protection / metering data
        row = 7
        tk.Label(self._body, text="Nameplate", font=("TkDefaultFont", 8, "bold"),
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
        tk.Label(self._body, text="Windings", font=("TkDefaultFont", 8, "bold"),
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

        dev_start = row.next()
        dev_next, dev_vars = self._device_fields(relay, dev_start)

        def apply():
            relay.name          = v_name.get().strip() or relay.name
            relay.function_code = v_func.get().strip() or relay.function_code
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
                     font=("TkDefaultFont", 8, "bold"), fg="#333").grid(
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
        self._body.columnconfigure(1, weight=1)

    def _show_empty(self) -> None:
        self._clear()
        tk.Label(self._body, text="Nothing selected.",
                 fg="#888888", font=("TkDefaultFont", 9)).pack(anchor="w")

    def _row(self, label: str, var: tk.Variable,
             readonly: bool = False, start_row: int = None) -> None:
        row = start_row if start_row is not None else len(self._body.winfo_children())
        tk.Label(self._body, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", pady=2, padx=(0, 8)
        )
        if readonly:
            tk.Label(self._body, textvariable=var, anchor="w",
                     fg="#888888").grid(row=row, column=1, sticky="ew", pady=2)
        else:
            tk.Entry(self._body, textvariable=var).grid(
                row=row, column=1, sticky="ew", pady=2
            )
