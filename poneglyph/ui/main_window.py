"""Main application window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from poneglyph.ui.network_state import NetworkState, make_demo_state
from poneglyph.ui.oneline import OneLineDiagram


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Poneglyph — Substation Load Test Platform")
        root.geometry("1280x800")
        root.minsize(900, 600)

        self._state: Optional[NetworkState] = None
        self._editor_window = None

        self._build_menu()
        self._build_layout()
        self._load_demo()

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
        sim_menu.add_command(label="Run Power Flow",   command=self._run_power_flow)
        sim_menu.add_command(label="Network Editor…",  command=self._open_editor)
        menubar.add_cascade(label="Simulation", menu=sim_menu)

        self.root.config(menu=menubar)

    def _build_layout(self) -> None:
        self._status_var = tk.StringVar(value="No project loaded.")
        ttk.Label(
            self.root, textvariable=self._status_var,
            anchor="w", relief="sunken",
        ).pack(side=tk.BOTTOM, fill=tk.X, ipady=2)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.diagram = OneLineDiagram(self.notebook, on_select=self._on_device_select)
        self.notebook.add(self.diagram, text="One-Line Diagram")

        for title in ("Measurement Points", "Field Readings", "Comparison Report"):
            frame = ttk.Frame(self.notebook)
            ttk.Label(frame, text=f"{title} — coming soon",
                      font=("TkDefaultFont", 12)).pack(expand=True)
            self.notebook.add(frame, text=title)

    def _load_demo(self) -> None:
        self._state = make_demo_state()
        self._state.subscribe(self._on_state_changed)
        self._push_to_diagram()
        self._status_var.set("Demo network loaded — 3 buses, 2 transformers.")

    def _push_to_diagram(self) -> None:
        if self._state is None:
            return
        s = self._state
        self.diagram.load_network(
            s.network, s.bus_layouts, s.branch_layouts, s.cts, s.vts,
        )

    def _on_state_changed(self) -> None:
        """Called by NetworkState.notify() whenever the model changes."""
        self._push_to_diagram()
        n = self._state.network
        self._status_var.set(
            f"{n.name} — {len(n.buses)} buses, {len(n.branches)} branches, "
            f"{len(self._state.cts)} CTs, {len(self._state.vts)} VTs"
        )

    def _open_editor(self) -> None:
        from poneglyph.ui.network_editor import NetworkEditor
        # Reuse existing window if still open
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.lift()
            self._editor_window.focus_force()
            return
        self._editor_window = NetworkEditor(self.root, self._state)

    def _on_device_select(self, sel) -> None:
        if sel:
            self._status_var.set(f"Selected: {sel[0]}  {sel[1]}")

    def _run_power_flow(self) -> None:
        self._status_var.set("Power flow — not yet wired up.")

    def set_status(self, message: str) -> None:
        self._status_var.set(message)
