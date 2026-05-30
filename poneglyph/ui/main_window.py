"""Main application window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class MainWindow:
    """Root Tkinter window — hosts the notebook of panels."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Poneglyph — Substation Load Test Platform")
        root.geometry("1280x800")
        root.minsize(900, 600)

        self._build_menu()
        self._build_layout()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project…", accelerator="Ctrl+N")
        file_menu.add_command(label="Open Project…", accelerator="Ctrl+O")
        file_menu.add_command(label="Save",           accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export Report…")
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        sim_menu = tk.Menu(menubar, tearoff=0)
        sim_menu.add_command(label="Run Power Flow")
        sim_menu.add_command(label="Network Editor…")
        menubar.add_cascade(label="Simulation", menu=sim_menu)

        self.root.config(menu=menubar)

    def _build_layout(self) -> None:
        # Top status bar
        self._status_var = tk.StringVar(value="No project loaded.")
        status = ttk.Label(self.root, textvariable=self._status_var, anchor="w", relief="sunken")
        status.pack(side=tk.BOTTOM, fill=tk.X, ipady=2)

        # Main notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._add_placeholder_tab("One-Line Diagram")
        self._add_placeholder_tab("Measurement Points")
        self._add_placeholder_tab("Field Readings")
        self._add_placeholder_tab("Comparison Report")

    def _add_placeholder_tab(self, title: str) -> None:
        frame = ttk.Frame(self.notebook)
        ttk.Label(frame, text=f"{title} — coming soon", font=("TkDefaultFont", 12)).pack(
            expand=True
        )
        self.notebook.add(frame, text=title)

    def set_status(self, message: str) -> None:
        self._status_var.set(message)
