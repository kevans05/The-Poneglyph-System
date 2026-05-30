"""Right-side properties panel.

Shows editable fields for whatever is selected in the diagram.
Calls an on_change callback whenever the user applies an edit.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from poneglyph.ui.diagram import DiagramBus, DiagramConnection


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

        fields: list[tuple[str, tk.Variable]] = []

        v_name = tk.StringVar(value=bus.name)
        v_kv   = tk.StringVar(value=str(bus.kv))

        self._row("ID",      tk.StringVar(value=bus.id), readonly=True)
        self._row("Name",    v_name)
        self._row("Base kV", v_kv)

        fields = [("name", v_name), ("kv", v_kv)]

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
