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
        self._build_toolbar()
        self._build_body()
        self._build_status()
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
        protect_menu.add_command(label="Relay",      command=lambda: self._set_protect_tool(TOOL_RELAY))
        protect_menu.add_command(label="Relay Wire", command=lambda: self._set_protect_tool(TOOL_RELAY_WIRE))
        protect_menu.add_separator()
        protect_menu.add_command(label="CT Wire (CT/CTTB)", command=lambda: self._set_protect_tool(TOOL_RELAY_WIRE_I))
        protect_menu.add_command(label="VT Wire (VT/FT)",   command=lambda: self._set_protect_tool(TOOL_RELAY_WIRE_V))
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

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)

        # View controls
        tk.Button(bar, text="⊕", width=3, relief="flat", font=("TkDefaultFont", 11),
                  command=lambda: self.diagram.zoom_in()).pack(side=tk.LEFT, padx=1, pady=2)
        tk.Button(bar, text="⊖", width=3, relief="flat", font=("TkDefaultFont", 11),
                  command=lambda: self.diagram.zoom_out()).pack(side=tk.LEFT, padx=1, pady=2)
        tk.Button(bar, text="⊡ Fit", relief="flat", padx=4,
                  command=lambda: self.diagram.fit_view()).pack(side=tk.LEFT, padx=2, pady=2)

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
        self.root.bind("w", lambda _e: self._toggle_tool(TOOL_RELAY_WIRE, self._set_protect_tool))
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
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        self.diagram = Diagram(pane, on_select=self._on_select,
                               on_status=self._set_status)
        pane.add(self.diagram, minsize=400, stretch="always")

        self.props = PropertiesPanel(pane, on_change=self.diagram.redraw)
        self.props.set_diagram(self.diagram)
        pane.add(self.props, minsize=180, width=220)

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
        self.diagram.redraw()

        if result.converged:
            self._set_status(f"Power flow converged in {result.iterations} iterations. "
                             f"Slack: {slack_bus}.")
        else:
            self._set_status(f"Power flow DID NOT converge after {result.iterations} iterations.")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)


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
