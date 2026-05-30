"""Main application window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from poneglyph.ui.oneline import BranchLayout, BusLayout, OneLineDiagram


class MainWindow:
    """Root Tkinter window — hosts the notebook of panels."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Poneglyph — Substation Load Test Platform")
        root.geometry("1280x800")
        root.minsize(900, 600)

        self._build_menu()
        self._build_layout()
        self._load_demo_network()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project…",  accelerator="Ctrl+N")
        file_menu.add_command(label="Open Project…", accelerator="Ctrl+O")
        file_menu.add_command(label="Save",           accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export Report…")
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        sim_menu = tk.Menu(menubar, tearoff=0)
        sim_menu.add_command(label="Run Power Flow",  command=self._run_power_flow)
        sim_menu.add_command(label="Network Editor…")
        menubar.add_cascade(label="Simulation", menu=sim_menu)

        self.root.config(menu=menubar)

    def _build_layout(self) -> None:
        self._status_var = tk.StringVar(value="No project loaded.")
        status = ttk.Label(
            self.root, textvariable=self._status_var,
            anchor="w", relief="sunken",
        )
        status.pack(side=tk.BOTTOM, fill=tk.X, ipady=2)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Tab 1 — One-line diagram
        self.diagram = OneLineDiagram(self.notebook, on_select=self._on_device_select)
        self.notebook.add(self.diagram, text="One-Line Diagram")

        # Remaining tabs — placeholders for now
        for title in ("Measurement Points", "Field Readings", "Comparison Report"):
            frame = ttk.Frame(self.notebook)
            ttk.Label(frame, text=f"{title} — coming soon", font=("TkDefaultFont", 12)).pack(expand=True)
            self.notebook.add(frame, text=title)

    def _load_demo_network(self) -> None:
        """Load a simple 3-bus demo so the diagram isn't empty on first launch."""
        from poneglyph.simulation.network import Bus, Branch, Network
        from poneglyph.simulation.devices.instrument_transformer import CT, VT

        net = Network(name="Demo Substation", base_mva=100)

        # Buses
        hv  = Bus("BUS-HV",  "132kV Bus",    base_kv=132)
        mv  = Bus("BUS-MV",  "33kV Bus",      base_kv=33)
        lv  = Bus("BUS-LV",  "11kV Bus",      base_kv=11)
        net.add_bus(hv)
        net.add_bus(mv)
        net.add_bus(lv)

        # Branches
        xfmr1 = Branch("XFMR-1", "132/33kV Tx",  "BUS-HV", "BUS-MV", r_pu=0.01, x_pu=0.10)
        xfmr2 = Branch("XFMR-2", "33/11kV Tx",   "BUS-MV", "BUS-LV", r_pu=0.01, x_pu=0.08)
        feeder = Branch("FEEDER-1", "Feeder 1",   "BUS-LV", "BUS-LV", r_pu=0.02, x_pu=0.05, closed=True)
        net.add_branch(xfmr1)
        net.add_branch(xfmr2)

        # Instrument transformers
        cts = {
            "CT-HV": CT("CT-HV",  "CT1 HV",  "XFMR-1", ratio=200),
            "CT-MV": CT("CT-MV",  "CT2 MV",  "XFMR-2", ratio=100),
        }
        vts = {
            "VT-HV": VT("VT-HV", "VT1 HV", "BUS-HV", ratio=1200),
            "VT-LV": VT("VT-LV", "VT2 LV", "BUS-LV", ratio=100),
        }

        # Layout positions (world coordinates)
        bus_layouts = {
            "BUS-HV": BusLayout("BUS-HV", x=300, y=100, length=200),
            "BUS-MV": BusLayout("BUS-MV", x=300, y=280, length=180),
            "BUS-LV": BusLayout("BUS-LV", x=300, y=440, length=160),
        }
        branch_layouts = {
            "XFMR-1": BranchLayout("XFMR-1", is_transformer=True,  ct_ids=["CT-HV"]),
            "XFMR-2": BranchLayout("XFMR-2", is_transformer=True,  ct_ids=["CT-MV"]),
        }

        self.diagram.load_network(net, bus_layouts, branch_layouts, cts, vts)
        self._status_var.set("Demo network loaded — 3 buses, 2 transformers.")

    def _on_device_select(self, sel) -> None:
        if sel:
            self._status_var.set(f"Selected: {sel[0]}  {sel[1]}")
        else:
            self._status_var.set("Ready.")

    def _run_power_flow(self) -> None:
        self._status_var.set("Power flow — not yet wired up.")

    def set_status(self, message: str) -> None:
        self._status_var.set(message)
