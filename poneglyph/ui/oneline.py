"""One-line diagram canvas widget.

Renders a substation network as an interactive one-line diagram.
Buses are draggable nodes; branches, breakers, CTs, and VTs are drawn
relative to their connected buses.

Interaction:
  Left-click       — select device / bus
  Left-drag (bus)  — reposition bus
  Middle-drag      — pan
  Scroll wheel     — zoom in/out
  Right-click      — context menu (future)
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Optional

from poneglyph.ui.symbols import (
    COLOUR,
    draw_breaker,
    draw_bus,
    draw_ct,
    draw_load,
    draw_transformer,
    draw_vt,
    draw_wire,
)


# ── Layout data ──────────────────────────────────────────────────────────────

@dataclass
class BusLayout:
    """World-space position of a bus node."""
    bus_id: str
    x: float
    y: float
    length: float = 140


@dataclass
class BranchLayout:
    """Decoration hints for a branch (which symbols to draw along it)."""
    branch_id: str
    show_breaker_from: bool = True   # breaker near from_bus end
    show_breaker_to: bool = False
    ct_ids: list[str] = field(default_factory=list)   # CT ids to show
    is_transformer: bool = False


# ── Main widget ──────────────────────────────────────────────────────────────

class OneLineDiagram(tk.Frame):
    """Tkinter Frame containing a pannable, zoomable one-line diagram canvas."""

    def __init__(self, parent: tk.Widget, on_select: Optional[Callable] = None) -> None:
        super().__init__(parent, bg=COLOUR["bg"])
        self._on_select = on_select  # callback(type, id) when user clicks a device

        # World-space state
        self._bus_layouts:    dict[str, BusLayout]    = {}
        self._branch_layouts: dict[str, BranchLayout] = {}

        # Network data (set via load_network)
        self._network = None
        self._cts:  dict = {}
        self._vts:  dict = {}

        # Canvas item → (type, id) mapping for hit-testing
        self._item_map:  dict[int, tuple[str, str]] = {}
        self._selection: Optional[tuple[str, str]]  = None

        # Pan / zoom state
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._scale    = 1.0
        self._pan_start: Optional[tuple[int, int]] = None

        # Drag state
        self._drag_bus:   Optional[str]        = None
        self._drag_start: Optional[tuple[float, float]] = None

        self._build_canvas()

    # ── Canvas setup ──────────────────────────────────────────────────────

    def _build_canvas(self) -> None:
        # Toolbar
        toolbar = tk.Frame(self, bg="#111122")
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(
            toolbar, text="Fit", bg="#223", fg="#CCC",
            relief="flat", padx=6, command=self.fit_view,
        ).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(
            toolbar, text="+", bg="#223", fg="#CCC",
            relief="flat", padx=6, command=lambda: self._zoom(1.25),
        ).pack(side=tk.LEFT, padx=1, pady=2)
        tk.Button(
            toolbar, text="−", bg="#223", fg="#CCC",
            relief="flat", padx=6, command=lambda: self._zoom(0.8),
        ).pack(side=tk.LEFT, padx=1, pady=2)

        self._lbl_sel = tk.Label(
            toolbar, text="Nothing selected", bg="#111122", fg="#888",
            font=("Courier", 9),
        )
        self._lbl_sel.pack(side=tk.RIGHT, padx=8)

        # Canvas
        self.canvas = tk.Canvas(
            self, bg=COLOUR["bg"], highlightthickness=0, cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Scrollbars
        hbar = tk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vbar = tk.Scrollbar(self, orient=tk.VERTICAL,   command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self.canvas.bind("<ButtonPress-1>",   self._on_left_press)
        self.canvas.bind("<B1-Motion>",       self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<ButtonPress-2>",   self._on_pan_start)
        self.canvas.bind("<B2-Motion>",       self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_end)
        self.canvas.bind("<ButtonPress-3>",   self._on_pan_start)   # right-drag also pans
        self.canvas.bind("<B3-Motion>",       self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)
        self.canvas.bind("<MouseWheel>",      self._on_scroll)
        self.canvas.bind("<Button-4>",        self._on_scroll)
        self.canvas.bind("<Button-5>",        self._on_scroll)
        self.canvas.bind("<Configure>",       lambda _: self.redraw())

    # ── Public API ────────────────────────────────────────────────────────

    def load_network(
        self,
        network,
        bus_layouts:    dict[str, BusLayout],
        branch_layouts: dict[str, BranchLayout],
        cts:  dict,
        vts:  dict,
    ) -> None:
        self._network       = network
        self._bus_layouts   = bus_layouts
        self._branch_layouts = branch_layouts
        self._cts = cts
        self._vts = vts
        self.fit_view()

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._item_map.clear()
        if self._network is None:
            self._draw_empty_hint()
            return
        self._draw_grid()
        self._draw_branches()
        self._draw_buses()
        self._draw_vts()

    def fit_view(self) -> None:
        """Centre and scale the view to fit all buses."""
        if not self._bus_layouts:
            self.redraw()
            return
        xs = [bl.x for bl in self._bus_layouts.values()]
        ys = [bl.y for bl in self._bus_layouts.values()]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        w  = self.canvas.winfo_width()  or 800
        h  = self.canvas.winfo_height() or 600
        span_x = max(max(xs) - min(xs), 1)
        span_y = max(max(ys) - min(ys), 1)
        self._scale    = min(w / (span_x + 300), h / (span_y + 200)) * 0.85
        self._offset_x = w / 2 - cx * self._scale
        self._offset_y = h / 2 - cy * self._scale
        self.redraw()

    # ── Coordinate transforms ─────────────────────────────────────────────

    def _w2s(self, wx: float, wy: float) -> tuple[float, float]:
        """World → screen."""
        return wx * self._scale + self._offset_x, wy * self._scale + self._offset_y

    def _s2w(self, sx: float, sy: float) -> tuple[float, float]:
        """Screen → world."""
        return (sx - self._offset_x) / self._scale, (sy - self._offset_y) / self._scale

    # ── Drawing helpers ────────────────────────────────────────────────────

    def _draw_empty_hint(self) -> None:
        w = self.canvas.winfo_width()  or 600
        h = self.canvas.winfo_height() or 400
        self.canvas.create_text(
            w / 2, h / 2,
            text="No network loaded.\nUse Simulation → Network Editor to add buses.",
            fill="#444466", font=("Courier", 13), justify=tk.CENTER,
        )

    def _draw_grid(self) -> None:
        w = self.canvas.winfo_width()  or 800
        h = self.canvas.winfo_height() or 600
        # Determine world-space grid spacing that maps to ~50 px
        grid_world = 50 / self._scale
        # Round to nearest sensible interval
        for mag in (1, 2, 5, 10, 20, 50, 100, 200, 500):
            if mag >= grid_world * 0.8:
                grid_world = mag
                break
        # World extent visible
        wx0, wy0 = self._s2w(0, 0)
        wx1, wy1 = self._s2w(w, h)
        import math
        x_start = math.floor(wx0 / grid_world) * grid_world
        y_start = math.floor(wy0 / grid_world) * grid_world
        x = x_start
        while x <= wx1:
            sx, _ = self._w2s(x, 0)
            self.canvas.create_line(sx, 0, sx, h, fill="#1E1E30", width=1)
            x += grid_world
        y = y_start
        while y <= wy1:
            _, sy = self._w2s(0, y)
            self.canvas.create_line(0, sy, w, sy, fill="#1E1E30", width=1)
            y += grid_world

    def _draw_buses(self) -> None:
        for bl in self._bus_layouts.values():
            bus = self._network.buses.get(bl.bus_id)
            if bus is None:
                continue
            sx, sy = self._w2s(bl.x, bl.y)
            selected = self._selection == ("bus", bl.bus_id)
            ids = draw_bus(
                self.canvas, sx, sy,
                length=bl.length * self._scale,
                label=bus.name,
                kv=bus.base_kv,
                selected=selected,
            )
            for item_id in ids:
                self._item_map[item_id] = ("bus", bl.bus_id)

    def _draw_branches(self) -> None:
        if self._network is None:
            return
        for branch in self._network.branches.values():
            bl_from = self._bus_layouts.get(branch.from_bus)
            bl_to   = self._bus_layouts.get(branch.to_bus)
            if bl_from is None or bl_to is None:
                continue
            sx1, sy1 = self._w2s(bl_from.x, bl_from.y)
            sx2, sy2 = self._w2s(bl_to.x,   bl_to.y)

            energised = branch.closed
            bl = self._branch_layouts.get(branch.id, BranchLayout(branch.id))

            # Split the wire into segments to leave room for symbols
            # Midpoint
            mx, my = (sx1 + sx2) / 2, (sy1 + sy2) / 2

            if bl.is_transformer:
                # Wire from → transformer body; wire transformer body → to
                draw_wire(self.canvas, sx1, sy1, mx, my - 28 * self._scale, energised)
                ids = draw_transformer(self.canvas, mx, my, selected=self._selection == ("branch", branch.id))
                for i in ids:
                    self._item_map[i] = ("branch", branch.id)
                draw_wire(self.canvas, mx, my + 28 * self._scale, sx2, sy2, energised)
            else:
                # Plain wire with optional breaker at from-end
                if bl.show_breaker_from:
                    # Wire: bus → breaker → (rest of line) → bus
                    bx = sx1 + (mx - sx1) * 0.3
                    by = sy1 + (my - sy1) * 0.3
                    draw_wire(self.canvas, sx1, sy1, bx, by, energised)
                    ids = draw_breaker(
                        self.canvas, bx, by, closed=branch.closed,
                        selected=self._selection == ("branch", branch.id),
                    )
                    for i in ids:
                        self._item_map[i] = ("branch", branch.id)
                    draw_wire(self.canvas, bx, by, sx2, sy2, energised)
                else:
                    draw_wire(self.canvas, sx1, sy1, sx2, sy2, energised)

            # CTs along this branch
            for ci, ct_id in enumerate(bl.ct_ids):
                ct = self._cts.get(ct_id)
                if ct is None:
                    continue
                t = 0.5 + ci * 0.12
                cx = sx1 + (sx2 - sx1) * t
                cy = sy1 + (sy2 - sy1) * t
                ids = draw_ct(
                    self.canvas, cx, cy, label=ct.name,
                    selected=self._selection == ("ct", ct_id),
                )
                for i in ids:
                    self._item_map[i] = ("ct", ct_id)

    def _draw_vts(self) -> None:
        for vt in self._vts.values():
            bl = self._bus_layouts.get(vt.bus_id)
            if bl is None:
                continue
            sx, sy = self._w2s(bl.x, bl.y)
            # Place VT below the bus bar, offset right
            vx, vy = sx + bl.length * self._scale * 0.35, sy + 32 * self._scale
            draw_wire(self.canvas, vx, sy + 6 * self._scale, vx, vy - 14 * self._scale, True)
            ids = draw_vt(
                self.canvas, vx, vy, label=vt.name,
                selected=self._selection == ("vt", vt.id),
            )
            for i in ids:
                self._item_map[i] = ("vt", vt.id)

    # ── Mouse events ───────────────────────────────────────────────────────

    def _on_left_press(self, event: tk.Event) -> None:
        hit = self._hit_test(event.x, event.y)
        if hit and hit[0] == "bus":
            self._drag_bus   = hit[1]
            self._drag_start = self._s2w(event.x, event.y)
        else:
            self._drag_bus = None
        self._set_selection(hit)

    def _on_left_drag(self, event: tk.Event) -> None:
        if self._drag_bus and self._drag_start:
            wx, wy = self._s2w(event.x, event.y)
            bl = self._bus_layouts.get(self._drag_bus)
            if bl:
                bl.x += wx - self._drag_start[0]
                bl.y += wy - self._drag_start[1]
                self._drag_start = (wx, wy)
                self.redraw()

    def _on_left_release(self, _event: tk.Event) -> None:
        self._drag_bus   = None
        self._drag_start = None

    def _on_pan_start(self, event: tk.Event) -> None:
        self._pan_start = (event.x, event.y)

    def _on_pan_drag(self, event: tk.Event) -> None:
        if self._pan_start:
            dx = event.x - self._pan_start[0]
            dy = event.y - self._pan_start[1]
            self._offset_x += dx
            self._offset_y += dy
            self._pan_start = (event.x, event.y)
            self.redraw()

    def _on_pan_end(self, _event: tk.Event) -> None:
        self._pan_start = None

    def _on_scroll(self, event: tk.Event) -> None:
        if event.num == 4 or event.delta > 0:
            self._zoom(1.15, event.x, event.y)
        else:
            self._zoom(1 / 1.15, event.x, event.y)

    # ── Zoom ───────────────────────────────────────────────────────────────

    def _zoom(self, factor: float, cx: Optional[float] = None, cy: Optional[float] = None) -> None:
        if cx is None:
            cx = (self.canvas.winfo_width()  or 800) / 2
        if cy is None:
            cy = (self.canvas.winfo_height() or 600) / 2
        self._offset_x = cx - (cx - self._offset_x) * factor
        self._offset_y = cy - (cy - self._offset_y) * factor
        self._scale *= factor
        self._scale = max(0.1, min(self._scale, 10.0))
        self.redraw()

    # ── Hit testing ────────────────────────────────────────────────────────

    def _hit_test(self, sx: float, sy: float) -> Optional[tuple[str, str]]:
        # Find topmost canvas item under the cursor
        items = self.canvas.find_overlapping(sx - 6, sy - 6, sx + 6, sy + 6)
        for item in reversed(items):
            hit = self._item_map.get(item)
            if hit:
                return hit
        return None

    def _set_selection(self, sel: Optional[tuple[str, str]]) -> None:
        self._selection = sel
        if sel:
            self._lbl_sel.config(text=f"Selected: {sel[0]}  {sel[1]}")
        else:
            self._lbl_sel.config(text="Nothing selected")
        if self._on_select:
            self._on_select(sel)
        self.redraw()
