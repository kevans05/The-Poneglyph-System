"""Main application window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from poneglyph.ui.diagram import (
    Diagram,
    TOOL_SELECT, TOOL_BUS, TOOL_TLINE, TOOL_FEEDER,
    TOOL_TRANSFORMER, TOOL_CT, TOOL_VT, TOOL_DELETE,
)
from poneglyph.ui.properties import PropertiesPanel


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Poneglyph — Substation Load Test Platform")
        root.geometry("1200x750")
        root.minsize(800, 500)

        # Tracks which tool each dropdown group is currently showing
        self._lines_tool = TOOL_BUS
        self._xfmr_tool  = TOOL_TRANSFORMER

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._set_tool(TOOL_SELECT)

    # ── Menu ──────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = tk.Menu(self.root)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="New",          accelerator="Ctrl+N", command=self._new)
        fm.add_command(label="Open…",        accelerator="Ctrl+O")
        fm.add_command(label="Save",         accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="Export Report…")
        fm.add_separator()
        fm.add_command(label="Quit",         command=self.root.quit)
        mb.add_cascade(label="File", menu=fm)

        sm = tk.Menu(mb, tearoff=0)
        sm.add_command(label="Run Power Flow", command=self._run_power_flow)
        mb.add_cascade(label="Simulation", menu=sm)

        self.root.config(menu=mb)

    # ── Toolbar ───────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.root, bd=1, relief="raised")
        bar.pack(side=tk.TOP, fill=tk.X)

        # Select (standalone)
        self._btn_select = tk.Button(
            bar, text="Select", width=7, relief="flat",
            command=lambda: self._set_tool(TOOL_SELECT),
        )
        self._btn_select.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        # Lines dropdown
        self._btn_lines = tk.Menubutton(bar, text="Lines ▾", width=9, relief="raised",
                                         direction="below")
        lines_menu = tk.Menu(self._btn_lines, tearoff=0)
        lines_menu.add_command(label="Bus",    command=lambda: self._set_lines_tool(TOOL_BUS))
        lines_menu.add_command(label="T-Line", command=lambda: self._set_lines_tool(TOOL_TLINE))
        lines_menu.add_command(label="Feeder", command=lambda: self._set_lines_tool(TOOL_FEEDER))
        self._btn_lines["menu"] = lines_menu
        self._btn_lines.pack(side=tk.LEFT, padx=2, pady=2)

        # Transformers dropdown
        self._btn_xfmr = tk.Menubutton(bar, text="Transformers ▾", width=14, relief="raised",
                                        direction="below")
        xfmr_menu = tk.Menu(self._btn_xfmr, tearoff=0)
        xfmr_menu.add_command(label="Power Transformer",         command=lambda: self._set_xfmr_tool(TOOL_TRANSFORMER))
        xfmr_menu.add_command(label="Current Transformer (CT)",  command=lambda: self._set_xfmr_tool(TOOL_CT))
        xfmr_menu.add_command(label="Voltage Transformer (VT)",  command=lambda: self._set_xfmr_tool(TOOL_VT))
        self._btn_xfmr["menu"] = xfmr_menu
        self._btn_xfmr.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        # Delete (standalone)
        self._btn_delete = tk.Button(
            bar, text="Delete", width=7, relief="flat",
            command=lambda: self._set_tool(TOOL_DELETE),
        )
        self._btn_delete.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)

        tk.Button(bar, text="Run Power Flow", relief="flat", padx=6,
                  command=self._run_power_flow).pack(side=tk.LEFT, padx=2, pady=2)

        # Keyboard shortcuts
        self.root.bind("s", lambda _e: self._set_tool(TOOL_SELECT))
        self.root.bind("b", lambda _e: self._set_lines_tool(TOOL_BUS))
        self.root.bind("t", lambda _e: self._set_lines_tool(TOOL_TLINE))
        self.root.bind("f", lambda _e: self._set_lines_tool(TOOL_FEEDER))
        self.root.bind("x", lambda _e: self._set_xfmr_tool(TOOL_TRANSFORMER))
        self.root.bind("c", lambda _e: self._set_xfmr_tool(TOOL_CT))
        self.root.bind("v", lambda _e: self._set_xfmr_tool(TOOL_VT))
        self.root.bind("d", lambda _e: self._set_tool(TOOL_DELETE))

    # ── Body ──────────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        self.diagram = Diagram(pane, on_select=self._on_select,
                               on_status=self._set_status)
        pane.add(self.diagram, minsize=400, stretch="always")

        self.props = PropertiesPanel(pane, on_change=self.diagram.redraw)
        pane.add(self.props, minsize=180, width=220)

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_status(self) -> None:
        self._status_var = tk.StringVar(value="Select a tool to begin.")
        tk.Label(self.root, textvariable=self._status_var, anchor="w",
                 relief="sunken", bd=1, font=("TkDefaultFont", 9),
                 ).pack(side=tk.BOTTOM, fill=tk.X, ipady=2, padx=2, pady=(0, 2))

    # ── Tool management ───────────────────────────────────────────────────

    _TOOL_LABELS = {
        TOOL_SELECT: "Select",  TOOL_DELETE: "Delete",
        TOOL_BUS: "Lines: Bus", TOOL_TLINE: "Lines: T-Line", TOOL_FEEDER: "Lines: Feeder",
        TOOL_TRANSFORMER: "Transformers: Power Tx",
        TOOL_CT: "Transformers: CT", TOOL_VT: "Transformers: VT",
    }
    _LINES_TOOLS  = {TOOL_BUS, TOOL_TLINE, TOOL_FEEDER}
    _XFMR_TOOLS   = {TOOL_TRANSFORMER, TOOL_CT, TOOL_VT}

    def _set_lines_tool(self, tool: str) -> None:
        self._lines_tool = tool
        labels = {TOOL_BUS: "Bus ▾", TOOL_TLINE: "T-Line ▾", TOOL_FEEDER: "Feeder ▾"}
        self._btn_lines.config(text=labels.get(tool, "Lines ▾"))
        self._set_tool(tool)

    def _set_xfmr_tool(self, tool: str) -> None:
        self._xfmr_tool = tool
        labels = {TOOL_TRANSFORMER: "Power Tx ▾", TOOL_CT: "CT ▾", TOOL_VT: "VT ▾"}
        self._btn_xfmr.config(text=labels.get(tool, "Transformers ▾"))
        self._set_tool(tool)

    def _set_tool(self, tool: str) -> None:
        # Visual feedback on standalone buttons
        self._btn_select.config(relief="sunken" if tool == TOOL_SELECT else "flat")
        self._btn_delete.config(relief="sunken" if tool == TOOL_DELETE else "flat")
        # Dropdown buttons show sunken when their group is active
        self._btn_lines.config(relief="sunken" if tool in self._LINES_TOOLS else "raised")
        self._btn_xfmr.config( relief="sunken" if tool in self._XFMR_TOOLS  else "raised")
        self.diagram.set_tool(tool)

    # ── Selection → properties ────────────────────────────────────────────

    def _on_select(self, sel) -> None:
        if sel is None:
            self.props.clear()
            return
        kind, elem_id = sel
        dispatch = {
            "bus":  lambda: self.props.show_bus(self.diagram.get_buses().get(elem_id)),
            "conn": lambda: self.props.show_connection(self.diagram.get_connections().get(elem_id)),
            "ct":   lambda: self.props.show_ct(self.diagram.get_cts().get(elem_id)),
            "vt":   lambda: self.props.show_vt(self.diagram.get_vts().get(elem_id)),
        }
        fn = dispatch.get(kind)
        if fn:
            fn()
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
