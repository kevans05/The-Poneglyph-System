"""Application entry point — wires together the simulation and UI."""

from __future__ import annotations

import tkinter as tk

from poneglyph.ui.main_window import MainWindow


class PoneglyphApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.window = MainWindow(self.root)

    def run(self) -> None:
        self.root.mainloop()
