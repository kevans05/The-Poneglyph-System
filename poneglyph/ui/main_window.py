"""Main application window."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk, colorchooser, filedialog, messagebox, simpledialog
from typing import Optional

from poneglyph.ui.diagram import (
    Diagram,
    TOOL_SELECT, TOOL_BUS, TOOL_TLINE, TOOL_FEEDER,
    TOOL_TRANSFORMER, TOOL_SOURCE, TOOL_LOAD, TOOL_CT, TOOL_VT,
    TOOL_CTTB, TOOL_TESTBLOCK, TOOL_DELETE,
    TOOL_BREAKER, TOOL_DISCONNECT,
    TOOL_RELAY, TOOL_RELAY_WIRE, TOOL_RELAY_WIRE_I, TOOL_RELAY_WIRE_V,
)
from poneglyph.io.project import save as project_save, load as project_load
from poneglyph.io.project import sanitize_name, create_project_folders
from poneglyph.ui.properties import PropertiesPanel
from poneglyph.loadtest.log_pose import LogPosePanel


class DrawingEditDialog(tk.Toplevel):
    """Modal dialog to add or edit a drawing registry entry."""

    def __init__(self, parent, existing: dict = None, on_save=None):
        super().__init__(parent)
        self.title("Edit Drawing" if existing else "Add Drawing")
        self.resizable(False, False)
        self.grab_set()
        self._on_save = on_save
        self._orig_name = existing.get("name", "") if existing else ""
        self._build(existing or {})

    def _build(self, d):
        pad = {"padx": 8, "pady": 3}
        f = tk.Frame(self, padx=12, pady=10)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(1, weight=1)

        labels = ["Drawing name", "Title", "Revision", "URL", "Notes"]
        attrs  = ["name", "title", "rev", "url", "notes"]
        self._vars = {}
        for r, (lbl, attr) in enumerate(zip(labels, attrs)):
            tk.Label(f, text=lbl, anchor="w").grid(row=r, column=0, sticky="w", **pad)
            v = tk.StringVar(value=d.get(attr, ""))
            self._vars[attr] = v
            width = 50 if attr in ("url", "notes") else 30
            tk.Entry(f, textvariable=v, width=width).grid(row=r, column=1, sticky="ew", **pad)

        btn = tk.Frame(self)
        btn.pack(fill=tk.X, padx=12, pady=(0, 10))
        tk.Button(btn, text="Save", command=self._save).pack(side=tk.RIGHT, padx=4)
        tk.Button(btn, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _save(self):
        data = {k: v.get().strip() for k, v in self._vars.items()}
        if not data["name"]:
            messagebox.showwarning("Drawing name required",
                                   "Please enter a drawing name.", parent=self)
            return
        if self._on_save:
            self._on_save(self._orig_name, data)
        self.destroy()


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Poneglyph — Substation Load Test Platform")
        root.geometry("1200x750")
        root.minsize(800, 500)

        self._lines_tool = TOOL_BUS
        self._xfmr_tool  = TOOL_TRANSFORMER
        self._current_file: Optional[Path] = None
        self._project_name: str = "Untitled"

        self._build_menu()
        self._build_status()
        self._build_body()
        self._set_tool(TOOL_SELECT)

    # ── Menu ──────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = tk.Menu(self.root)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="New",    accelerator="Ctrl+N", command=self._new)
        fm.add_command(label="Open…", accelerator="Ctrl+O", command=self._open)
        fm.add_command(label="Save",  accelerator="Ctrl+S", command=self._save)
        fm.add_command(label="Save As…",                    command=self._save_as)
        fm.add_separator()
        fm.add_command(label="Quit",  command=self.root.quit)
        mb.add_cascade(label="File", menu=fm)

        sm = tk.Menu(mb, tearoff=0)
        sm.add_command(label="Run Power Flow", command=self._run_power_flow)
        mb.add_cascade(label="Simulation", menu=sm)

        vm = tk.Menu(mb, tearoff=0)
        vm.add_command(label="Voltage Colours…", command=self._edit_volt_colours)
        mb.add_cascade(label="View", menu=vm)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="Keyboard Shortcuts…", command=self._show_keymap)
        mb.add_cascade(label="Help", menu=hm)

        self.root.config(menu=mb)

    # ── Toolbar ───────────────────────────────────────────────────────────

    def _build_toolbar(self, parent: tk.Widget) -> None:
        """Build the SLD toolbar inside the given parent frame."""
        bar = tk.Frame(parent, bd=1, relief="raised")
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

        # Transformers dropdown (power transformers only)
        self._btn_xfmr = tk.Menubutton(bar, text="Transformers ▾", width=14, relief="raised",
                                        direction="below")
        xfmr_menu = tk.Menu(self._btn_xfmr, tearoff=0)
        xfmr_menu.add_command(label="Power Transformer", command=lambda: self._set_xfmr_tool(TOOL_TRANSFORMER))
        self._btn_xfmr["menu"] = xfmr_menu
        self._btn_xfmr.pack(side=tk.LEFT, padx=2, pady=2)

        # Sources dropdown (power source + load)
        self._btn_src = tk.Menubutton(bar, text="Sources ▾", width=10, relief="raised",
                                      direction="below")
        src_menu = tk.Menu(self._btn_src, tearoff=0)
        src_menu.add_command(label="Power Source", command=lambda: self._set_src_tool(TOOL_SOURCE))
        src_menu.add_command(label="Load",         command=lambda: self._set_src_tool(TOOL_LOAD))
        self._btn_src["menu"] = src_menu
        self._btn_src.pack(side=tk.LEFT, padx=2, pady=2)

        # Instrument Devices dropdown
        self._btn_instr = tk.Menubutton(bar, text="Instrument Devices ▾", width=18, relief="raised",
                                         direction="below")
        instr_menu = tk.Menu(self._btn_instr, tearoff=0)
        instr_menu.add_command(label="Current Transformer (CT)", command=lambda: self._set_instr_tool(TOOL_CT))
        instr_menu.add_command(label="Voltage Transformer (VT)", command=lambda: self._set_instr_tool(TOOL_VT))
        instr_menu.add_separator()
        instr_menu.add_command(label="CT Test Block (CTTB)",  command=lambda: self._set_instr_tool(TOOL_CTTB))
        instr_menu.add_command(label="FT / ISO Block",        command=lambda: self._set_instr_tool(TOOL_TESTBLOCK))
        self._btn_instr["menu"] = instr_menu
        self._btn_instr.pack(side=tk.LEFT, padx=2, pady=2)

        # Switching Devices dropdown
        self._btn_switch = tk.Menubutton(bar, text="Switching ▾", width=10, relief="raised",
                                          direction="below")
        switch_menu = tk.Menu(self._btn_switch, tearoff=0)
        switch_menu.add_command(label="Circuit Breaker",   command=lambda: self._set_switch_tool(TOOL_BREAKER))
        switch_menu.add_command(label="Disconnect Switch", command=lambda: self._set_switch_tool(TOOL_DISCONNECT))
        self._btn_switch["menu"] = switch_menu
        self._btn_switch.pack(side=tk.LEFT, padx=2, pady=2)

        # Protection devices dropdown
        self._btn_protect = tk.Menubutton(bar, text="Protection ▾", width=12, relief="raised",
                                           direction="below")
        protect_menu = tk.Menu(self._btn_protect, tearoff=0)
        protect_menu.add_command(label="Relay",    command=lambda: self._set_protect_tool(TOOL_RELAY))
        protect_menu.add_separator()
        protect_menu.add_command(label="CT Wire (CT / CTTB)", command=lambda: self._set_protect_tool(TOOL_RELAY_WIRE_I))
        protect_menu.add_command(label="VT Wire (VT / FT)",   command=lambda: self._set_protect_tool(TOOL_RELAY_WIRE_V))
        self._btn_protect["menu"] = protect_menu
        self._btn_protect.pack(side=tk.LEFT, padx=2, pady=2)

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
        self.root.bind("b", lambda _e: self._toggle_tool(TOOL_BUS,         self._set_lines_tool))
        self.root.bind("t", lambda _e: self._toggle_tool(TOOL_TLINE,       self._set_lines_tool))
        self.root.bind("f", lambda _e: self._toggle_tool(TOOL_FEEDER,      self._set_lines_tool))
        self.root.bind("x", lambda _e: self._toggle_tool(TOOL_TRANSFORMER, self._set_xfmr_tool))
        self.root.bind("p", lambda _e: self._p_key())
        self.root.bind("l", lambda _e: self._toggle_tool(TOOL_LOAD,        self._set_src_tool))
        self.root.bind("c", lambda _e: self._toggle_tool(TOOL_CT,        self._set_instr_tool))
        self.root.bind("v", lambda _e: self._toggle_tool(TOOL_VT,        self._set_instr_tool))
        self.root.bind("n", lambda _e: self._toggle_tool(TOOL_CTTB,      self._set_instr_tool))
        self.root.bind("m", lambda _e: self._toggle_tool(TOOL_TESTBLOCK, self._set_instr_tool))
        self.root.bind("k", lambda _e: self._toggle_tool(TOOL_BREAKER,     self._set_switch_tool))
        self.root.bind("i", lambda _e: self._toggle_tool(TOOL_DISCONNECT,  self._set_switch_tool))
        self.root.bind("y", lambda _e: self._toggle_tool(TOOL_RELAY,      self._set_protect_tool))
        self.root.bind("w", lambda _e: self._toggle_tool(TOOL_RELAY_WIRE_I, self._set_protect_tool))
        self.root.bind("d", lambda _e: self._set_tool(TOOL_DELETE))
        self.root.bind("g", lambda _e: self.diagram.toggle_snap_grid())
        self.root.bind("<space>", lambda _e: self.diagram.toggle_selected_device())
        self.root.bind("r", lambda _e: self.diagram.rotate_selected())
        self.root.bind("<Control-s>", lambda _e: self._save())
        self.root.bind("<Control-o>", lambda _e: self._open())
        self.root.bind("<Control-n>", lambda _e: self._new())
        self.root.bind("<plus>",  lambda _e: self.diagram.zoom_in())
        self.root.bind("<minus>", lambda _e: self.diagram.zoom_out())
        self.root.bind("<Home>",  lambda _e: self.diagram.fit_view())

    # ── Body ──────────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True)
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._main_nb = nb

        # ── Tab 1: SLD ──────────────────────────────────────────────────────
        sld_frame = tk.Frame(nb)
        nb.add(sld_frame, text="SLD")

        # SLD-specific toolbar sits at the top of this tab only
        self._build_toolbar(sld_frame)

        pane = tk.PanedWindow(sld_frame, orient=tk.HORIZONTAL,
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        self.diagram = Diagram(pane, on_select=self._on_select,
                               on_status=self._set_status)
        pane.add(self.diagram, minsize=400, stretch="always")

        self.props = PropertiesPanel(pane, on_change=self._on_props_change)
        self.props.set_diagram(self.diagram)
        pane.add(self.props, minsize=180, width=240)

        # ── Tab 2: Drawings ─────────────────────────────────────────────────
        drw_frame = tk.Frame(nb)
        nb.add(drw_frame, text="Drawings")

        drw_nb = ttk.Notebook(drw_frame)
        drw_nb.pack(fill=tk.BOTH, expand=True)

        # ── Sub-tab 1: Registry ──────────────────────────────────────────────
        reg_frame = tk.Frame(drw_nb)
        drw_nb.add(reg_frame, text="Registry")

        reg_bar = tk.Frame(reg_frame, bd=1, relief="raised")
        reg_bar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(reg_bar, text="+ Add", relief="flat",
                  command=lambda: DrawingEditDialog(self.root, on_save=self._drw_add)
                  ).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(reg_bar, text="Edit", relief="flat",
                  command=self._drw_open_edit_dialog).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(reg_bar, text="Delete", relief="flat",
                  command=self._drw_delete).pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(reg_bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        tk.Button(reg_bar, text="Scan SLD", relief="flat",
                  command=self._drw_scan_sld).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(reg_bar, text="Index", relief="flat",
                  command=self._drw_show_index).pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(reg_bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        tk.Button(reg_bar, text="⬇ Download All", relief="flat",
                  command=self._drw_download_all).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(reg_bar, text="\U0001f5a8 Print Selected", relief="flat",
                  command=self._drw_print_selected).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(reg_bar, text="\U0001f5a8 Print All", relief="flat",
                  command=self._drw_print_all).pack(side=tk.LEFT, padx=2, pady=2)

        reg_content = tk.Frame(reg_frame)
        reg_content.pack(fill=tk.BOTH, expand=True)
        reg_content.columnconfigure(0, weight=1)
        reg_content.rowconfigure(0, weight=1)

        reg_cols = ("drawing", "title", "revision", "url", "notes")
        self._reg_tree = ttk.Treeview(reg_content, columns=reg_cols, show="headings",
                                      selectmode="browse")
        self._reg_tree.heading("drawing",  text="Drawing")
        self._reg_tree.heading("title",    text="Title")
        self._reg_tree.heading("revision", text="Revision")
        self._reg_tree.heading("url",      text="URL")
        self._reg_tree.heading("notes",    text="Notes")
        self._reg_tree.column("drawing",  width=180)
        self._reg_tree.column("title",    width=200)
        self._reg_tree.column("revision", width=70)
        self._reg_tree.column("url",      width=280)
        self._reg_tree.column("notes",    width=200)
        reg_vsb = ttk.Scrollbar(reg_content, orient="vertical", command=self._reg_tree.yview)
        self._reg_tree.configure(yscrollcommand=reg_vsb.set)
        self._reg_tree.grid(row=0, column=0, sticky="nsew")
        reg_vsb.grid(row=0, column=1, sticky="ns")
        self._reg_tree.bind("<Double-1>", lambda _e: self._drw_open_edit_dialog())
        self._reg_tree.bind("<Control-1>", self._drw_ctrl_click)

        # ── Sub-tab 2: Device Links ──────────────────────────────────────────
        lnk_frame = tk.Frame(drw_nb)
        drw_nb.add(lnk_frame, text="Device Links")

        lnk_content = tk.Frame(lnk_frame)
        lnk_content.pack(fill=tk.BOTH, expand=True)
        lnk_content.columnconfigure(0, weight=1)
        lnk_content.rowconfigure(0, weight=1)

        cols = ("device", "type", "drawing")
        self._drw_tree = ttk.Treeview(lnk_content, columns=cols, show="headings",
                                      selectmode="browse")
        self._drw_tree.heading("device",  text="Device")
        self._drw_tree.heading("type",    text="Type")
        self._drw_tree.heading("drawing", text="Drawing")
        self._drw_tree.column("device",  width=140)
        self._drw_tree.column("type",    width=80)
        self._drw_tree.column("drawing", width=200)
        vsb = ttk.Scrollbar(lnk_content, orient="vertical", command=self._drw_tree.yview)
        self._drw_tree.configure(yscrollcommand=vsb.set)
        self._drw_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # ── Tab 3: Load Test ─────────────────────────────────────────────────
        lt_frame = tk.Frame(nb)
        nb.add(lt_frame, text="Load Test")
        self._load_test = LogPosePanel(
            lt_frame,
            diagram=self.diagram,
            project_name=self._project_name,
        )
        self._load_test.pack(fill=tk.BOTH, expand=True)
        self.props.set_history_loader(self._load_test.get_all_records)

    def _on_props_change(self):
        self.diagram.redraw()

    def _on_tab_changed(self, event):
        tab = self._main_nb.index(self._main_nb.select())
        if tab == 1:
            self._drw_refresh_registry()
            self._refresh_drawings_tab()
        elif tab == 2:
            self._load_test.set_project(
                project_name=self._project_name,
                project_path=self._current_file,
            )

    def _refresh_drawings_tab(self):
        tree = self._drw_tree
        for item in tree.get_children():
            tree.delete(item)
        d = self.diagram
        device_groups = [
            (d._cts,         "CT"),
            (d._vts,         "VT"),
            (d._cttbs,       "CTTB"),
            (d._testblocks,  "FT/ISO"),
            (d._relays,      "Relay"),
            (d._breakers,    "Breaker"),
            (d._disconnects, "Disconnect"),
            (d._transformers,"Transformer"),
        ]
        for dev_dict, dev_type in device_groups:
            for dev in dev_dict.values():
                for drw_name in getattr(dev, "device_drawings", []):
                    tree.insert("", tk.END, values=(dev.name, dev_type, drw_name))

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_status(self) -> None:
        self._status_var = tk.StringVar(value="Select a tool to begin.")
        tk.Label(self.root, textvariable=self._status_var, anchor="w",
                 relief="sunken", bd=1, font=("TkDefaultFont", 9),
                 ).pack(side=tk.BOTTOM, fill=tk.X, ipady=2, padx=2, pady=(0, 2))

    # ── Tool management ───────────────────────────────────────────────────

    _LINES_TOOLS   = {TOOL_BUS, TOOL_TLINE, TOOL_FEEDER}
    _XFMR_TOOLS    = {TOOL_TRANSFORMER}
    _SRC_TOOLS     = {TOOL_SOURCE, TOOL_LOAD}
    _INSTR_TOOLS   = {TOOL_CT, TOOL_VT, TOOL_CTTB, TOOL_TESTBLOCK}
    _SWITCH_TOOLS  = {TOOL_BREAKER, TOOL_DISCONNECT}
    _PROTECT_TOOLS = {TOOL_RELAY, TOOL_RELAY_WIRE, TOOL_RELAY_WIRE_I, TOOL_RELAY_WIRE_V}

    def _set_lines_tool(self, tool: str) -> None:
        self._lines_tool = tool
        labels = {TOOL_BUS: "Bus ▾", TOOL_TLINE: "T-Line ▾", TOOL_FEEDER: "Feeder ▾"}
        self._btn_lines.config(text=labels.get(tool, "Lines ▾"))
        self._set_tool(tool)

    def _set_xfmr_tool(self, tool: str) -> None:
        self._xfmr_tool = tool
        self._btn_xfmr.config(text="Power Tx ▾")
        self._set_tool(tool)

    def _set_src_tool(self, tool: str) -> None:
        labels = {TOOL_SOURCE: "Source ▾", TOOL_LOAD: "Load ▾"}
        self._btn_src.config(text=labels.get(tool, "Sources ▾"))
        self._set_tool(tool)

    def _set_instr_tool(self, tool: str) -> None:
        labels = {TOOL_CT: "CT ▾", TOOL_VT: "VT ▾",
                  TOOL_CTTB: "CTTB ▾", TOOL_TESTBLOCK: "FT/ISO ▾"}
        self._btn_instr.config(text=labels.get(tool, "Instrument Devices ▾"))
        self._set_tool(tool)

    def _set_switch_tool(self, tool: str) -> None:
        labels = {TOOL_BREAKER: "Breaker ▾", TOOL_DISCONNECT: "Disconnect ▾"}
        self._btn_switch.config(text=labels.get(tool, "Switching ▾"))
        self._set_tool(tool)

    def _set_protect_tool(self, tool: str) -> None:
        labels = {TOOL_RELAY: "Relay ▾", TOOL_RELAY_WIRE: "Relay Wire ▾",
                  TOOL_RELAY_WIRE_I: "I-Wire ▾", TOOL_RELAY_WIRE_V: "V-Wire ▾"}
        self._btn_protect.config(text=labels.get(tool, "Protection ▾"))
        self._set_tool(tool)

    def _set_tool(self, tool: str, sticky: bool = False) -> None:
        self._btn_select.config(relief="sunken" if tool == TOOL_SELECT else "flat")
        self._btn_delete.config(relief="sunken" if tool == TOOL_DELETE else "flat")
        self._btn_lines.config(   relief="sunken" if tool in self._LINES_TOOLS   else "raised")
        self._btn_xfmr.config(    relief="sunken" if tool in self._XFMR_TOOLS    else "raised")
        self._btn_src.config(     relief="sunken" if tool in self._SRC_TOOLS     else "raised")
        self._btn_instr.config(   relief="sunken" if tool in self._INSTR_TOOLS   else "raised")
        self._btn_switch.config(  relief="sunken" if tool in self._SWITCH_TOOLS  else "raised")
        self._btn_protect.config( relief="sunken" if tool in self._PROTECT_TOOLS else "raised")
        self.diagram.set_tool(tool, sticky=sticky)

    def _toggle_tool(self, tool: str, set_fn) -> None:
        """Press hotkey: if already in this tool → toggle sticky; else activate it."""
        if self.diagram._tool == tool:
            new_sticky = not self.diagram._sticky_tool
            self.diagram.set_tool(tool, sticky=new_sticky)
        else:
            set_fn(tool)

    # ── Selection → properties ────────────────────────────────────────────

    def _on_select(self, sel) -> None:
        if sel is None:
            self.props.clear()
            return
        kind, elem_id = sel
        dispatch = {
            "bus":         lambda: self.props.show_bus(self.diagram.get_buses().get(elem_id)),
            "conn":        lambda: self.props.show_connection(self.diagram.get_connections().get(elem_id)),
            "transformer": lambda: self.props.show_transformer(self.diagram.get_transformers().get(elem_id)),
            "source":      lambda: self.props.show_source(self.diagram.get_sources().get(elem_id)),
            "load":        lambda: self.props.show_load(self.diagram.get_loads().get(elem_id)),
            "ct":          lambda: self.props.show_ct(self.diagram.get_cts().get(elem_id)),
            "vt":          lambda: self.props.show_vt(self.diagram.get_vts().get(elem_id)),
            "cttb":        lambda: self.props.show_cttb(self.diagram.get_cttbs().get(elem_id)),
            "testblock":   lambda: self.props.show_testblock(self.diagram.get_testblocks().get(elem_id)),
            "breaker":     lambda: self.props.show_breaker(self.diagram.get_breakers().get(elem_id)),
            "disconnect":  lambda: self.props.show_disconnect(self.diagram.get_disconnects().get(elem_id)),
            "relay":       lambda: self.props.show_relay(self.diagram.get_relays().get(elem_id)),
            "relay_wire":  lambda: self.props.show_relay_wire(self.diagram.get_relay_wires().get(elem_id)),
        }
        fn = dispatch.get(kind)
        if fn:
            fn()
        else:
            self.props.clear()

    # ── Actions ───────────────────────────────────────────────────────────

    def _edit_volt_colours(self) -> None:
        VoltageColourDialog(self.root, self.diagram)

    def _p_key(self) -> None:
        """P = flip CT polarity when a CT is selected, else activate Power Source tool."""
        kind, _ = self.diagram.get_selection()
        if kind == "ct":
            self.diagram.flip_ct_polarity()
        else:
            self._toggle_tool(TOOL_SOURCE, self._set_src_tool)

    def _show_keymap(self) -> None:
        KeymapDialog(self.root)

    def _new(self) -> None:
        self.diagram.clear()
        self.props.clear()
        self._current_file = None
        self._project_name = "Untitled"
        self._set_status("New diagram — select a tool and start drawing.")

    # ── File I/O ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._current_file:
            self._save_as()
        else:
            self._write_file(self._current_file)

    def _save_as(self) -> None:
        name = simpledialog.askstring(
            "Project Name", "Enter project name:",
            initialvalue=self._project_name, parent=self.root
        )
        if not name:
            return
        self._project_name = name.strip() or "Untitled"
        safe = sanitize_name(self._project_name)

        # Ask where to put the project folder
        parent_dir = filedialog.askdirectory(title="Choose location for project folder")
        if not parent_dir:
            return

        project_folder = Path(parent_dir) / safe
        project_folder.mkdir(exist_ok=True)
        create_project_folders(project_folder)

        filepath = project_folder / f"{safe}.poneglyph"
        self._current_file = filepath
        self._write_file(filepath)

    def _write_file(self, filepath: Path) -> None:
        try:
            project_save(self.diagram, filepath, self._project_name)
            self.root.title(f"Poneglyph — {self._project_name}")
            self._set_status(f"Saved → {filepath}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _open(self) -> None:
        fname = filedialog.askopenfilename(
            filetypes=[("Poneglyph diagram", "*.poneglyph"), ("All files", "*")],
            title="Open diagram",
        )
        if not fname:
            return
        try:
            pname = project_load(self.diagram, fname)
            self.props.clear()
            self._current_file = Path(fname)
            self._project_name = pname
            self.root.title(f"Poneglyph — {pname}")
            self._set_status(f"Opened {fname}")
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def _run_power_flow(self) -> None:
        from poneglyph.ui.network_state import build_network
        from poneglyph.simulation.powerflow import PowerFlowSolver

        buses   = self.diagram.get_buses()
        conns   = self.diagram.get_connections()
        xfmrs   = self.diagram.get_transformers()
        sources = self.diagram.get_sources()
        loads   = self.diagram.get_loads()

        if not buses:
            self._set_status("Add at least one bus before running power flow.")
            return
        if not sources:
            self._set_status("Add a Power Source (defines the slack bus) before running power flow.")
            return

        net = build_network(buses, conns, xfmrs)
        solver = PowerFlowSolver(net)

        slack_bus = next((s.bus for s in sources.values() if s.bus in net.buses), None)
        if slack_bus is None:
            self._set_status("Attach the Power Source to a bus (snap it onto a bus bar) first.")
            return
        src = next(s for s in sources.values() if s.bus == slack_bus)
        solver.set_slack_bus(slack_bus, v_pu=src.v_pu, angle_deg=src.angle_deg)

        for ld in loads.values():
            if ld.bus in net.buses:
                solver.set_load(ld.bus, ld.p_mw, ld.q_mvar)

        result = solver.solve()

        for bid, dbus in buses.items():
            nb = net.buses.get(bid)
            dbus.v_solved = nb.v_pu if nb else None

        self._store_pf_results(net, buses, conns, xfmrs, sources, loads)
        self.diagram.redraw()

        # Refresh properties panel so Predictions tab updates immediately
        sel = self.diagram.get_selection()
        if sel is not None:
            self._on_select(sel)

        if result.converged:
            self._set_status(f"Power flow converged in {result.iterations} iterations. "
                             f"Slack: {slack_bus}.")
        else:
            self._set_status(f"Power flow DID NOT converge after {result.iterations} iterations.")

    def _store_pf_results(self, net, buses, conns, xfmrs, sources, loads) -> None:
        """Stamp pf_solved dicts onto diagram devices after a power-flow solve."""
        import cmath as _cm, math as _m
        sqrt3 = _m.sqrt(3)
        BASE  = net.base_mva   # MVA

        def _ph3(mag, ang):
            return (_cm.rect(mag, ang),
                    _cm.rect(mag, ang - 2*_m.pi/3),
                    _cm.rect(mag, ang + 2*_m.pi/3))

        def _branch_flow(nb_from, nb_to, br):
            phi = getattr(br, "phase_shift_rad", 0.0)
            if abs(phi) > 1e-9:
                # Phase-shifting transformer: I_HV = (V_HV - a*V_LV) / Z
                a = _cm.rect(1.0, phi)
                dv = nb_from.v_pu - a * nb_to.v_pu
            else:
                dv = nb_from.v_pu - nb_to.v_pu
            ipu = dv / br.z_pu if abs(br.z_pu) > 1e-12 else 0j
            base_i = (BASE * 1e6) / (nb_from.base_kv * 1e3 * sqrt3)
            imag = abs(ipu) * base_i
            iang = _cm.phase(ipu)
            s = nb_from.v_pu * ipu.conjugate()
            p_kw   = s.real * BASE * 1e3
            q_kvar = s.imag * BASE * 1e3
            s_kva  = _m.hypot(p_kw, q_kvar)
            pf     = p_kw / s_kva if s_kva > 1e-9 else 1.0
            ia, ib, ic = _ph3(imag, iang)
            vln  = abs(nb_from.v_pu) * nb_from.base_kv / sqrt3
            vll  = abs(nb_from.v_pu) * nb_from.base_kv
            vang = _cm.phase(nb_from.v_pu)
            va, vb, vc = _ph3(vln, vang)
            return {"type": "branch",
                    "i_a": ia, "i_b": ib, "i_c": ic,
                    "i_mag": imag, "i_ang_deg": _m.degrees(iang),
                    "v_a": va, "v_b": vb, "v_c": vc,
                    "v_kv_ln": vln, "v_kv_ll": vll,
                    "p_kw": p_kw, "q_kvar": q_kvar, "s_kva": s_kva, "pf": pf}

        def _bus_power(bid):
            p_kw = q_kvar = 0.0
            for br in net.connected_branches(bid):
                fb = net.get_bus(br.from_bus)
                tb = net.get_bus(br.to_bus)
                if not fb or not tb:
                    continue
                dv = fb.v_pu - tb.v_pu
                ipu = dv / br.z_pu if abs(br.z_pu) > 1e-12 else 0j
                vref = fb.v_pu if br.from_bus == bid else tb.v_pu
                sign = 1 if br.from_bus == bid else -1
                s = vref * (sign * ipu).conjugate()
                p_kw   += s.real * BASE * 1e3
                q_kvar += s.imag * BASE * 1e3
            return p_kw, q_kvar

        # ── buses ────────────────────────────────────────────────────────
        for bid, dbus in buses.items():
            nb = net.buses.get(bid)
            if nb is None:
                dbus.pf_solved = None
                continue
            vpu  = nb.v_pu
            vmag = abs(vpu)
            vang = _cm.phase(vpu)
            vln  = vmag * nb.base_kv / sqrt3
            vll  = vmag * nb.base_kv
            va, vb, vc = _ph3(vln, vang)
            p_kw, q_kvar = _bus_power(bid)
            s_kva = _m.hypot(p_kw, q_kvar)
            pf    = p_kw / s_kva if s_kva > 1e-9 else 1.0
            dbus.pf_solved = {
                "type": "bus",
                "v_mag_pu": vmag, "v_ang_deg": _m.degrees(vang),
                "v_kv_ln": vln, "v_kv_ll": vll,
                "v_a": va, "v_b": vb, "v_c": vc,
                "p_kw": p_kw, "q_kvar": q_kvar, "s_kva": s_kva, "pf": pf,
            }

        # ── connections + transformers ────────────────────────────────────
        for brid, dev in list(conns.items()) + list(xfmrs.items()):
            br = net.branches.get(brid)
            if br is None:
                dev.pf_solved = None
                continue
            fb = net.get_bus(br.from_bus)
            tb = net.get_bus(br.to_bus)
            dev.pf_solved = _branch_flow(fb, tb, br) if (fb and tb) else None

        # ── sources ──────────────────────────────────────────────────────
        for src in sources.values():
            nb = net.buses.get(src.bus) if src.bus else None
            if not nb:
                src.pf_solved = None
                continue
            vmag = abs(nb.v_pu)
            vang = _cm.phase(nb.v_pu)
            vln  = vmag * nb.base_kv / sqrt3
            vll  = vmag * nb.base_kv
            va, vb, vc = _ph3(vln, vang)
            p_kw, q_kvar = _bus_power(src.bus)
            s_kva = _m.hypot(p_kw, q_kvar)
            pf_val = p_kw / s_kva if s_kva > 1e-9 else 1.0
            imag   = (s_kva * 1e3 / 3) / (vln * 1e3) if vln > 1e-9 else 0.0
            ia, ib, ic = _ph3(imag, vang)
            src.pf_solved = {
                "type": "source",
                "v_kv_ln": vln, "v_kv_ll": vll, "v_ang_deg": _m.degrees(vang),
                "v_a": va, "v_b": vb, "v_c": vc,
                "p_kw": p_kw, "q_kvar": q_kvar, "s_kva": s_kva, "pf": pf_val,
                "i_a": ia, "i_b": ib, "i_c": ic,
            }

        # ── loads ─────────────────────────────────────────────────────────
        for ld in loads.values():
            nb = net.buses.get(ld.bus) if ld.bus else None
            p_kw, q_kvar = ld._resolved()
            s_kva = _m.hypot(p_kw, q_kvar)
            pf_val = p_kw / s_kva if s_kva > 1e-9 else 1.0
            if nb and abs(nb.v_pu) > 1e-9:
                vln  = abs(nb.v_pu) * nb.base_kv / sqrt3
                vll  = abs(nb.v_pu) * nb.base_kv
                vang = _cm.phase(nb.v_pu)
                imag = (s_kva * 1e3 / 3) / (vln * 1e3) if vln > 1e-9 else 0.0
                iang = vang - _m.acos(min(1.0, abs(pf_val)))
                va, vb, vc = _ph3(vln, vang)
            else:
                vln = vll = 0.0
                imag = iang = 0.0
                va = vb = vc = 0j
            ia, ib, ic = _ph3(imag, iang)
            ld.pf_solved = {
                "type": "load",
                "v_a": va, "v_b": vb, "v_c": vc,
                "v_kv_ln": vln, "v_kv_ll": vll,
                "p_kw": p_kw, "q_kvar": q_kvar, "s_kva": s_kva, "pf": pf_val,
                "i_a": ia, "i_b": ib, "i_c": ic, "i_mag": imag,
            }

        # ── secondary devices ─────────────────────────────────────────────
        diag = self.diagram
        cts        = diag.get_cts()
        vts        = diag.get_vts()
        cttbs      = diag.get_cttbs()
        testblocks = diag.get_testblocks()
        relays     = diag.get_relays()
        rwires     = diag.get_relay_wires()

        # ── CTs ──────────────────────────────────────────────────────────
        for ct in cts.values():
            # Find the branch the CT sits on
            br_dev = conns.get(ct.connection_id) or xfmrs.get(ct.xfmr_id)
            pf_br  = getattr(br_dev, "pf_solved", None) if br_dev else None
            if not pf_br:
                ct.pf_solved = None
                continue
            ratio = ct.ratio_secondary / ct.ratio_primary if ct.ratio_primary else 1.0
            i_pri = pf_br["i_mag"]
            i_sec = i_pri * ratio
            ang   = pf_br["i_ang_deg"]
            ia, ib, ic = _ph3(i_sec, _m.radians(ang))
            ct.pf_solved = {
                "type": "ct",
                "i_mag": i_sec, "i_ang_deg": ang,
                "i_a": ia, "i_b": ib, "i_c": ic,
                "ratio": f"{ct.ratio_primary}:{ct.ratio_secondary}",
            }

        # ── VTs ──────────────────────────────────────────────────────────
        def _bus_is_delta(bus_id: str) -> bool:
            """True if bus_id is the terminal of a delta winding on any transformer."""
            for tx in xfmrs.values():
                if tx.hv_bus == bus_id and tx.hv_winding == "delta":
                    return True
                if tx.lv_bus == bus_id and tx.lv_winding == "delta":
                    return True
            return False

        for vt in vts.values():
            nb = net.buses.get(vt.bus_id) if vt.bus_id else None
            if not nb:
                vt.pf_solved = None
                continue
            ratio  = vt.ratio_secondary / vt.ratio_primary if vt.ratio_primary else 1.0
            vang   = _m.degrees(_cm.phase(nb.v_pu))
            # Delta-winding buses have no neutral — VT primary sees V_LL, not V_LN.
            # Wye-grounded buses: primary sees V_LN (= base_kv / sqrt3 per-unit).
            is_delta = _bus_is_delta(vt.bus_id)
            if is_delta:
                v_pri = abs(nb.v_pu) * nb.base_kv * 1000          # V_LL in volts
            else:
                v_pri = abs(nb.v_pu) * nb.base_kv / sqrt3 * 1000  # V_LN in volts
            v_sec  = v_pri * ratio
            va, vb, vc = _ph3(v_sec, _m.radians(vang))
            vt.pf_solved = {
                "type": "vt",
                "v_mag": v_sec, "v_ang_deg": vang,
                "v_a": va, "v_b": vb, "v_c": vc,
                "ratio": f"{vt.ratio_primary:.0f}:{vt.ratio_secondary:.0f}",
                "delta_primary": is_delta,
            }

        # ── CTTBs ─────────────────────────────────────────────────────────
        # Build a lookup: relay_wire dest_id → list of source pf_solved dicts
        # We process CTTBs iteratively so downstream CTTBs can read upstream results.
        def _get_cttb_input_phasors(cttb_id: str) -> list:
            """Return list of (complex) secondary current phasors feeding this CTTB."""
            inputs = []
            for rw in rwires.values():
                if rw.relay_id == cttb_id and rw.dest_type == "cttb":
                    if rw.source_type == "ct":
                        src_pf = getattr(cts.get(rw.source_id), "pf_solved", None)
                        if src_pf:
                            inputs.append(src_pf["i_a"])  # use phase A as representative
                    elif rw.source_type == "cttb":
                        src_pf = getattr(cttbs.get(rw.source_id), "pf_solved", None)
                        if src_pf:
                            inputs.append(src_pf["i_a"])
            return inputs

        # Two-pass: first pass handles CTs as sources, second handles CTTB→CTTB chains
        for _ in range(2):
            for cttb in cttbs.values():
                phasors_in = _get_cttb_input_phasors(cttb.id)
                if not phasors_in:
                    cttb.pf_solved = None
                    continue
                if cttb.mode == "Sum":
                    combined = sum(phasors_in)
                elif cttb.mode == "Subtract" and len(phasors_in) >= 2:
                    combined = phasors_in[0] - sum(phasors_in[1:])
                else:
                    combined = phasors_in[0]   # Pass or single input
                i_sec = abs(combined)
                ang_r = _cm.phase(combined)
                ia, ib, ic = _ph3(i_sec, ang_r)
                cttb.pf_solved = {
                    "type": "cttb",
                    "i_mag": i_sec, "i_ang_deg": _m.degrees(ang_r),
                    "i_a": ia, "i_b": ib, "i_c": ic,
                    "mode": cttb.mode,
                }

        # ── TestBlocks (FT/ISO) ───────────────────────────────────────────
        def _get_tb_voltage(tb_id: str):
            """Return (complex volts, ang_deg) for a test block from upstream VT/TB."""
            for rw in rwires.values():
                if rw.relay_id == tb_id and rw.dest_type == "testblock" and rw.wire_type == "voltage":
                    if rw.source_type == "vt":
                        src_pf = getattr(vts.get(rw.source_id), "pf_solved", None)
                        if src_pf:
                            return src_pf["v_a"], src_pf["v_ang_deg"]
                    elif rw.source_type == "testblock":
                        src_pf = getattr(testblocks.get(rw.source_id), "pf_solved", None)
                        if src_pf:
                            return src_pf["v_a"], src_pf["v_ang_deg"]
            return None, None

        for _ in range(2):
            for tb in testblocks.values():
                v_complex, ang_deg = _get_tb_voltage(tb.id)
                if v_complex is None:
                    tb.pf_solved = None
                    continue
                v_mag = abs(v_complex)
                ang_r = _cm.phase(v_complex)
                va, vb, vc = _ph3(v_mag, ang_r)
                tb.pf_solved = {
                    "type": "testblock",
                    "v_mag": v_mag, "v_ang_deg": ang_deg,
                    "v_a": va, "v_b": vb, "v_c": vc,
                }

        # ── Relays ────────────────────────────────────────────────────────
        for relay in relays.values():
            winding_data = []
            # Collect wires that terminate at this relay
            relay_inputs = [rw for rw in rwires.values()
                            if rw.relay_id == relay.id and rw.dest_type == "relay"]
            for w_idx, winding_label in enumerate(relay.windings):
                w_wires = [rw for rw in relay_inputs if rw.winding == w_idx + 1]
                i_complex = v_complex_w = None
                for rw in w_wires:
                    if rw.wire_type == "current":
                        if rw.source_type == "ct":
                            src_pf = getattr(cts.get(rw.source_id), "pf_solved", None)
                        elif rw.source_type == "cttb":
                            src_pf = getattr(cttbs.get(rw.source_id), "pf_solved", None)
                        else:
                            src_pf = None
                        if src_pf:
                            i_complex = src_pf["i_a"]
                    elif rw.wire_type == "voltage":
                        if rw.source_type == "vt":
                            src_pf = getattr(vts.get(rw.source_id), "pf_solved", None)
                        elif rw.source_type == "testblock":
                            src_pf = getattr(testblocks.get(rw.source_id), "pf_solved", None)
                        else:
                            src_pf = None
                        if src_pf:
                            v_complex_w = src_pf["v_a"]
                if i_complex is not None:
                    i_mag = abs(i_complex)
                    i_ang = _m.degrees(_cm.phase(i_complex))
                    wi_a, wi_b, wi_c = _ph3(i_mag, _cm.phase(i_complex))
                else:
                    i_mag = i_ang = None
                    wi_a = wi_b = wi_c = None
                if v_complex_w is not None:
                    v_mag = abs(v_complex_w)
                    v_ang = _m.degrees(_cm.phase(v_complex_w))
                    wv_a, wv_b, wv_c = _ph3(v_mag, _cm.phase(v_complex_w))
                else:
                    v_mag = v_ang = None
                    wv_a = wv_b = wv_c = None
                winding_data.append({
                    "label": winding_label,
                    "i_mag": i_mag, "i_ang_deg": i_ang,
                    "i_a": wi_a, "i_b": wi_b, "i_c": wi_c,
                    "v_mag": v_mag, "v_ang_deg": v_ang,
                    "v_a": wv_a, "v_b": wv_b, "v_c": wv_c,
                })
            has_any = any(
                w["i_mag"] is not None or w["v_mag"] is not None
                for w in winding_data
            )
            relay.pf_solved = {"type": "relay", "windings": winding_data} if has_any else None

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    # ── Drawing registry ──────────────────────────────────────────────────

    def _drw_refresh_registry(self):
        """Repopulate the registry treeview from diagram._drawings."""
        for item in self._reg_tree.get_children():
            self._reg_tree.delete(item)
        for name in sorted(self.diagram._drawings.keys()):
            d = self.diagram._drawings[name]
            self._reg_tree.insert("", tk.END, iid=name, values=(
                d.name,
                getattr(d, "title", ""),
                d.rev,
                d.url,
                getattr(d, "notes", ""),
            ))

    def _drw_ctrl_click(self, event):
        import webbrowser
        item = self._reg_tree.identify_row(event.y)
        if not item:
            return
        d = self.diagram._drawings.get(item)
        if d and d.url:
            webbrowser.open(d.url)

    def _drw_add(self, _orig_name, data):
        """Callback from DrawingEditDialog — add new entry."""
        from poneglyph.ui.diagram import DiagramDrawing
        name = data["name"]
        self.diagram._drawings[name] = DiagramDrawing(
            name=name,
            url=data.get("url", ""),
            rev=data.get("rev", ""),
            description=data.get("title", ""),
            title=data.get("title", ""),
            notes=data.get("notes", ""),
        )
        self._drw_refresh_registry()
        self.diagram.redraw()

    def _drw_edit(self, orig_name, data):
        """Callback from DrawingEditDialog — update existing entry."""
        from poneglyph.ui.diagram import DiagramDrawing
        new_name = data["name"]
        self.diagram._drawings.pop(orig_name, None)
        self.diagram._drawings[new_name] = DiagramDrawing(
            name=new_name,
            url=data.get("url", ""),
            rev=data.get("rev", ""),
            description=data.get("title", ""),
            title=data.get("title", ""),
            notes=data.get("notes", ""),
        )
        self._drw_refresh_registry()
        self.diagram.redraw()

    def _drw_delete(self):
        sel = self._reg_tree.selection()
        if not sel:
            return
        name = self._reg_tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Delete drawing",
                               f"Remove '{name}' from the registry?",
                               parent=self.root):
            self.diagram._drawings.pop(name, None)
            self._drw_refresh_registry()
            self.diagram.redraw()

    def _drw_open_edit_dialog(self):
        sel = self._reg_tree.selection()
        if not sel:
            return
        name = sel[0]
        d = self.diagram._drawings.get(name)
        if d is None:
            return
        existing = {
            "name":  d.name,
            "title": getattr(d, "title", getattr(d, "description", "")),
            "rev":   d.rev,
            "url":   d.url,
            "notes": getattr(d, "notes", ""),
        }
        DrawingEditDialog(self.root, existing=existing, on_save=self._drw_edit)

    def _drw_scan_sld(self):
        """Walk all device_drawings lists; add any names not yet in registry."""
        from poneglyph.ui.diagram import DiagramDrawing
        added = 0
        all_devs = (
            list(self.diagram._cts.values()) + list(self.diagram._vts.values()) +
            list(self.diagram._cttbs.values()) + list(self.diagram._testblocks.values()) +
            list(self.diagram._relays.values()) + list(self.diagram._breakers.values()) +
            list(self.diagram._disconnects.values()) + list(self.diagram._transformers.values())
        )
        for dev in all_devs:
            for drw_name in getattr(dev, "device_drawings", []):
                if drw_name and drw_name not in self.diagram._drawings:
                    self.diagram._drawings[drw_name] = DiagramDrawing(name=drw_name)
                    added += 1
        self._drw_refresh_registry()
        messagebox.showinfo("Scan SLD", f"Added {added} new drawing(s) to the registry.",
                            parent=self.root)

    def _drw_show_index(self):
        """Show cross-reference: drawing → devices that reference it."""
        lines = {}
        all_devs = (
            list(self.diagram._cts.values()) + list(self.diagram._vts.values()) +
            list(self.diagram._cttbs.values()) + list(self.diagram._testblocks.values()) +
            list(self.diagram._relays.values()) + list(self.diagram._breakers.values()) +
            list(self.diagram._disconnects.values()) + list(self.diagram._transformers.values())
        )
        for dev in all_devs:
            for drw_name in getattr(dev, "device_drawings", []):
                lines.setdefault(drw_name, []).append(dev.name)
        if not lines:
            messagebox.showinfo("Drawing Index", "No device–drawing links found.", parent=self.root)
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Drawing Index")
        dlg.grab_set()
        tv = ttk.Treeview(dlg, columns=("drawing", "devices"), show="headings")
        tv.heading("drawing", text="Drawing")
        tv.heading("devices", text="Devices")
        tv.column("drawing", width=200)
        tv.column("devices", width=400)
        for drw_name in sorted(lines.keys()):
            tv.insert("", tk.END, values=(drw_name, ", ".join(sorted(lines[drw_name]))))
        tv.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        tk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=(0, 8))

    def _drw_download_all(self):
        """Download all drawings with a URL into <project>/Drawings/<name>/."""
        import threading, urllib.request
        if not self._current_file:
            messagebox.showwarning("No project", "Save the project first to set a download folder.",
                                   parent=self.root)
            return
        drawings_dir = self._current_file.parent / "Drawings"
        drawings_dir.mkdir(exist_ok=True)
        to_download = [(n, d) for n, d in self.diagram._drawings.items() if d.url]
        if not to_download:
            messagebox.showinfo("Download All", "No drawings have a URL set.", parent=self.root)
            return

        def _worker():
            ok, fail = 0, 0
            for name, d in to_download:
                sub = drawings_dir / name.replace("/", "_")
                sub.mkdir(exist_ok=True)
                fname = d.url.rsplit("/", 1)[-1] or f"{name}.pdf"
                dest  = sub / fname
                try:
                    urllib.request.urlretrieve(d.url, dest)
                    ok += 1
                except Exception:
                    fail += 1
            self.root.after(0, lambda: messagebox.showinfo(
                "Download complete", f"Downloaded {ok}, failed {fail}.", parent=self.root))

        threading.Thread(target=_worker, daemon=True).start()
        self._set_status(f"Downloading {len(to_download)} drawing(s)…")

    def _drw_print_selected(self):
        import subprocess, sys
        sel = self._reg_tree.selection()
        if not sel or not self._current_file:
            return
        name = self._reg_tree.item(sel[0])["values"][0]
        sub = self._current_file.parent / "Drawings" / name.replace("/", "_")
        files = list(sub.iterdir()) if sub.exists() else []
        if not files:
            messagebox.showwarning("Print", f"No downloaded file found for '{name}'.",
                                   parent=self.root)
            return
        for f in files:
            if sys.platform == "win32":
                import os; os.startfile(str(f), "print")
            else:
                subprocess.Popen(["lpr", str(f)])

    def _drw_print_all(self):
        import subprocess, sys
        if not self._current_file:
            return
        drawings_dir = self._current_file.parent / "Drawings"
        if not drawings_dir.exists():
            return
        for sub in drawings_dir.iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    if sys.platform == "win32":
                        import os; os.startfile(str(f), "print")
                    else:
                        subprocess.Popen(["lpr", str(f)])


class VoltageColourDialog(tk.Toplevel):
    """Editable table of voltage-level → colour mappings."""

    def __init__(self, parent: tk.Tk, diagram: Diagram) -> None:
        super().__init__(parent)
        self.title("Voltage Colours")
        self.resizable(False, False)
        self.grab_set()
        self._diagram = diagram
        self._rows: list[tuple[tk.StringVar, tk.StringVar, tk.Label]] = []

        self._build(diagram.get_volt_colours())

    def _build(self, mapping: dict) -> None:
        hdr = tk.Frame(self)
        hdr.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(hdr, text="kV", width=8, font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)
        tk.Label(hdr, text="Colour", width=12, font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)

        self._list_frame = tk.Frame(self)
        self._list_frame.pack(fill=tk.BOTH, padx=8, pady=4)

        for kv, colour in sorted(mapping.items()):
            self._add_row(kv, colour)

        btn_row = tk.Frame(self)
        btn_row.pack(fill=tk.X, padx=8, pady=8)
        tk.Button(btn_row, text="Add Row", command=self._add_blank_row).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_row, text="Apply", command=self._apply).pack(side=tk.RIGHT, padx=2)
        tk.Button(btn_row, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=2)

    def _add_row(self, kv: float = 0.0, colour: str = "#000000") -> None:
        row = tk.Frame(self._list_frame)
        row.pack(fill=tk.X, pady=1)

        kv_var  = tk.StringVar(value=str(kv) if kv else "")
        col_var = tk.StringVar(value=colour)

        tk.Entry(row, textvariable=kv_var, width=8).pack(side=tk.LEFT, padx=2)

        swatch = tk.Label(row, bg=colour, width=4, relief="sunken", cursor="hand2")
        swatch.pack(side=tk.LEFT, padx=2)

        col_entry = tk.Entry(row, textvariable=col_var, width=10)
        col_entry.pack(side=tk.LEFT, padx=2)

        def pick_colour(sv=col_var, sw=swatch):
            result = colorchooser.askcolor(color=sv.get(), parent=self, title="Pick colour")
            if result and result[1]:
                sv.set(result[1])
                try:
                    sw.config(bg=result[1])
                except tk.TclError:
                    pass

        def on_entry_change(*_, sv=col_var, sw=swatch):
            try:
                sw.config(bg=sv.get())
            except tk.TclError:
                pass

        swatch.bind("<Button-1>", lambda _e: pick_colour())
        col_var.trace_add("write", on_entry_change)

        def remove(r=row, entry=(kv_var, col_var, swatch)):
            r.destroy()
            self._rows = [t for t in self._rows if t is not entry]

        tk.Button(row, text="✕", width=2, command=remove).pack(side=tk.LEFT, padx=2)
        self._rows.append((kv_var, col_var, swatch))

    def _add_blank_row(self) -> None:
        self._add_row(0.0, "#000000")

    def _collect(self) -> dict[float, str]:
        result: dict[float, str] = {}
        for kv_var, col_var, _ in self._rows:
            try:
                kv = float(kv_var.get())
                col = col_var.get().strip()
                if kv > 0 and col:
                    result[kv] = col
            except ValueError:
                pass
        return result

    def _apply(self) -> None:
        self._diagram.set_volt_colours(self._collect())

    def _ok(self) -> None:
        self._apply()
        self.destroy()


class KeymapDialog(tk.Toplevel):
    _KEYMAP = [
        ("Tools", [
            ("S",        "Select tool"),
            ("B",        "Bus tool  (press again to toggle sticky)"),
            ("T",        "T-Line tool"),
            ("F",        "Feeder tool"),
            ("X",        "Transformer tool"),
            ("L",        "Load tool"),
            ("C",        "Current Transformer (CT) tool"),
            ("V",        "Voltage Transformer (VT) tool"),
            ("N",        "CT Test Block (CTTB) tool"),
            ("M",        "FT / ISO Block tool"),
            ("K",        "Circuit Breaker tool"),
            ("I",        "Disconnect Switch tool"),
            ("Y",        "Relay tool"),
            ("W",        "Relay Wire tool"),
            ("D",        "Delete tool"),
        ]),
        ("Editing", [
            ("Space",    "Toggle selected breaker / disconnect open ↔ closed"),
            ("R",        "Rotate selected transformer 90° CCW"),
            ("P",        "Flip CT polarity (when CT selected) / Power Source tool"),
            ("G",        "Toggle grid snap ON / OFF"),
            ("Shift+click (bus node)", "Delete node  (merges adjacent segments)"),
            ("Shift+click (bus segment midpoint)", "Insert node"),
            ("Drag terminal dot",     "Rewire device terminal to a different bus"),
            ("Drag label",            "Move element label (wire goes invisible underneath)"),
        ]),
        ("Canvas", [
            ("Right-click drag",  "Pan"),
            ("Mouse wheel",       "Zoom in / out"),
            ("Ctrl+N",            "New diagram"),
        ]),
    ]

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.title("Keyboard Shortcuts")
        self.resizable(False, False)
        self.grab_set()

        pad = {"padx": 6, "pady": 2}
        row = 0
        for section, entries in self._KEYMAP:
            tk.Label(self, text=section, font=("TkDefaultFont", 9, "bold"),
                     anchor="w").grid(row=row, column=0, columnspan=2,
                                      sticky="w", padx=8, pady=(10, 2))
            row += 1
            ttk.Separator(self, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="ew", padx=6)
            row += 1
            for key, desc in entries:
                tk.Label(self, text=key, font=("TkFixedFont", 9),
                         fg="#0044AA", anchor="e", width=30).grid(
                    row=row, column=0, sticky="e", **pad)
                tk.Label(self, text=desc, anchor="w").grid(
                    row=row, column=1, sticky="w", **pad)
                row += 1

        tk.Button(self, text="Close", command=self.destroy,
                  width=10).grid(row=row, column=0, columnspan=2, pady=10)
        self.columnconfigure(1, weight=1)
