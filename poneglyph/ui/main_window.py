"""Main application window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from poneglyph.ui.diagram import (
    Diagram,
    TOOL_SELECT, TOOL_BUS, TOOL_TLINE,
    TOOL_FEEDER, TOOL_TRANSFORMER, TOOL_DELETE,
)
from poneglyph.ui.properties import PropertiesPanel


_TOOLS = [
    (TOOL_SELECT,      "Select",      "S"),
    (TOOL_BUS,         "Bus",         "B"),
    (TOOL_TLINE,       "T-Line",      "T"),
    (TOOL_FEEDER,      "Feeder",      "F"),
    (TOOL_TRANSFORMER, "Transformer", "X"),
    (TOOL_DELETE,      "Delete",      "D"),
]


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Poneglyph — Substation Load Test Platform")
        root.geometry("1200x750")
        root.minsize(800, 500)

        self._tool_buttons: dict[str, tk.Button] = {}

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_status()

        self._set_tool(TOOL_SELECT)

    # ── Menu ──────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_m = tk.Menu(menubar, tearoff=0)
        file_m.add_command(label="New",          accelerator="Ctrl+N", command=self._new)
        file_m.add_command(label="Open…",        accelerator="Ctrl+O")
        file_m.add_command(label="Save",         accelerator="Ctrl+S")
        file_m.add_separator()
        file_m.add_command(label="Export Report…")
        file_m.add_separator()
        file_m.add_command(label="Quit",         command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_m)

        sim_m = tk.Menu(menubar, tearoff=0)
        sim_m.add_command(label="Run Power Flow", command=self._run_power_flow)
        menubar.add_cascade(label="Simulation", menu=sim_m)

        self.root.config(menu=menubar)

    # ── Toolbar ───────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.root, bd=1, relief="raised")
        bar.pack(side=tk.TOP, fill=tk.X)

        for tool, label, key in _TOOLS:
            btn = tk.Button(
                bar, text=label, width=9,
                relief="flat", padx=4,
                command=lambda t=tool: self._set_tool(t),
            )
            btn.pack(side=tk.LEFT, padx=2, pady=2)
            self._tool_buttons[tool] = btn

        # Keyboard shortcuts
        for tool, _, key in _TOOLS:
            self.root.bind(key.lower(), lambda _e, t=tool: self._set_tool(t))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)
        tk.Button(bar, text="Run Power Flow", relief="flat", padx=6,
                  command=self._run_power_flow).pack(side=tk.LEFT, padx=2, pady=2)

    # ── Body: diagram + properties panel ──────────────────────────────────

    def _build_body(self) -> None:
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        self.diagram = Diagram(
            pane,
            on_select=self._on_select,
            on_status=self._set_status,
        )
        pane.add(self.diagram, minsize=400, stretch="always")

        self.props = PropertiesPanel(pane, on_change=self.diagram.redraw)
        pane.add(self.props, minsize=180, width=220)

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_status(self) -> None:
        self._status_var = tk.StringVar(value="Select a tool to begin.")
        tk.Label(
            self.root, textvariable=self._status_var,
            anchor="w", relief="sunken", bd=1,
            font=("TkDefaultFont", 9),
        ).pack(side=tk.BOTTOM, fill=tk.X, ipady=2, padx=2, pady=(0, 2))

    # ── Tool selection ────────────────────────────────────────────────────

    def _set_tool(self, tool: str) -> None:
        for t, btn in self._tool_buttons.items():
            btn.configure(relief="sunken" if t == tool else "flat")
        self.diagram.set_tool(tool)

    # ── Selection → properties ────────────────────────────────────────────

    def _on_select(self, sel) -> None:
        if sel is None:
            self.props.clear()
            return
        kind, elem_id = sel
        if kind == "bus":
            bus = self.diagram.get_buses().get(elem_id)
            if bus:
                self.props.show_bus(bus)
        elif kind == "conn":
            conn = self.diagram.get_connections().get(elem_id)
            if conn:
                self.props.show_connection(conn)
        else:
            self.props.clear()

    # ── Actions ───────────────────────────────────────────────────────────

    def _new(self) -> None:
        self.diagram.clear()
        self.props.clear()
        self._set_status("New diagram — select a tool and start drawing.")

    def _run_power_flow(self) -> None:
        self._set_status("Power flow — not yet wired up.")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)
