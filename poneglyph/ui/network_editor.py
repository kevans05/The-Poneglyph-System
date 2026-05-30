"""Network editor — Toplevel window for adding/editing/removing network elements.

Layout:
  ┌─────────────────┬────────────────────────────────────┐
  │  Element tree   │  Edit form (changes with selection) │
  │                 │                                    │
  │  ▶ Buses (3)    │  [fields for selected element]     │
  │  ▶ Branches (2) │                                    │
  │  ▶ CTs (2)      │  [Save]  [Delete]                  │
  │  ▶ VTs (2)      │                                    │
  │  [Add ▼]        │                                    │
  └─────────────────┴────────────────────────────────────┘
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from poneglyph.simulation.network import Branch, Bus
from poneglyph.simulation.devices.instrument_transformer import CT, VT
from poneglyph.ui.network_state import NetworkState
from poneglyph.ui.oneline import BranchLayout


# ── Palette ──────────────────────────────────────────────────────────────────

BG      = "#1A1A2E"
BG2     = "#16213E"
FG      = "#DDDDDD"
FG_DIM  = "#888888"
ACCENT  = "#0F3460"
SEL     = "#E94560"
ENTRY   = "#0D1B2A"
FONT    = ("Courier", 10)
FONT_B  = ("Courier", 10, "bold")
FONT_S  = ("Courier", 9)

# Tree node prefixes (used as item ids in treeview)
_GROUPS = {
    "buses":    "Buses",
    "branches": "Branches",
    "cts":      "CTs",
    "vts":      "VTs",
}


# ── Helper widgets ────────────────────────────────────────────────────────────

def _label(parent, text, bold=False):
    return tk.Label(
        parent, text=text, bg=BG2, fg=FG if bold else FG_DIM,
        font=FONT_B if bold else FONT_S, anchor="w",
    )


def _entry(parent, var):
    return tk.Entry(
        parent, textvariable=var,
        bg=ENTRY, fg=FG, insertbackground=FG,
        relief="flat", font=FONT, bd=4,
    )


def _combo(parent, var, values):
    cb = ttk.Combobox(
        parent, textvariable=var, values=values,
        font=FONT, state="readonly",
    )
    cb.configure(background=ENTRY)
    return cb


def _check(parent, text, var):
    return tk.Checkbutton(
        parent, text=text, variable=var,
        bg=BG2, fg=FG, selectcolor=ENTRY,
        activebackground=BG2, activeforeground=FG,
        font=FONT_S, anchor="w",
    )


def _section_label(parent, text):
    f = tk.Frame(parent, bg=ACCENT)
    tk.Label(f, text=text, bg=ACCENT, fg=FG, font=FONT_B, anchor="w", padx=6).pack(
        fill=tk.X, pady=2
    )
    return f


def _btn(parent, text, command, colour=ACCENT):
    return tk.Button(
        parent, text=text, command=command,
        bg=colour, fg=FG, activebackground=SEL, activeforeground=FG,
        relief="flat", font=FONT, padx=10, pady=4, cursor="hand2",
    )


# ── Network editor window ─────────────────────────────────────────────────────

class NetworkEditor(tk.Toplevel):
    """Floating editor window for the network model."""

    def __init__(self, parent: tk.Widget, state: NetworkState) -> None:
        super().__init__(parent)
        self.title("Network Editor")
        self.configure(bg=BG)
        self.geometry("820x560")
        self.minsize(700, 450)

        self._state  = state
        self._sel_type: Optional[str] = None   # "bus"|"branch"|"ct"|"vt"
        self._sel_id:   Optional[str] = None

        self._build_ui()
        self._refresh_tree()

        # Keep on top of main window but don't block it
        self.transient(parent)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BG, sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Left — element tree
        left = tk.Frame(pane, bg=BG2, width=220)
        pane.add(left, minsize=180)
        self._build_tree(left)

        # Right — edit form
        self._form_frame = tk.Frame(pane, bg=BG2)
        pane.add(self._form_frame, minsize=380)
        self._show_empty_form()

    def _build_tree(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Network Elements", bg=BG2, fg=FG, font=FONT_B).pack(
            fill=tk.X, padx=6, pady=(6, 2)
        )

        tree_frame = tk.Frame(parent, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4)

        style = ttk.Style()
        style.configure(
            "Editor.Treeview",
            background=ENTRY, foreground=FG, fieldbackground=ENTRY,
            font=FONT_S, rowheight=22,
        )
        style.configure("Editor.Treeview.Heading", background=ACCENT, foreground=FG, font=FONT_B)
        style.map("Editor.Treeview", background=[("selected", SEL)])

        self._tree = ttk.Treeview(
            tree_frame, style="Editor.Treeview",
            columns=("name",), show="tree headings", selectmode="browse",
        )
        self._tree.heading("#0",     text="ID",   anchor="w")
        self._tree.heading("name",   text="Name", anchor="w")
        self._tree.column("#0",      width=90,  stretch=False)
        self._tree.column("name",    width=110, stretch=True)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Group nodes
        for key, label in _GROUPS.items():
            self._tree.insert("", "end", iid=f"_grp_{key}", text=label, open=True)

        # Add button row
        btn_row = tk.Frame(parent, bg=BG2)
        btn_row.pack(fill=tk.X, padx=4, pady=4)
        add_menu_btn = _btn(btn_row, "+ Add…", self._show_add_menu)
        add_menu_btn.pack(fill=tk.X)

    # ── Tree population ───────────────────────────────────────────────────

    def _refresh_tree(self) -> None:
        net = self._state.network
        for key in _GROUPS:
            grp = f"_grp_{key}"
            for child in self._tree.get_children(grp):
                self._tree.delete(child)

        for bus_id, bus in net.buses.items():
            self._tree.insert("_grp_buses", "end", iid=f"bus:{bus_id}",
                              text=bus_id, values=(bus.name,))
        for br_id, br in net.branches.items():
            self._tree.insert("_grp_branches", "end", iid=f"branch:{br_id}",
                              text=br_id, values=(br.name,))
        for ct_id, ct in self._state.cts.items():
            self._tree.insert("_grp_cts", "end", iid=f"ct:{ct_id}",
                              text=ct_id, values=(ct.name,))
        for vt_id, vt in self._state.vts.items():
            self._tree.insert("_grp_vts", "end", iid=f"vt:{vt_id}",
                              text=vt_id, values=(vt.name,))

        # Update group labels with counts
        net = self._state.network
        counts = {
            "buses":    len(net.buses),
            "branches": len(net.branches),
            "cts":      len(self._state.cts),
            "vts":      len(self._state.vts),
        }
        for key, label in _GROUPS.items():
            self._tree.item(f"_grp_{key}", text=f"{label}  ({counts[key]})")

    # ── Tree selection → form ──────────────────────────────────────────────

    def _on_tree_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid.startswith("_grp_"):
            self._show_empty_form()
            return
        kind, elem_id = iid.split(":", 1)
        self._sel_type = kind
        self._sel_id   = elem_id
        if kind == "bus":
            self._show_bus_form(elem_id)
        elif kind == "branch":
            self._show_branch_form(elem_id)
        elif kind == "ct":
            self._show_ct_form(elem_id)
        elif kind == "vt":
            self._show_vt_form(elem_id)

    # ── Form builder helpers ───────────────────────────────────────────────

    def _clear_form(self) -> None:
        for w in self._form_frame.winfo_children():
            w.destroy()

    def _show_empty_form(self) -> None:
        self._clear_form()
        tk.Label(
            self._form_frame,
            text="Select an element to edit,\nor use  + Add…  to create one.",
            bg=BG2, fg=FG_DIM, font=FONT, justify=tk.CENTER,
        ).place(relx=0.5, rely=0.45, anchor="center")

    def _form_grid(self) -> tk.Frame:
        """Return a freshly cleared, padded form grid frame."""
        self._clear_form()
        f = tk.Frame(self._form_frame, bg=BG2)
        f.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        return f

    def _add_field(self, grid: tk.Frame, row: int, label: str, var: tk.Variable,
                   widget_factory=None) -> None:
        _label(grid, label).grid(row=row, column=0, sticky="w", pady=3)
        w = widget_factory(grid, var) if widget_factory else _entry(grid, var)
        w.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
        grid.columnconfigure(1, weight=1)

    def _save_delete_row(self, grid: tk.Frame, row: int,
                         save_cmd, delete_cmd) -> None:
        btn_row = tk.Frame(grid, bg=BG2)
        btn_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(16, 0))
        _btn(btn_row, "Save", save_cmd, colour="#1A6B3C").pack(side=tk.LEFT, padx=(0, 6))
        _btn(btn_row, "Delete", delete_cmd, colour="#8B1A1A").pack(side=tk.LEFT)

    # ── Bus form ──────────────────────────────────────────────────────────

    def _show_bus_form(self, bus_id: str, new: bool = False) -> None:
        bus = self._state.network.buses.get(bus_id)
        bl  = self._state.bus_layouts.get(bus_id)
        g = self._form_grid()
        _section_label(g, "Bus" if not new else "New Bus").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        v_id   = tk.StringVar(value=bus_id if not new else "")
        v_name = tk.StringVar(value=bus.name  if bus else "")
        v_kv   = tk.StringVar(value=str(bus.base_kv) if bus else "")
        v_x    = tk.StringVar(value=str(bl.x)        if bl  else "0")
        v_y    = tk.StringVar(value=str(bl.y)        if bl  else "0")
        v_len  = tk.StringVar(value=str(bl.length)   if bl  else "140")

        self._add_field(g, 1, "ID",       v_id,   lambda p, v: _entry(p, v) if new else tk.Label(p, textvariable=v, bg=ENTRY, fg=FG_DIM, font=FONT, anchor="w", relief="flat", bd=4))
        self._add_field(g, 2, "Name",     v_name)
        self._add_field(g, 3, "Base kV",  v_kv)
        self._add_field(g, 4, "Layout X", v_x)
        self._add_field(g, 5, "Layout Y", v_y)
        self._add_field(g, 6, "Bar Length", v_len)

        def save():
            try:
                bid  = v_id.get().strip()
                name = v_name.get().strip()
                kv   = float(v_kv.get())
                x    = float(v_x.get())
                y    = float(v_y.get())
                ln   = float(v_len.get())
            except ValueError as e:
                messagebox.showerror("Invalid input", str(e), parent=self)
                return
            if not bid or not name:
                messagebox.showerror("Invalid input", "ID and Name are required.", parent=self)
                return
            if new and bid in self._state.network.buses:
                messagebox.showerror("Duplicate ID", f"Bus '{bid}' already exists.", parent=self)
                return
            if new:
                self._state.add_bus(Bus(bid, name, kv), x=x, y=y, length=ln)
            else:
                bus.name    = name
                bus.base_kv = kv
                bl.x, bl.y, bl.length = x, y, ln
                self._state.notify()
            self._refresh_tree()
            self._tree.selection_set(f"bus:{bid}")

        def delete():
            if not messagebox.askyesno("Delete Bus", f"Remove bus '{bus_id}'?\nAll connected branches will also be removed.", parent=self):
                return
            for br_id in [k for k, v in self._state.network.branches.items()
                          if v.from_bus == bus_id or v.to_bus == bus_id]:
                self._state.remove_branch(br_id)
            self._state.remove_bus(bus_id)
            self._refresh_tree()
            self._show_empty_form()

        self._save_delete_row(g, 7, save, delete if not new else lambda: None)

    # ── Branch form ───────────────────────────────────────────────────────

    def _show_branch_form(self, branch_id: str, new: bool = False) -> None:
        br = self._state.network.branches.get(branch_id)
        bl = self._state.branch_layouts.get(branch_id, BranchLayout(branch_id))
        g  = self._form_grid()
        _section_label(g, "Branch" if not new else "New Branch").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        bus_ids = list(self._state.network.buses.keys())
        v_id    = tk.StringVar(value=branch_id if not new else "")
        v_name  = tk.StringVar(value=br.name     if br else "")
        v_from  = tk.StringVar(value=br.from_bus  if br else (bus_ids[0] if bus_ids else ""))
        v_to    = tk.StringVar(value=br.to_bus    if br else (bus_ids[-1] if bus_ids else ""))
        v_r     = tk.StringVar(value=str(br.r_pu) if br else "0.01")
        v_x     = tk.StringVar(value=str(br.x_pu) if br else "0.10")
        v_closed  = tk.BooleanVar(value=br.closed        if br else True)
        v_xfmr    = tk.BooleanVar(value=bl.is_transformer)
        v_breaker = tk.BooleanVar(value=bl.show_breaker_from)

        self._add_field(g, 1, "ID",          v_id,
                        lambda p, v: _entry(p, v) if new else tk.Label(p, textvariable=v, bg=ENTRY, fg=FG_DIM, font=FONT, anchor="w", relief="flat", bd=4))
        self._add_field(g, 2, "Name",        v_name)
        self._add_field(g, 3, "From Bus",    v_from, lambda p, v: _combo(p, v, bus_ids))
        self._add_field(g, 4, "To Bus",      v_to,   lambda p, v: _combo(p, v, bus_ids))
        self._add_field(g, 5, "R (pu)",      v_r)
        self._add_field(g, 6, "X (pu)",      v_x)
        _label(g, "").grid(row=7, column=0)
        _check(g, "Closed",        v_closed ).grid(row=7, column=1, sticky="w")
        _check(g, "Transformer",   v_xfmr   ).grid(row=8, column=1, sticky="w")
        _check(g, "Show Breaker",  v_breaker).grid(row=9, column=1, sticky="w")

        def save():
            try:
                bid   = v_id.get().strip()
                name  = v_name.get().strip()
                r_pu  = float(v_r.get())
                x_pu  = float(v_x.get())
            except ValueError as e:
                messagebox.showerror("Invalid input", str(e), parent=self)
                return
            if not bid or not name:
                messagebox.showerror("Invalid input", "ID and Name are required.", parent=self)
                return
            if new and bid in self._state.network.branches:
                messagebox.showerror("Duplicate ID", f"Branch '{bid}' already exists.", parent=self)
                return
            layout = BranchLayout(
                bid,
                show_breaker_from=v_breaker.get(),
                is_transformer=v_xfmr.get(),
                ct_ids=bl.ct_ids if not new else [],
            )
            if new:
                self._state.add_branch(
                    Branch(bid, name, v_from.get(), v_to.get(), r_pu, x_pu, v_closed.get()),
                    layout=layout,
                )
            else:
                br.name, br.from_bus, br.to_bus = name, v_from.get(), v_to.get()
                br.r_pu, br.x_pu, br.closed = r_pu, x_pu, v_closed.get()
                bl.is_transformer   = v_xfmr.get()
                bl.show_breaker_from = v_breaker.get()
                self._state.notify()
            self._refresh_tree()
            self._tree.selection_set(f"branch:{bid}")

        def delete():
            if not messagebox.askyesno("Delete Branch", f"Remove branch '{branch_id}'?\nAll attached CTs will also be removed.", parent=self):
                return
            self._state.remove_branch(branch_id)
            self._refresh_tree()
            self._show_empty_form()

        self._save_delete_row(g, 10, save, delete if not new else lambda: None)

    # ── CT form ───────────────────────────────────────────────────────────

    def _show_ct_form(self, ct_id: str, new: bool = False) -> None:
        ct = self._state.cts.get(ct_id)
        g  = self._form_grid()
        _section_label(g, "Current Transformer" if not new else "New CT").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        branch_ids = list(self._state.network.branches.keys())
        v_id     = tk.StringVar(value=ct_id if not new else "")
        v_name   = tk.StringVar(value=ct.name          if ct else "")
        v_branch = tk.StringVar(value=ct.branch_id     if ct else (branch_ids[0] if branch_ids else ""))
        v_ratio  = tk.StringVar(value=str(ct.ratio)    if ct else "100")
        v_rev    = tk.BooleanVar(value=ct.polarity_reversed if ct else False)

        self._add_field(g, 1, "ID",      v_id,
                        lambda p, v: _entry(p, v) if new else tk.Label(p, textvariable=v, bg=ENTRY, fg=FG_DIM, font=FONT, anchor="w", relief="flat", bd=4))
        self._add_field(g, 2, "Name",    v_name)
        self._add_field(g, 3, "Branch",  v_branch, lambda p, v: _combo(p, v, branch_ids))
        self._add_field(g, 4, "Ratio",   v_ratio)
        _check(g, "Polarity reversed", v_rev).grid(row=5, column=1, sticky="w", pady=4)

        def save():
            try:
                cid   = v_id.get().strip()
                name  = v_name.get().strip()
                ratio = float(v_ratio.get())
            except ValueError as e:
                messagebox.showerror("Invalid input", str(e), parent=self)
                return
            if not cid or not name:
                messagebox.showerror("Invalid input", "ID and Name are required.", parent=self)
                return
            if new and cid in self._state.cts:
                messagebox.showerror("Duplicate ID", f"CT '{cid}' already exists.", parent=self)
                return
            if new:
                self._state.add_ct(CT(cid, name, v_branch.get(), ratio, v_rev.get()))
            else:
                ct.name, ct.branch_id, ct.ratio, ct.polarity_reversed = (
                    name, v_branch.get(), ratio, v_rev.get()
                )
                self._state.notify()
            self._refresh_tree()
            self._tree.selection_set(f"ct:{cid}")

        def delete():
            if not messagebox.askyesno("Delete CT", f"Remove CT '{ct_id}'?", parent=self):
                return
            self._state.remove_ct(ct_id)
            self._refresh_tree()
            self._show_empty_form()

        self._save_delete_row(g, 6, save, delete if not new else lambda: None)

    # ── VT form ───────────────────────────────────────────────────────────

    def _show_vt_form(self, vt_id: str, new: bool = False) -> None:
        vt = self._state.vts.get(vt_id)
        g  = self._form_grid()
        _section_label(g, "Voltage Transformer" if not new else "New VT").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        bus_ids = list(self._state.network.buses.keys())
        v_id    = tk.StringVar(value=vt_id if not new else "")
        v_name  = tk.StringVar(value=vt.name         if vt else "")
        v_bus   = tk.StringVar(value=vt.bus_id        if vt else (bus_ids[0] if bus_ids else ""))
        v_ratio = tk.StringVar(value=str(vt.ratio)   if vt else "100")
        v_conn  = tk.StringVar(value=vt.connection   if vt else "WYE")

        self._add_field(g, 1, "ID",         v_id,
                        lambda p, v: _entry(p, v) if new else tk.Label(p, textvariable=v, bg=ENTRY, fg=FG_DIM, font=FONT, anchor="w", relief="flat", bd=4))
        self._add_field(g, 2, "Name",       v_name)
        self._add_field(g, 3, "Bus",        v_bus,   lambda p, v: _combo(p, v, bus_ids))
        self._add_field(g, 4, "Ratio",      v_ratio)
        self._add_field(g, 5, "Connection", v_conn,  lambda p, v: _combo(p, v, ["WYE", "DELTA"]))

        def save():
            try:
                vid   = v_id.get().strip()
                name  = v_name.get().strip()
                ratio = float(v_ratio.get())
            except ValueError as e:
                messagebox.showerror("Invalid input", str(e), parent=self)
                return
            if not vid or not name:
                messagebox.showerror("Invalid input", "ID and Name are required.", parent=self)
                return
            if new and vid in self._state.vts:
                messagebox.showerror("Duplicate ID", f"VT '{vid}' already exists.", parent=self)
                return
            if new:
                self._state.add_vt(VT(vid, name, v_bus.get(), ratio, v_conn.get()))
            else:
                vt.name, vt.bus_id, vt.ratio, vt.connection = (
                    name, v_bus.get(), ratio, v_conn.get()
                )
                self._state.notify()
            self._refresh_tree()
            self._tree.selection_set(f"vt:{vid}")

        def delete():
            if not messagebox.askyesno("Delete VT", f"Remove VT '{vt_id}'?", parent=self):
                return
            self._state.remove_vt(vt_id)
            self._refresh_tree()
            self._show_empty_form()

        self._save_delete_row(g, 6, save, delete if not new else lambda: None)

    # ── Add menu ──────────────────────────────────────────────────────────

    def _show_add_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=ACCENT, fg=FG, activebackground=SEL,
                       activeforeground=FG, font=FONT)
        menu.add_command(label="Bus",    command=self._add_bus)
        menu.add_command(label="Branch", command=self._add_branch)
        menu.add_command(label="CT",     command=self._add_ct)
        menu.add_command(label="VT",     command=self._add_vt)
        try:
            x = self.winfo_rootx() + 20
            y = self.winfo_rooty() + self.winfo_height() - 60
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _add_bus(self) -> None:
        self._clear_form()
        self._show_bus_form("", new=True)

    def _add_branch(self) -> None:
        self._clear_form()
        self._show_branch_form("", new=True)

    def _add_ct(self) -> None:
        self._clear_form()
        self._show_ct_form("", new=True)

    def _add_vt(self) -> None:
        self._clear_form()
        self._show_vt_form("", new=True)
