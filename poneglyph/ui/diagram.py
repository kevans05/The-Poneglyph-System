"""One-line diagram canvas — paint-app style.

Tools (accessed via toolbar dropdowns):
  Select        — click to select, drag buses to move
  Bus           — click-drag horizontally to draw a bus bar
  T-Line        — click bus → click bus
  Feeder        — click bus → click empty point (dangling load end)
  Transformer   — click bus → click bus (IEC winding symbol)
  CT            — click on an existing connection line
  VT            — click on a bus
  Delete        — click any element to remove it

Visual conventions (IEC 60617):
  Bus           — single thick horizontal line, name above, kV below
  T-Line/Feeder — thin line; breaker shown as small filled square
  Transformer   — two sets of 3 semicircular winding bumps, gap between (IEC 60617)
  CT            — circle around the line with secondary lead
  VT            — winding bumps hanging from a bus tap, ground symbol at bottom
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Element data models ──────────────────────────────────────────────────────

@dataclass
class DiagramBus:
    id: str
    name: str
    kv: float
    x1: float
    y: float
    x2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    def nearest_tap(self, x: float) -> float:
        return max(self.x1, min(self.x2, x))

    def hit(self, x: float, y: float, tol: float = 8) -> bool:
        return self.x1 - tol <= x <= self.x2 + tol and abs(y - self.y) <= tol


@dataclass
class DiagramConnection:
    id: str
    name: str
    kind: str           # "tline" | "feeder" | "transformer"
    from_bus: str
    from_x: float
    to_bus: Optional[str] = None
    to_x: Optional[float] = None
    to_point: Optional[tuple[float, float]] = None
    has_breaker_from: bool = True
    r_pu: float = 0.01
    x_pu: float = 0.10

    def start_point(self, buses: dict[str, DiagramBus]) -> Optional[tuple[float, float]]:
        b = buses.get(self.from_bus)
        return (b.nearest_tap(self.from_x), b.y) if b else None

    def end_point(self, buses: dict[str, DiagramBus]) -> Optional[tuple[float, float]]:
        if self.to_bus:
            b = buses.get(self.to_bus)
            return (b.nearest_tap(self.to_x or b.cx), b.y) if b else None
        return self.to_point


@dataclass
class DiagramCT:
    id: str
    name: str
    connection_id: str
    t: float = 0.5      # position along connection (0 = from_bus, 1 = to_bus)
    ratio: str = "100/1"


@dataclass
class DiagramVT:
    id: str
    name: str
    bus_id: str
    tap_x: float        # x position on the bus (world coords)
    ratio: str = "11000/110"


# ── Tool constants ────────────────────────────────────────────────────────────

TOOL_SELECT      = "select"
TOOL_BUS         = "bus"
TOOL_TLINE       = "tline"
TOOL_FEEDER      = "feeder"
TOOL_TRANSFORMER = "transformer"
TOOL_CT          = "ct"
TOOL_VT          = "vt"
TOOL_DELETE      = "delete"

TOOL_HINTS = {
    TOOL_SELECT:      "Select: click an element to select it; drag a bus to reposition it.",
    TOOL_BUS:         "Bus: click and drag horizontally to draw a bus bar.",
    TOOL_TLINE:       "T-Line: click a source bus, then click a destination bus.",
    TOOL_FEEDER:      "Feeder: click a bus, then click an empty point for the load end.",
    TOOL_TRANSFORMER: "Transformer: click a source bus, then click a destination bus.",
    TOOL_CT:          "Current Transformer: click on an existing connection line.",
    TOOL_VT:          "Voltage Transformer: click on a bus.",
    TOOL_DELETE:      "Delete: click any element to remove it.",
}

BUS_WIDTH  = 4
LINE_WIDTH = 2
SNAP_TOL   = 16      # pixels — generous so bus clicks register easily


# ── Diagram canvas ────────────────────────────────────────────────────────────

class Diagram(tk.Frame):
    """Paint-app one-line diagram editor."""

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Optional[Callable] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._on_status = on_status

        self._buses:       dict[str, DiagramBus]       = {}
        self._connections: dict[str, DiagramConnection] = {}
        self._cts:         dict[str, DiagramCT]         = {}
        self._vts:         dict[str, DiagramVT]         = {}

        self._tool = TOOL_SELECT
        self._selection: Optional[tuple[str, str]] = None

        self._scale    = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0

        self._drag_bus_id:    Optional[str]               = None
        self._drag_origin:    Optional[tuple[float, float]] = None
        self._bus_draw_start: Optional[tuple[float, float]] = None
        self._conn_from_bus:  Optional[str]               = None
        self._conn_from_x:    float                       = 0.0
        self._pan_start_pt:   Optional[tuple[int, int]]   = None

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.canvas = tk.Canvas(self, bg="white", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>",   self._pan_start)
        self.canvas.bind("<B2-Motion>",       self._pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.canvas.bind("<ButtonPress-3>",   self._pan_start)
        self.canvas.bind("<B3-Motion>",       self._pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._pan_end)
        self.canvas.bind("<MouseWheel>",      self._scroll)
        self.canvas.bind("<Button-4>",        self._scroll)
        self.canvas.bind("<Button-5>",        self._scroll)
        self.canvas.bind("<Configure>",       lambda _e: self.redraw())
        self.canvas.bind("<Motion>",          self._on_motion)

    # ── Public API ────────────────────────────────────────────────────────

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        self._conn_from_bus  = None
        self._bus_draw_start = None
        if self._on_status:
            self._on_status(TOOL_HINTS.get(tool, ""))
        cursor = {TOOL_SELECT: "arrow", TOOL_DELETE: "X_cursor"}.get(tool, "crosshair")
        self.canvas.configure(cursor=cursor)
        self.redraw()

    def get_buses(self)       -> dict[str, DiagramBus]:       return self._buses
    def get_connections(self) -> dict[str, DiagramConnection]: return self._connections
    def get_cts(self)         -> dict[str, DiagramCT]:         return self._cts
    def get_vts(self)         -> dict[str, DiagramVT]:         return self._vts
    def get_selection(self)   -> Optional[tuple[str, str]]:    return self._selection

    def clear(self) -> None:
        self._buses.clear()
        self._connections.clear()
        self._cts.clear()
        self._vts.clear()
        self._selection = None
        self.redraw()

    # ── Coordinates ───────────────────────────────────────────────────────

    def _w2s(self, wx: float, wy: float) -> tuple[float, float]:
        return wx * self._scale + self._offset_x, wy * self._scale + self._offset_y

    def _s2w(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self._offset_x) / self._scale, (sy - self._offset_y) / self._scale

    # ── Redraw ────────────────────────────────────────────────────────────

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._draw_grid()
        for conn in self._connections.values():
            self._draw_connection(conn)
        for bus in self._buses.values():
            self._draw_bus(bus)
        for ct in self._cts.values():
            self._draw_ct(ct)
        for vt in self._vts.values():
            self._draw_vt(vt)

    def _draw_grid(self) -> None:
        w = self.canvas.winfo_width()  or 800
        h = self.canvas.winfo_height() or 600
        step = 20 * self._scale
        if step < 8:
            return
        x = self._offset_x % step
        while x < w:
            y = self._offset_y % step
            while y < h:
                self.canvas.create_oval(x-1, y-1, x+1, y+1, fill="#DDDDDD", outline="")
                y += step
            x += step

    def _draw_bus(self, bus: DiagramBus) -> None:
        sx1, sy = self._w2s(bus.x1, bus.y)
        sx2, _  = self._w2s(bus.x2, bus.y)
        sel    = self._selection == ("bus", bus.id)
        colour = "#0066CC" if sel else "black"
        self.canvas.create_line(sx1, sy, sx2, sy, width=BUS_WIDTH, fill=colour, capstyle=tk.ROUND)
        cx = (sx1 + sx2) / 2
        self.canvas.create_text(cx, sy - 12, text=bus.name,
                                font=("TkDefaultFont", 9, "bold"), fill=colour, anchor="s")
        if bus.kv:
            self.canvas.create_text(cx, sy + 10, text=f"{bus.kv} kV",
                                    font=("TkDefaultFont", 8), fill="#555555", anchor="n")

    def _draw_connection(self, conn: DiagramConnection) -> None:
        start = conn.start_point(self._buses)
        end   = conn.end_point(self._buses)
        if start is None or end is None:
            return
        x1, y1 = self._w2s(*start)
        x2, y2 = self._w2s(*end)
        sel    = self._selection == ("conn", conn.id)
        colour = "#0066CC" if sel else "black"

        if conn.kind == "transformer":
            self._draw_iec_transformer(x1, y1, x2, y2, colour)
        else:
            self.canvas.create_line(x1, y1, x2, y2, width=LINE_WIDTH, fill=colour)

        if conn.has_breaker_from:
            self._draw_breaker(x1, y1, x2, y2, t=0.15, colour=colour)

        if conn.kind == "feeder":
            self._draw_load_triangle(x2, y2, colour)

        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        self.canvas.create_text(mx + 6, my, text=conn.name,
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    def _draw_breaker(self, x1, y1, x2, y2, t: float, colour: str) -> None:
        bx = x1 + (x2 - x1) * t
        by = y1 + (y2 - y1) * t
        h  = 5 * self._scale
        self.canvas.create_rectangle(bx - h, by - h, bx + h, by + h,
                                     fill=colour, outline=colour)

    def _draw_load_triangle(self, x: float, y: float, colour: str) -> None:
        s = 10 * self._scale
        self.canvas.create_polygon(x, y, x - s, y + s * 1.6, x + s, y + s * 1.6,
                                   fill="white", outline=colour, width=LINE_WIDTH)

    # ── IEC 60617 transformer symbol ──────────────────────────────────────

    def _draw_iec_transformer(self, x1: float, y1: float,
                               x2: float, y2: float, colour: str) -> None:
        """IEC 60617 two-winding transformer: 3 winding bumps per side, gap between."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1
        ux, uy = dx / length, dy / length          # unit along line
        px, py = uy, -ux                            # unit perpendicular (right of travel)

        r   = 7 * self._scale                       # bump radius
        gap = 4 * self._scale                       # gap between windings
        n   = 3                                     # bumps per winding
        half_sym = n * r + gap / 2                  # half-height of full symbol

        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

        sym_start_x = mx - ux * half_sym
        sym_start_y = my - uy * half_sym

        # Lead lines: bus tap → symbol start, symbol end → bus tap
        self.canvas.create_line(x1, y1, sym_start_x, sym_start_y,
                                width=LINE_WIDTH, fill=colour)
        self.canvas.create_line(mx + ux * half_sym, my + uy * half_sym, x2, y2,
                                width=LINE_WIDTH, fill=colour)

        # Primary winding: bumps bulging RIGHT, occupying along from -half_sym to -gap/2
        w1_center_along = -(gap / 2 + n * r)
        self._draw_winding(mx, my, ux, uy, px, py, r, n, w1_center_along, +1, colour)

        # Secondary winding: bumps bulging LEFT, occupying along from +gap/2 to +half_sym
        w2_center_along = +(gap / 2 + n * r)
        self._draw_winding(mx, my, ux, uy, px, py, r, n, w2_center_along, -1, colour)

    def _draw_winding(self, cx, cy, ux, uy, px, py,
                      r, n_bumps, center_along, direction, colour) -> None:
        """Draw n_bumps semicircular arcs for one transformer winding."""
        N = 18  # points per arc for smoothness
        half = n_bumps * r
        for i in range(n_bumps):
            bump_along = center_along - half + r + i * 2 * r
            bcx = cx + bump_along * ux
            bcy = cy + bump_along * uy
            pts = []
            for j in range(N + 1):
                t   = -math.pi / 2 + math.pi * j / N
                lx  = direction * r * math.cos(t)
                ly  = r * math.sin(t)
                sx, sy = self._w2s(bcx + lx * px + ly * ux,
                                   bcy + lx * py + ly * uy)
                pts.extend([sx, sy])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

    # ── IEC CT symbol ────────────────────────────────────────────────────

    def _draw_ct(self, ct: DiagramCT) -> None:
        conn = self._connections.get(ct.connection_id)
        if conn is None:
            return
        start = conn.start_point(self._buses)
        end   = conn.end_point(self._buses)
        if start is None or end is None:
            return
        wx1, wy1 = start
        wx2, wy2 = end
        wx = wx1 + (wx2 - wx1) * ct.t
        wy = wy1 + (wy2 - wy1) * ct.t
        sx, sy = self._w2s(wx, wy)

        sel    = self._selection == ("ct", ct.id)
        colour = "#0066CC" if sel else "black"

        r  = 10 * self._scale
        # Circle around the conductor
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                outline=colour, fill="white", width=LINE_WIDTH)

        # Secondary lead: short line perpendicular to the conductor
        dx, dy = wx2 - wx1, wy2 - wy1
        length = math.hypot(dx, dy) or 1
        pxn, pyn = -dy / length, dx / length   # perpendicular
        lead = (r + 10) * 1.0  # in screen pixels
        ex, ey = sx + pxn * lead, sy + pyn * lead
        self.canvas.create_line(sx, sy, ex, ey, fill=colour, width=LINE_WIDTH)
        # Tick at end of secondary lead
        self.canvas.create_line(ex - pyn * 5, ey + pxn * 5,
                                ex + pyn * 5, ey - pxn * 5,
                                fill=colour, width=LINE_WIDTH)

        # Label
        self.canvas.create_text(ex + pxn * 4, ey + pyn * 4,
                                text=ct.name, font=("TkDefaultFont", 8),
                                fill="#444444", anchor="w")

    # ── IEC VT symbol ────────────────────────────────────────────────────

    def _draw_vt(self, vt: DiagramVT) -> None:
        bus = self._buses.get(vt.bus_id)
        if bus is None:
            return
        tap_x = bus.nearest_tap(vt.tap_x)
        sx, sy = self._w2s(tap_x, bus.y)

        sel    = self._selection == ("vt", vt.id)
        colour = "#0066CC" if sel else "black"

        r    = 6 * self._scale
        drop = 12 * self._scale          # short drop line from bus

        # Drop line from bus to winding start
        self.canvas.create_line(sx, sy, sx, sy + drop,
                                fill=colour, width=LINE_WIDTH)

        # Primary winding: 3 bumps to the right, hanging down
        winding_top = sy + drop
        n = 3
        for i in range(n):
            by = winding_top + r + i * 2 * r
            pts = []
            N = 16
            for j in range(N + 1):
                t    = -math.pi / 2 + math.pi * j / N
                bx_s = sx + r * math.cos(t)    # bumps to the right (+x)
                by_s = by + r * math.sin(t)
                pts.extend([bx_s, by_s])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        winding_bot = winding_top + n * 2 * r

        # Secondary winding: 3 smaller bumps to the left
        r2 = r * 0.75
        sec_top = winding_bot + r * 0.5
        for i in range(n):
            by = sec_top + r2 + i * 2 * r2
            pts = []
            for j in range(N + 1):
                t    = -math.pi / 2 + math.pi * j / N
                bx_s = sx - r2 * math.cos(t)   # bumps to the left (-x)
                by_s = by + r2 * math.sin(t)
                pts.extend([bx_s, by_s])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        sec_bot = sec_top + n * 2 * r2

        # Ground symbol (IEC: short line + three decreasing horizontal lines)
        gy = sec_bot + 4 * self._scale
        self.canvas.create_line(sx, sec_bot, sx, gy, fill=colour, width=LINE_WIDTH)
        for k, w in enumerate([10, 6, 3]):
            ws = w * self._scale
            yy = gy + k * 4 * self._scale
            self.canvas.create_line(sx - ws, yy, sx + ws, yy,
                                    fill=colour, width=LINE_WIDTH)

        # Label
        self.canvas.create_text(sx + 14 * self._scale, winding_top + (winding_bot - winding_top) / 2,
                                text=vt.name, font=("TkDefaultFont", 8),
                                fill="#444444", anchor="w")

    # ── Hit testing ───────────────────────────────────────────────────────

    def _hit_bus(self, wx: float, wy: float) -> Optional[str]:
        for bus in self._buses.values():
            if bus.hit(wx, wy, tol=SNAP_TOL / self._scale):
                return bus.id
        return None

    def _hit_connection(self, sx: float, sy: float) -> Optional[str]:
        for conn in self._connections.values():
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            if _point_to_segment_dist(sx, sy, x1, y1, x2, y2) < 8:
                return conn.id
        return None

    def _hit_ct(self, sx: float, sy: float) -> Optional[str]:
        tol = 12 * self._scale
        for ct in self._cts.values():
            conn = self._connections.get(ct.connection_id)
            if conn is None:
                continue
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            wx1, wy1 = start
            wx2, wy2 = end
            wx = wx1 + (wx2 - wx1) * ct.t
            wy = wy1 + (wy2 - wy1) * ct.t
            csx, csy = self._w2s(wx, wy)
            if math.hypot(sx - csx, sy - csy) < tol:
                return ct.id
        return None

    def _hit_vt(self, wx: float, wy: float) -> Optional[str]:
        tol = SNAP_TOL / self._scale
        for vt in self._vts.values():
            bus = self._buses.get(vt.bus_id)
            if bus is None:
                continue
            if abs(bus.nearest_tap(vt.tap_x) - wx) < tol and abs(bus.y - wy) < tol * 2:
                return vt.id
        return None

    # ── Mouse events ──────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT:
            ct_id   = self._hit_ct(event.x, event.y)
            vt_id   = self._hit_vt(wx, wy)
            bus_id  = self._hit_bus(wx, wy)
            conn_id = self._hit_connection(event.x, event.y)
            if ct_id:
                self._set_selection("ct", ct_id)
            elif vt_id:
                self._set_selection("vt", vt_id)
            elif bus_id:
                self._set_selection("bus", bus_id)
                self._drag_bus_id = bus_id
                self._drag_origin = (wx, wy)
            elif conn_id:
                self._set_selection("conn", conn_id)
            else:
                self._set_selection(None, None)

        elif self._tool == TOOL_BUS:
            self._bus_draw_start = (wx, wy)

        elif self._tool in (TOOL_TLINE, TOOL_FEEDER, TOOL_TRANSFORMER):
            bus_id = self._hit_bus(wx, wy)
            if self._conn_from_bus is None:
                if bus_id:
                    self._conn_from_bus = bus_id
                    self._conn_from_x   = wx
                    if self._on_status:
                        self._on_status(
                            f"From '{self._buses[bus_id].name}' — now click the destination."
                        )
            else:
                self._finish_connection(wx, wy, bus_id)

        elif self._tool == TOOL_CT:
            conn_id = self._hit_connection(event.x, event.y)
            if conn_id:
                conn  = self._connections[conn_id]
                start = conn.start_point(self._buses)
                end   = conn.end_point(self._buses)
                if start and end:
                    wx1, wy1 = start
                    wx2, wy2 = end
                    length = math.hypot(wx2 - wx1, wy2 - wy1) or 1
                    t = math.hypot(wx - wx1, wy - wy1) / length
                    t = max(0.1, min(0.9, t))
                    cid = f"CT-{len(self._cts)+1}"
                    ct  = DiagramCT(cid, cid, conn_id, t)
                    self._cts[cid] = ct
                    self._set_selection("ct", cid)

        elif self._tool == TOOL_VT:
            bus_id = self._hit_bus(wx, wy)
            if bus_id:
                vid = f"VT-{len(self._vts)+1}"
                vt  = DiagramVT(vid, vid, bus_id, wx)
                self._vts[vid] = vt
                self._set_selection("vt", vid)

        elif self._tool == TOOL_DELETE:
            ct_id   = self._hit_ct(event.x, event.y)
            vt_id   = self._hit_vt(wx, wy)
            bus_id  = self._hit_bus(wx, wy)
            conn_id = self._hit_connection(event.x, event.y)
            if ct_id:
                self._cts.pop(ct_id)
                self._set_selection(None, None)
                self.redraw()
            elif vt_id:
                self._vts.pop(vt_id)
                self._set_selection(None, None)
                self.redraw()
            elif bus_id:
                self._delete_bus(bus_id)
            elif conn_id:
                self._delete_connection(conn_id)

    def _on_drag(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)
        if self._tool == TOOL_SELECT and self._drag_bus_id and self._drag_origin:
            bus    = self._buses[self._drag_bus_id]
            dx     = wx - self._drag_origin[0]
            bus.x1 += dx
            bus.x2 += dx
            bus.y  += wy - self._drag_origin[1]
            self._drag_origin = (wx, wy)
            self.redraw()
        elif self._tool == TOOL_BUS and self._bus_draw_start:
            self.redraw()
            sx1, sy1 = self._w2s(*self._bus_draw_start)
            self.canvas.create_line(sx1, sy1, event.x, sy1,
                                    width=BUS_WIDTH, fill="#888888", dash=(4, 4))

    def _on_release(self, event: tk.Event) -> None:
        if self._tool == TOOL_BUS and self._bus_draw_start:
            wx, wy = self._s2w(event.x, event.y)
            x1, y0 = self._bus_draw_start
            x2 = wx
            if abs(x2 - x1) > 10 / self._scale:
                bid = f"BUS-{len(self._buses)+1}"
                self._buses[bid] = DiagramBus(bid, bid, 0.0,
                                              min(x1, x2), y0, max(x1, x2))
                self._set_selection("bus", bid)
            self._bus_draw_start = None
            self.redraw()
        self._drag_bus_id = None
        self._drag_origin = None

    def _on_motion(self, event: tk.Event) -> None:
        if self._conn_from_bus and self._tool in (TOOL_TLINE, TOOL_FEEDER, TOOL_TRANSFORMER):
            self.redraw()
            bus = self._buses.get(self._conn_from_bus)
            if bus:
                sx, sy = self._w2s(bus.nearest_tap(self._conn_from_x), bus.y)
                self.canvas.create_line(sx, sy, event.x, event.y,
                                        width=LINE_WIDTH, fill="#888888", dash=(4, 4))

    def _finish_connection(self, wx: float, wy: float, to_bus_id: Optional[str]) -> None:
        kind_map = {TOOL_TLINE: "tline", TOOL_FEEDER: "feeder",
                    TOOL_TRANSFORMER: "transformer"}
        kind = kind_map[self._tool]
        if self._conn_from_bus not in self._buses:
            self._conn_from_bus = None
            return
        cid = f"{kind.upper()}-{len(self._connections)+1}"
        if kind == "feeder":
            conn = DiagramConnection(cid, cid, kind, self._conn_from_bus, self._conn_from_x,
                                     to_point=(wx, wy))
        elif to_bus_id and to_bus_id != self._conn_from_bus:
            conn = DiagramConnection(cid, cid, kind, self._conn_from_bus, self._conn_from_x,
                                     to_bus=to_bus_id, to_x=wx)
        else:
            # Missed the destination bus — keep from_bus active and prompt the user
            if self._on_status:
                msg = ("Same bus — click a different bus." if to_bus_id
                       else "No bus found there — click directly on a bus bar.")
                self._on_status(f"From '{self._buses[self._conn_from_bus].name}' — {msg}")
            return
        self._connections[cid] = conn
        self._set_selection("conn", cid)
        self._conn_from_bus = None
        self.redraw()

    def _delete_bus(self, bus_id: str) -> None:
        self._buses.pop(bus_id, None)
        dead_conns = [cid for cid, c in self._connections.items()
                      if c.from_bus == bus_id or c.to_bus == bus_id]
        for cid in dead_conns:
            self._delete_connection(cid)
        dead_vts = [vid for vid, v in self._vts.items() if v.bus_id == bus_id]
        for vid in dead_vts:
            self._vts.pop(vid)
        self._set_selection(None, None)
        self.redraw()

    def _delete_connection(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
        dead_cts = [cid for cid, c in self._cts.items() if c.connection_id == conn_id]
        for cid in dead_cts:
            self._cts.pop(cid)
        self._set_selection(None, None)
        self.redraw()

    # ── Pan / zoom ────────────────────────────────────────────────────────

    def _pan_start(self, event: tk.Event) -> None:
        self._pan_start_pt = (event.x, event.y)

    def _pan_drag(self, event: tk.Event) -> None:
        if self._pan_start_pt:
            self._offset_x += event.x - self._pan_start_pt[0]
            self._offset_y += event.y - self._pan_start_pt[1]
            self._pan_start_pt = (event.x, event.y)
            self.redraw()

    def _pan_end(self, _event: tk.Event) -> None:
        self._pan_start_pt = None

    def _scroll(self, event: tk.Event) -> None:
        factor = 1.1 if (event.num == 4 or event.delta > 0) else 1 / 1.1
        cx, cy = event.x, event.y
        self._offset_x = cx - (cx - self._offset_x) * factor
        self._offset_y = cy - (cy - self._offset_y) * factor
        self._scale    = max(0.2, min(self._scale * factor, 8.0))
        self.redraw()

    # ── Selection ─────────────────────────────────────────────────────────

    def _set_selection(self, kind: Optional[str], elem_id: Optional[str]) -> None:
        self._selection = (kind, elem_id) if kind else None
        if self._on_select:
            self._on_select(self._selection)
        self.redraw()


# ── Geometry ─────────────────────────────────────────────────────────────────

def _point_to_segment_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)))
    return math.hypot(px - x1 - t*dx, py - y1 - t*dy)
