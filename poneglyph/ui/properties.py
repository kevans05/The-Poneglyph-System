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
)


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

        tk.Label(self, text="Properties", font=("TkDefaultFont", 10, "bold"),
                 anchor="w").pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Separator(self).pack(fill=tk.X)

        self._body = tk.Frame(self)
        self._body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._show_empty()

    # ── Public ────────────────────────────────────────────────────────────

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
        tk.Label(self._body, text="Load (PQ)", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name = tk.StringVar(value=ld.name)
        v_p    = tk.StringVar(value=str(ld.p_mw))
        v_q    = tk.StringVar(value=str(ld.q_mvar))
        self._row("ID",       tk.StringVar(value=ld.id), readonly=True, start_row=1)
        self._row("Name",     v_name, start_row=2)
        self._row("P (MW)",   v_p,    start_row=3)
        self._row("Q (MVAr)", v_q,    start_row=4)
        bus_txt = ld.bus if ld.bus else "(not attached)"
        self._row("Bus",      tk.StringVar(value=bus_txt), readonly=True, start_row=5)

        def apply():
            ld.name = v_name.get().strip() or ld.name
            try:
                ld.p_mw   = float(v_p.get())
                ld.q_mvar = float(v_q.get())
            except ValueError:
                pass
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_ct(self, ct: DiagramCT) -> None:
        if ct is None:
            return
        self._current = ct
        self._clear()
        tk.Label(self._body, text="Current Transformer", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name  = tk.StringVar(value=ct.name)
        v_ratio = tk.StringVar(value=ct.ratio)
        self._row("ID",    tk.StringVar(value=ct.id), readonly=True, start_row=1)
        self._row("Name",  v_name,  start_row=2)
        self._row("Ratio", v_ratio, start_row=3)

        def apply():
            ct.name  = v_name.get().strip() or ct.name
            ct.ratio = v_ratio.get().strip() or ct.ratio
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def show_vt(self, vt: DiagramVT) -> None:
        if vt is None:
            return
        self._current = vt
        self._clear()
        tk.Label(self._body, text="Voltage Transformer", font=("TkDefaultFont", 9, "italic"),
                 fg="#555555").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        v_name  = tk.StringVar(value=vt.name)
        v_ratio = tk.StringVar(value=vt.ratio)
        self._row("ID",    tk.StringVar(value=vt.id), readonly=True, start_row=1)
        self._row("Name",  v_name,  start_row=2)
        self._row("Ratio", v_ratio, start_row=3)

        def apply():
            vt.name  = v_name.get().strip() or vt.name
            vt.ratio = v_ratio.get().strip() or vt.ratio
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
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

        def apply():
            br.name   = v_name.get().strip() or br.name
            br.closed = v_closed.get()
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
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

        def apply():
            dc.name   = v_name.get().strip() or dc.name
            dc.closed = v_closed.get()
            if self._on_change:
                self._on_change()

        tk.Button(self._body, text="Apply", command=apply).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def clear(self) -> None:
        self._current = None
        self._show_empty()

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
