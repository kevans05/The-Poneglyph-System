"""Log Pose — main UI panel for the P&C Equipment Load Test module."""
from __future__ import annotations

import csv
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

from .sea_chart import MeasurementPoint, VectorGroup, LoadTestRecord
from .vivre_card import check_forcing_neutral, differential_deviation


class LogPosePanel(tk.Frame):
    """P&C Load Test panel — Setup, Measurements, Vector Analysis, Differential, History."""

    def __init__(self, parent: tk.Widget, diagram=None, project_path=None, project_name: str = "") -> None:
        super().__init__(parent)
        self._diagram = diagram
        self._project_path = project_path
        self._project_name = project_name

        self._points: list[MeasurementPoint] = []
        self._blocked = tk.BooleanVar(value=False)

        # StringVars for setup fields
        self._wo_var = tk.StringVar()
        self._tech_var = tk.StringVar()
        self._note_var = tk.StringVar()

        # Measurement entry vars: keyed by index (row) -> {col: StringVar}
        self._meas_vars: dict[int, dict[str, tk.StringVar]] = {}

        # Vector analysis vars
        self._vec_a_mag = tk.StringVar(value="0.0")
        self._vec_a_ang = tk.StringVar(value="0.0")
        self._vec_b_mag = tk.StringVar(value="0.0")
        self._vec_b_ang = tk.StringVar(value="120.0")
        self._vec_c_mag = tk.StringVar(value="0.0")
        self._vec_c_ang = tk.StringVar(value="240.0")
        self._vec_n_mag = tk.StringVar(value="0.0")
        self._vec_n_ang = tk.StringVar(value="0.0")
        self._vec_result_var = tk.StringVar(value="—")

        # Forcing neutral vars
        self._fn_a_mag = tk.StringVar(value="0.0")
        self._fn_a_ang = tk.StringVar(value="0.0")
        self._fn_n_mag = tk.StringVar(value="0.0")
        self._fn_n_ang = tk.StringVar(value="180.0")
        self._fn_result_var = tk.StringVar(value="—")

        # Differential wizard
        self._diff_cttbs: list[str] = []
        self._diff_step = 0
        self._diff_points: list[MeasurementPoint] = []
        self._diff_mag_var = tk.StringVar(value="0.0")
        self._diff_ang_var = tk.StringVar(value="0.0")

        self._build_ui()

        if self._diagram is not None:
            self._load_from_sld()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True)

        self._build_setup_tab()
        self._build_measurements_tab()
        self._build_vector_tab()
        self._build_differential_tab()
        self._build_history_tab()

        self._nb.bind("<<NotebookTabChanged>>", self._on_subtab_changed)

    # ── Sub-tab 1: Setup ──────────────────────────────────────────────────

    def _build_setup_tab(self) -> None:
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text="Setup")

        canvas = tk.Canvas(frame)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)

        pad = {"padx": 10, "pady": 4}

        # WO / Project info
        info_frame = tk.LabelFrame(inner, text="Job Information", padx=8, pady=6)
        info_frame.pack(fill=tk.X, **pad)

        tk.Label(info_frame, text="WO / Project Number:").grid(row=0, column=0, sticky="e", pady=3)
        tk.Entry(info_frame, textvariable=self._wo_var, width=30).grid(row=0, column=1, sticky="w", padx=6)

        tk.Label(info_frame, text="Technologist Name:").grid(row=1, column=0, sticky="e", pady=3)
        tk.Entry(info_frame, textvariable=self._tech_var, width=30).grid(row=1, column=1, sticky="w", padx=6)

        # Protection blocking section
        block_frame = tk.LabelFrame(
            inner, text="⚠  Protection Blocking",
            fg="red", font=("TkDefaultFont", 10, "bold"),
            padx=8, pady=6, relief="ridge", bd=3,
        )
        block_frame.pack(fill=tk.X, **pad)

        tk.Label(
            block_frame,
            text="⚠  Protection Blocking Required",
            font=("TkDefaultFont", 11, "bold"), fg="red",
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            block_frame,
            text="Confirm FVO/SIO contact and SEL Relay Mirrored Bits blocked",
            wraplength=560, justify="left",
        ).pack(anchor="w")

        tk.Label(block_frame, text="Blocking Note (who contacted, reference #):").pack(anchor="w", pady=(6, 2))
        tk.Entry(block_frame, textvariable=self._note_var, width=60).pack(anchor="w", fill=tk.X)

        chk = tk.Checkbutton(
            block_frame,
            text="Protection has been blocked — I confirm",
            variable=self._blocked,
            font=("TkDefaultFont", 10, "bold"),
            fg="darkred",
            command=self._on_blocking_changed,
        )
        chk.pack(anchor="w", pady=(8, 0))

        # Meter configuration reminders
        meter_frame = tk.LabelFrame(
            inner, text="Meter Configuration Reminders",
            bg="#FFFDE7", padx=8, pady=6, relief="ridge", bd=2,
        )
        meter_frame.pack(fill=tk.X, **pad)

        reminders = [
            "• Connect reference lead to Channel 1",
            "• Set Channel 2 to lag by 0°–360°",
            "• Red side of current jack towards CT",
        ]
        for r in reminders:
            tk.Label(meter_frame, text=r, bg="#FFFDE7", anchor="w").pack(anchor="w", pady=1)

        # Load from SLD button
        tk.Button(
            inner, text="Load Equipment from SLD",
            command=self._load_from_sld, padx=10,
        ).pack(anchor="w", **pad)

    # ── Sub-tab 2: Measurements ────────────────────────────────────────────

    def _build_measurements_tab(self) -> None:
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text="Measurements")
        self._meas_tab_frame = frame

        # Locked overlay label (shown when not blocked)
        self._lock_label = tk.Label(
            frame,
            text="⛔  Measurements locked — confirm protection blocking in Setup tab",
            font=("TkDefaultFont", 14, "bold"),
            fg="white", bg="red",
            wraplength=500,
        )

        # Scrollable grid container
        self._meas_outer = tk.Frame(frame)

        self._meas_canvas = tk.Canvas(self._meas_outer)
        vsb = ttk.Scrollbar(self._meas_outer, orient="vertical", command=self._meas_canvas.yview)
        hsb = ttk.Scrollbar(self._meas_outer, orient="horizontal", command=self._meas_canvas.xview)
        self._meas_canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._meas_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._meas_grid_frame = tk.Frame(self._meas_canvas)
        self._meas_win_id = self._meas_canvas.create_window((0, 0), window=self._meas_grid_frame, anchor="nw")

        def _on_cfg(event):
            self._meas_canvas.configure(scrollregion=self._meas_canvas.bbox("all"))

        self._meas_grid_frame.bind("<Configure>", _on_cfg)

        btn_bar = tk.Frame(frame)
        tk.Button(btn_bar, text="Recalculate", command=self._recalculate).pack(side=tk.LEFT, padx=4, pady=4)
        self._meas_btn_bar = btn_bar

        self._refresh_measurements_tab()

    def _refresh_measurements_tab(self) -> None:
        frame = self._meas_tab_frame
        locked = not self._blocked.get()

        if locked:
            self._meas_outer.pack_forget()
            self._meas_btn_bar.pack_forget()
            self._lock_label.place(relx=0.5, rely=0.5, anchor="center")
            return

        self._lock_label.place_forget()
        self._meas_btn_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self._meas_outer.pack(fill=tk.BOTH, expand=True)

        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        # Destroy old widgets
        for w in self._meas_grid_frame.winfo_children():
            w.destroy()
        self._meas_vars.clear()

        headers = ["Device", "Type", "Pred Mag", "Pred Ang°", "Meas Mag", "Meas Ang°", "Δ Mag", "Δ Ang°", "Status"]
        col_widths = [10, 8, 9, 9, 9, 9, 8, 8, 7]

        for col, (hdr, w) in enumerate(zip(headers, col_widths)):
            lbl = tk.Label(
                self._meas_grid_frame, text=hdr, font=("TkDefaultFont", 9, "bold"),
                relief="ridge", width=w, bg="#D0D0D0",
            )
            lbl.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)

        for row_idx, pt in enumerate(self._points):
            r = row_idx + 1
            bg = "#FFFFFF" if row_idx % 2 == 0 else "#F5F5F5"

            def _label(text, col, background=bg):
                tk.Label(
                    self._meas_grid_frame, text=text, relief="flat",
                    bg=background, anchor="w", padx=4,
                ).grid(row=r, column=col, sticky="nsew", padx=1, pady=1)

            _label(pt.device_name, 0)
            _label(pt.device_type.upper(), 1)
            _label(f"{pt.pred_magnitude:.2f}", 2)
            _label(f"{pt.pred_angle:.1f}", 3)

            mag_var = tk.StringVar(value=f"{pt.meas_magnitude:.2f}")
            ang_var = tk.StringVar(value=f"{pt.meas_angle:.1f}")
            self._meas_vars[row_idx] = {"mag": mag_var, "ang": ang_var}

            tk.Entry(self._meas_grid_frame, textvariable=mag_var, width=9).grid(
                row=r, column=4, sticky="nsew", padx=1, pady=1)
            tk.Entry(self._meas_grid_frame, textvariable=ang_var, width=9).grid(
                row=r, column=5, sticky="nsew", padx=1, pady=1)

            # Delta cols
            delta_mag_lbl = tk.Label(
                self._meas_grid_frame, text=f"{pt.magnitude_delta:.4f}",
                relief="flat", bg=bg, anchor="center",
            )
            delta_mag_lbl.grid(row=r, column=6, sticky="nsew", padx=1, pady=1)

            delta_ang_lbl = tk.Label(
                self._meas_grid_frame, text=f"{pt.angle_delta:.2f}",
                relief="flat", bg=bg, anchor="center",
            )
            delta_ang_lbl.grid(row=r, column=7, sticky="nsew", padx=1, pady=1)

            if pt.flagged:
                status_text, status_fg = "⚠ FLAG", "red"
            else:
                status_text, status_fg = "✓ OK", "green"

            tk.Label(
                self._meas_grid_frame, text=status_text,
                fg=status_fg, font=("TkDefaultFont", 9, "bold"),
                relief="flat", bg=bg,
            ).grid(row=r, column=8, sticky="nsew", padx=1, pady=1)

    def _recalculate(self) -> None:
        """Read entry values back into MeasurementPoint objects then rebuild grid."""
        for idx, pt in enumerate(self._points):
            if idx in self._meas_vars:
                try:
                    pt.meas_magnitude = float(self._meas_vars[idx]["mag"].get())
                except ValueError:
                    pass
                try:
                    pt.meas_angle = float(self._meas_vars[idx]["ang"].get()) % 360
                except ValueError:
                    pass
        self._rebuild_grid()

    # ── Sub-tab 3: Vector Analysis ─────────────────────────────────────────

    def _build_vector_tab(self) -> None:
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text="Vector Analysis")

        canvas = tk.Canvas(frame)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _cfg)
        canvas.bind("<Configure>", _cfg)

        pad = {"padx": 12, "pady": 6}

        # 3I0 / V0 calculator
        vg_frame = tk.LabelFrame(inner, text="3I₀ / V₀ Calculator", padx=8, pady=6)
        vg_frame.pack(fill=tk.X, **pad)

        headers = ["Phase", "Magnitude", "Angle (°)"]
        for c, h in enumerate(headers):
            tk.Label(vg_frame, text=h, font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=c, padx=6, pady=2)

        phase_rows = [
            ("A", self._vec_a_mag, self._vec_a_ang),
            ("B", self._vec_b_mag, self._vec_b_ang),
            ("C", self._vec_c_mag, self._vec_c_ang),
            ("Neutral (meas.)", self._vec_n_mag, self._vec_n_ang),
        ]
        for r, (label, mag_v, ang_v) in enumerate(phase_rows, 1):
            tk.Label(vg_frame, text=label, width=14, anchor="e").grid(row=r, column=0, padx=6, pady=2)
            tk.Entry(vg_frame, textvariable=mag_v, width=12).grid(row=r, column=1, padx=6, pady=2)
            tk.Entry(vg_frame, textvariable=ang_v, width=12).grid(row=r, column=2, padx=6, pady=2)

        tk.Button(vg_frame, text="Calculate", command=self._calc_vector).grid(
            row=5, column=0, columnspan=3, pady=6)

        self._vg_result_frame = tk.Frame(vg_frame, relief="sunken", bd=1)
        self._vg_result_frame.grid(row=6, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
        self._vg_result_lbl = tk.Label(
            self._vg_result_frame, textvariable=self._vec_result_var,
            font=("TkDefaultFont", 10), anchor="w", justify="left", padx=8,
        )
        self._vg_result_lbl.pack(anchor="w", fill=tk.X)

        # Forcing neutral section
        fn_frame = tk.LabelFrame(inner, text="Forcing Neutral Test", padx=8, pady=6)
        fn_frame.pack(fill=tk.X, **pad)

        tk.Label(
            fn_frame,
            text="Short/isolate B & C phases. Measure A-phase and Neutral simultaneously.",
            wraplength=520, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        fn_headers = ["", "Magnitude", "Angle (°)"]
        for c, h in enumerate(fn_headers):
            tk.Label(fn_frame, text=h, font=("TkDefaultFont", 9, "bold")).grid(
                row=1, column=c, padx=6, pady=2)

        fn_rows = [
            ("A-Phase", self._fn_a_mag, self._fn_a_ang),
            ("Neutral", self._fn_n_mag, self._fn_n_ang),
        ]
        for r, (label, mag_v, ang_v) in enumerate(fn_rows, 2):
            tk.Label(fn_frame, text=label, width=14, anchor="e").grid(row=r, column=0, padx=6, pady=2)
            tk.Entry(fn_frame, textvariable=mag_v, width=12).grid(row=r, column=1, padx=6, pady=2)
            tk.Entry(fn_frame, textvariable=ang_v, width=12).grid(row=r, column=2, padx=6, pady=2)

        tk.Button(fn_frame, text="Check", command=self._check_forcing_neutral).grid(
            row=4, column=0, columnspan=3, pady=6)

        self._fn_result_lbl = tk.Label(
            fn_frame, textvariable=self._fn_result_var,
            font=("TkDefaultFont", 10), anchor="w", justify="left", padx=8,
            relief="sunken", bd=1,
        )
        self._fn_result_lbl.grid(row=5, column=0, columnspan=3, sticky="ew", padx=4, pady=4)

    def _calc_vector(self) -> None:
        try:
            vg = VectorGroup(
                a_mag=float(self._vec_a_mag.get()), a_ang=float(self._vec_a_ang.get()),
                b_mag=float(self._vec_b_mag.get()), b_ang=float(self._vec_b_ang.get()),
                c_mag=float(self._vec_c_mag.get()), c_ang=float(self._vec_c_ang.get()),
                n_mag=float(self._vec_n_mag.get()), n_ang=float(self._vec_n_ang.get()),
            )
        except ValueError:
            messagebox.showerror("Input error", "All fields must be numeric.", parent=self)
            return

        calc_mag, calc_ang = vg.calculated_neutral()
        import math
        def ang_diff(a, b):
            d = (a - b) % 360
            return d if d <= 180 else d - 360

        mag_delta = round(calc_mag - vg.n_mag, 4)
        ang_delta = round(ang_diff(calc_ang, vg.n_ang), 2)
        pass_mag = abs(mag_delta) <= calc_mag * 0.05 if calc_mag > 0 else abs(mag_delta) < 0.01
        pass_ang = abs(ang_delta) <= 5.0
        verdict = "PASS" if (pass_mag and pass_ang) else "FAIL"
        colour = "green" if verdict == "PASS" else "red"

        result = (
            f"Calculated Neutral:  {calc_mag:.4f} ∠ {calc_ang:.1f}°\n"
            f"Measured Neutral:    {vg.n_mag:.4f} ∠ {vg.n_ang:.1f}°\n"
            f"Δ Magnitude: {mag_delta:+.4f}   Δ Angle: {ang_delta:+.2f}°\n"
            f"Result: {verdict}"
        )
        self._vec_result_var.set(result)
        self._vg_result_lbl.config(fg=colour)

    def _check_forcing_neutral(self) -> None:
        try:
            a_pt = MeasurementPoint(
                device_id="A", device_name="A-Phase", device_type="ct",
                meas_magnitude=float(self._fn_a_mag.get()),
                meas_angle=float(self._fn_a_ang.get()),
            )
            n_pt = MeasurementPoint(
                device_id="N", device_name="Neutral", device_type="ct",
                meas_magnitude=float(self._fn_n_mag.get()),
                meas_angle=float(self._fn_n_ang.get()),
            )
        except ValueError:
            messagebox.showerror("Input error", "All fields must be numeric.", parent=self)
            return

        res = check_forcing_neutral(a_pt, n_pt)
        mag_ok = "PASS" if res["mag_ok"] else "FAIL"
        ang_ok = "PASS" if res["ang_ok"] else "FAIL"
        overall = "PASS" if (res["mag_ok"] and res["ang_ok"]) else "FAIL"
        colour = "green" if overall == "PASS" else "red"

        result = (
            f"Magnitude difference: {res['mag_diff']:.4f}  [{mag_ok}]\n"
            f"Angle difference from 180°: {abs(abs(res['ang_diff']) - 180):.2f}°  [{ang_ok}]\n"
            f"Overall: {overall}"
        )
        self._fn_result_var.set(result)
        self._fn_result_lbl.config(fg=colour)

    # ── Sub-tab 4: Differential ────────────────────────────────────────────

    def _build_differential_tab(self) -> None:
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text="Differential")
        self._diff_tab_frame = frame

        top = tk.Frame(frame)
        top.pack(fill=tk.X, padx=10, pady=6)

        tk.Label(top, text="CTTB Devices:", font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)

        self._diff_listbox = tk.Listbox(frame, height=5, selectmode=tk.BROWSE)
        self._diff_listbox.pack(fill=tk.X, padx=10, pady=(0, 4))

        # Wizard area
        wizard_frame = tk.LabelFrame(frame, text="Differential Wizard", padx=8, pady=6)
        wizard_frame.pack(fill=tk.X, padx=10, pady=4)

        self._diff_step_lbl = tk.Label(
            wizard_frame, text="Load equipment from SLD to begin.",
            font=("TkDefaultFont", 10), wraplength=480,
        )
        self._diff_step_lbl.pack(anchor="w", pady=4)

        entry_row = tk.Frame(wizard_frame)
        entry_row.pack(anchor="w", pady=2)
        tk.Label(entry_row, text="Relay Reading — Magnitude:").pack(side=tk.LEFT)
        tk.Entry(entry_row, textvariable=self._diff_mag_var, width=10).pack(side=tk.LEFT, padx=4)
        tk.Label(entry_row, text="Angle (°):").pack(side=tk.LEFT)
        tk.Entry(entry_row, textvariable=self._diff_ang_var, width=10).pack(side=tk.LEFT, padx=4)

        nav_row = tk.Frame(wizard_frame)
        nav_row.pack(anchor="w", pady=4)
        tk.Button(nav_row, text="◀ Previous", command=self._diff_prev).pack(side=tk.LEFT, padx=4)
        tk.Button(nav_row, text="Next ▶", command=self._diff_next).pack(side=tk.LEFT, padx=4)

        self._diff_result_lbl = tk.Label(
            frame, text="", font=("TkDefaultFont", 11, "bold"), anchor="w",
        )
        self._diff_result_lbl.pack(fill=tk.X, padx=10, pady=4)

        self._diff_refresh_ui()

    def _diff_refresh_ui(self) -> None:
        cttbs = self._diff_cttbs
        n = len(cttbs)
        if n == 0:
            self._diff_step_lbl.config(text="No CTTB devices found. Load equipment from SLD in the Setup tab.")
            return

        step = self._diff_step
        if step >= n:
            # Show result
            self._diff_step_lbl.config(
                text=f"All {n} steps complete. Click 'Next' to calculate residual."
            )
            return

        self._diff_step_lbl.config(
            text=f"Step {step + 1} of {n} — Short/isolate all CTTBs except [{cttbs[step]}].\n"
                 f"Enter the relay differential reading:"
        )

        # Restore any previously entered value for this step
        if step < len(self._diff_points):
            pt = self._diff_points[step]
            self._diff_mag_var.set(f"{pt.meas_magnitude:.2f}")
            self._diff_ang_var.set(f"{pt.meas_angle:.1f}")

    def _diff_prev(self) -> None:
        if self._diff_step > 0:
            self._diff_step -= 1
            self._diff_result_lbl.config(text="")
            self._diff_refresh_ui()

    def _diff_next(self) -> None:
        n = len(self._diff_cttbs)
        if n == 0:
            return

        if self._diff_step < n:
            # Record current step
            cttb_name = self._diff_cttbs[self._diff_step]
            try:
                mag = float(self._diff_mag_var.get())
                ang = float(self._diff_ang_var.get()) % 360
            except ValueError:
                messagebox.showerror("Input error", "Magnitude and Angle must be numeric.", parent=self)
                return

            pt = MeasurementPoint(
                device_id=cttb_name, device_name=cttb_name, device_type="cttb",
                meas_magnitude=mag, meas_angle=ang,
            )
            if self._diff_step < len(self._diff_points):
                self._diff_points[self._diff_step] = pt
            else:
                self._diff_points.append(pt)

            self._diff_step += 1
            self._diff_mag_var.set("0.0")
            self._diff_ang_var.set("0.0")

        if self._diff_step >= n:
            # Calculate
            residual = differential_deviation(self._diff_points)
            verdict = "PASS" if residual < 0.05 else "FAIL"
            colour = "green" if verdict == "PASS" else "red"
            self._diff_result_lbl.config(
                text=f"Differential residual: {residual:.4f} A  →  {verdict}",
                fg=colour,
            )
        else:
            self._diff_result_lbl.config(text="")
            self._diff_refresh_ui()

    # ── Sub-tab 5: History ─────────────────────────────────────────────────

    def _build_history_tab(self) -> None:
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text="History")

        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("timestamp", "wo_number", "technologist", "device_count", "notes")
        self._hist_tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self._hist_tree.heading("timestamp",   text="Date / Time")
        self._hist_tree.heading("wo_number",   text="WO #")
        self._hist_tree.heading("technologist", text="Technologist")
        self._hist_tree.heading("device_count", text="Devices")
        self._hist_tree.heading("notes",        text="Notes")
        self._hist_tree.column("timestamp",    width=160)
        self._hist_tree.column("wo_number",    width=120)
        self._hist_tree.column("technologist", width=140)
        self._hist_tree.column("device_count", width=60)
        self._hist_tree.column("notes",        width=200)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=vsb.set)
        self._hist_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        btn_row = tk.Frame(frame)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=4)

        tk.Button(btn_row, text="Save Current Test", command=self._save_test).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="Load Selected",     command=self._load_selected_test).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="Export CSV",        command=self._export_csv).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="Refresh",           command=self._refresh_history).pack(side=tk.RIGHT, padx=4)

    # ── SLD loading ────────────────────────────────────────────────────────

    def _load_from_sld(self) -> None:
        if self._diagram is None:
            return
        d = self._diagram
        self._points.clear()

        device_groups = [
            (getattr(d, "_cts",        {}), "ct"),
            (getattr(d, "_vts",        {}), "vt"),
            (getattr(d, "_cttbs",      {}), "cttb"),
            (getattr(d, "_testblocks", {}), "testblock"),
            (getattr(d, "_relays",     {}), "relay"),
        ]
        for dev_dict, dev_type in device_groups:
            for dev_id, dev in dev_dict.items():
                name = getattr(dev, "name", dev_id)
                self._points.append(MeasurementPoint(
                    device_id=dev_id,
                    device_name=name,
                    device_type=dev_type,
                    pred_magnitude=0.0,
                    pred_angle=0.0,
                ))

        # Update differential CTTB list
        self._diff_cttbs = [
            getattr(dev, "name", dev_id)
            for dev_id, dev in getattr(d, "_cttbs", {}).items()
        ]
        self._diff_step = 0
        self._diff_points.clear()

        # Refresh differential listbox
        if hasattr(self, "_diff_listbox"):
            self._diff_listbox.delete(0, tk.END)
            for name in self._diff_cttbs:
                self._diff_listbox.insert(tk.END, name)
            self._diff_refresh_ui()

        # Rebuild measurement grid if unlocked
        if self._blocked.get() and hasattr(self, "_meas_grid_frame"):
            self._rebuild_grid()

    def _on_blocking_changed(self) -> None:
        self._refresh_measurements_tab()

    def _on_subtab_changed(self, event) -> None:
        idx = self._nb.index(self._nb.select())
        if idx == 1:
            self._refresh_measurements_tab()
        elif idx == 4:
            self._refresh_history()

    # ── Persistence ────────────────────────────────────────────────────────

    def _current_record(self) -> LoadTestRecord:
        """Snapshot the current UI state into a LoadTestRecord."""
        # Flush entry values into points first
        for idx, pt in enumerate(self._points):
            if idx in self._meas_vars:
                try:
                    pt.meas_magnitude = float(self._meas_vars[idx]["mag"].get())
                except ValueError:
                    pass
                try:
                    pt.meas_angle = float(self._meas_vars[idx]["ang"].get()) % 360
                except ValueError:
                    pass

        return LoadTestRecord(
            id=str(uuid.uuid4()),
            project_name=self._project_name,
            wo_number=self._wo_var.get(),
            technologist=self._tech_var.get(),
            protection_blocked=self._blocked.get(),
            blocking_note=self._note_var.get(),
            points=[asdict(p) for p in self._points],
            vector_groups=[],
            notes="",
        )

    def _save_test(self) -> None:
        if not self._project_path:
            messagebox.showwarning(
                "No project file",
                "Please save the project (File → Save) before saving a load test record.",
                parent=self,
            )
            return
        record = self._current_record()
        try:
            from poneglyph.io.project import save_load_test
            save_load_test(Path(self._project_path), asdict(record))
            self._refresh_history()
            messagebox.showinfo("Saved", f"Load test saved (id={record.id[:8]}…)", parent=self)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)

    def _refresh_history(self) -> None:
        if not self._project_path:
            return
        try:
            from poneglyph.io.project import list_load_tests
            records = list_load_tests(Path(self._project_path))
        except Exception:
            return

        tree = self._hist_tree
        for item in tree.get_children():
            tree.delete(item)

        for rec in records:
            ts = rec.get("timestamp", "")[:19].replace("T", " ")
            tree.insert("", tk.END, iid=rec.get("id", ""), values=(
                ts,
                rec.get("wo_number", ""),
                rec.get("technologist", ""),
                len(rec.get("points", [])),
                rec.get("notes", ""),
            ))

    def _load_selected_test(self) -> None:
        sel = self._hist_tree.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Select a record first.", parent=self)
            return
        rec_id = sel[0]

        try:
            from poneglyph.io.project import list_load_tests
            records = list_load_tests(Path(self._project_path))
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc), parent=self)
            return

        rec = next((r for r in records if r.get("id") == rec_id), None)
        if rec is None:
            messagebox.showerror("Not found", "Record not found.", parent=self)
            return

        self._wo_var.set(rec.get("wo_number", ""))
        self._tech_var.set(rec.get("technologist", ""))
        self._note_var.set(rec.get("blocking_note", ""))
        self._blocked.set(rec.get("protection_blocked", False))

        self._points.clear()
        for p_dict in rec.get("points", []):
            self._points.append(MeasurementPoint(**p_dict))

        self._meas_vars.clear()
        if self._blocked.get():
            self._rebuild_grid()
        self._refresh_measurements_tab()
        messagebox.showinfo("Loaded", "Load test record restored.", parent=self)

    def _export_csv(self) -> None:
        sel = self._hist_tree.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Select a record first.", parent=self)
            return
        rec_id = sel[0]

        try:
            from poneglyph.io.project import list_load_tests
            records = list_load_tests(Path(self._project_path))
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return

        rec = next((r for r in records if r.get("id") == rec_id), None)
        if rec is None:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*")],
            title="Export Load Test CSV",
            parent=self,
        )
        if not path:
            return

        try:
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    "device_id", "device_name", "device_type", "channel",
                    "pred_magnitude", "pred_angle",
                    "meas_magnitude", "meas_angle",
                ])
                for p in rec.get("points", []):
                    writer.writerow([
                        p.get("device_id"), p.get("device_name"), p.get("device_type"),
                        p.get("channel"),
                        p.get("pred_magnitude"), p.get("pred_angle"),
                        p.get("meas_magnitude"), p.get("meas_angle"),
                    ])
            messagebox.showinfo("Exported", f"CSV saved to {path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

    # ── Project name update ────────────────────────────────────────────────

    def set_project(self, project_name: str = "", project_path=None) -> None:
        self._project_name = project_name
        if project_path is not None:
            self._project_path = project_path
        self._refresh_history()
