"""One-line diagram canvas — paint-app style.

Tools:
  Select    — click to select, drag to move buses
  Bus       — click-drag horizontally to draw a bus bar
  T-Line    — click a bus, then click another bus to connect
  Feeder    — click a bus, then click an empty point (dangling load end)
  Transformer — click a bus, then click another bus (draws transformer symbol)
  Delete    — click any element to remove it

Visual conventions (standard one-line):
  Bus        — single thick horizontal line, name above, kV below
  T-Line     — thin vertical/diagonal line between two buses
  Feeder     — thin line from bus to a load triangle
  Transformer — line with two tangent circles in the middle
  Breaker    — small filled square on a line (toggled open/closed)
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Optional
import uuid


# ── Element data models ──────────────────────────────────────────────────────

@dataclass
class DiagramBus:
    id: str
    name: str
    kv: float
    x1: float   # left end  (world coords)
    y: float    # vertical position
    x2: float   # right end

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    def nearest_tap(self, x: float) -> float:
        """Clamp x to the bus extents."""
        return max(self.x1, min(self.x2, x))

    def hit(self, x: float, y: float, tol: float = 8) -> bool:
        return self.x1 - tol <= x <= self.x2 + tol and abs(y - self.y) <= tol


@dataclass
class DiagramConnection:
    id: str
    name: str
    kind: str           # "tline" | "feeder" | "transformer"
    from_bus: str       # bus id
    from_x: float       # tap x on from_bus
    to_bus: Optional[str] = None   # bus id (tline / transformer)
    to_x: Optional[float] = None   # tap x on to_bus
    to_point: Optional[tuple[float, float]] = None  # for feeder end
    has_breaker_from: bool = True
    r_pu: float = 0.01
    x_pu: float = 0.10

    def end_point(self, buses: dict[str, DiagramBus]) -> Optional[tuple[float, float]]:
        if self.to_bus:
            b = buses.get(self.to_bus)
            if b:
                return b.nearest_tap(self.to_x or b.cx), b.y
        return self.to_point

    def start_point(self, buses: dict[str, DiagramBus]) -> Optional[tuple[float, float]]:
        b = buses.get(self.from_bus)
        if b:
            return b.nearest_tap(self.from_x), b.y
        return None


# ── Diagram canvas ────────────────────────────────────────────────────────────

TOOL_SELECT      = "select"
TOOL_BUS         = "bus"
TOOL_TLINE       = "tline"
TOOL_FEEDER      = "feeder"
TOOL_TRANSFORMER = "transformer"
TOOL_DELETE      = "delete"

TOOL_HINTS = {
    TOOL_SELECT:      "Select: click to select an element, drag a bus to move it.",
    TOOL_BUS:         "Bus: click and drag horizontally to draw a bus bar.",
    TOOL_TLINE:       "T-Line: click a bus to start, then click another bus to connect.",
    TOOL_FEEDER:      "Feeder: click a bus to start, then click an empty point for the load end.",
    TOOL_TRANSFORMER: "Transformer: click a bus to start, then click another bus.",
    TOOL_DELETE:      "Delete: click any element to remove it.",
}

BUS_WIDTH   = 4      # line thickness for bus bars
LINE_WIDTH  = 2      # line thickness for connections
SNAP_TOL    = 12     # pixels for bus hit-test


class Diagram(tk.Frame):
    """Paint-app one-line diagram editor."""

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Optional[Callable] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_select  = on_select
        self._on_status  = on_status

        self._buses:       dict[str, DiagramBus]       = {}
        self._connections: dict[str, DiagramConnection] = {}

        self._tool       = TOOL_SELECT
        self._selection: Optional[tuple[str, str]] = None  # (kind, id)

        # Pan / zoom
        self._scale     = 1.0
        self._offset_x  = 0.0
        self._offset_y  = 0.0
        self._pan_start: Optional[tuple[int, int]] = None

        # Per-tool transient state
        self._drag_bus_id:  Optional[str]          = None
        self._drag_origin:  Optional[tuple[float, float]] = None
        self._bus_draw_start: Optional[tuple[float, float]] = None
        self._conn_from_bus:  Optional[str]        = None   # for tline/feeder/xfmr pending

        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

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
        self._conn_from_bus   = None
        self._bus_draw_start  = None
        hint = TOOL_HINTS.get(tool, "")
        if self._on_status:
            self._on_status(hint)
        cursor = {
            TOOL_SELECT: "arrow", TOOL_BUS: "crosshair",
            TOOL_TLINE: "crosshair", TOOL_FEEDER: "crosshair",
            TOOL_TRANSFORMER: "crosshair", TOOL_DELETE: "X_cursor",
        }.get(tool, "crosshair")
        self.canvas.configure(cursor=cursor)
        self.redraw()

    def get_buses(self) -> dict[str, DiagramBus]:
        return self._buses

    def get_connections(self) -> dict[str, DiagramConnection]:
        return self._connections

    def get_selection(self) -> Optional[tuple[str, str]]:
        return self._selection

    def clear(self) -> None:
        self._buses.clear()
        self._connections.clear()
        self._selection = None
        self.redraw()

    # ── Coordinate helpers ────────────────────────────────────────────────

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

    def _draw_grid(self) -> None:
        w = self.canvas.winfo_width()  or 800
        h = self.canvas.winfo_height() or 600
        # Light grey dot-grid every 20 world units
        step = 20 * self._scale
        if step < 8:
            return
        x0 = self._offset_x % step
        y0 = self._offset_y % step
        x = x0
        while x < w:
            y = y0
            while y < h:
                self.canvas.create_oval(x-1, y-1, x+1, y+1, fill="#DDDDDD", outline="")
                y += step
            x += step

    def _draw_bus(self, bus: DiagramBus) -> None:
        sx1, sy = self._w2s(bus.x1, bus.y)
        sx2, _  = self._w2s(bus.x2, bus.y)
        sel = self._selection == ("bus", bus.id)
        colour = "#0066CC" if sel else "black"
        self.canvas.create_line(sx1, sy, sx2, sy, width=BUS_WIDTH, fill=colour, capstyle=tk.ROUND)
        # Label above
        cx = (sx1 + sx2) / 2
        self.canvas.create_text(cx, sy - 12, text=bus.name,
                                font=("TkDefaultFont", 9, "bold"), fill=colour, anchor="s")
        # kV below
        self.canvas.create_text(cx, sy + 10, text=f"{bus.kv} kV",
                                font=("TkDefaultFont", 8), fill="#555555", anchor="n")

    def _draw_connection(self, conn: DiagramConnection) -> None:
        from_bus = self._buses.get(conn.from_bus)
        if from_bus is None:
            return
        fx = from_bus.nearest_tap(conn.from_x)
        fsx, fsy = self._w2s(fx, from_bus.y)
        end = conn.end_point(self._buses)
        if end is None:
            return
        esx, esy = self._w2s(*end)

        sel = self._selection == ("conn", conn.id)
        colour = "#0066CC" if sel else "black"

        if conn.kind == "transformer":
            self._draw_transformer_line(fsx, fsy, esx, esy, colour)
        else:
            self.canvas.create_line(fsx, fsy, esx, esy, width=LINE_WIDTH, fill=colour)

        # Breaker symbol near the from end
        if conn.has_breaker_from:
            self._draw_breaker_on_line(fsx, fsy, esx, esy, t=0.2, colour=colour)

        # Load triangle for feeders
        if conn.kind == "feeder":
            self._draw_load_symbol(esx, esy, colour)

        # Label at midpoint
        mx, my = (fsx + esx) / 2, (fsy + esy) / 2
        self.canvas.create_text(mx + 6, my, text=conn.name,
                                font=("TkDefaultFont", 8), fill="#333333", anchor="w")

    def _draw_breaker_on_line(self, x1, y1, x2, y2, t: float, colour: str) -> None:
        bx = x1 + (x2 - x1) * t
        by = y1 + (y2 - y1) * t
        half = 5 * self._scale
        self.canvas.create_rectangle(
            bx - half, by - half, bx + half, by + half,
            fill=colour, outline=colour,
        )

    def _draw_transformer_line(self, x1, y1, x2, y2, colour: str) -> None:
        self.canvas.create_line(x1, y1, x2, y2, width=LINE_WIDTH, fill=colour)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        r = 12 * self._scale
        gap = r * 0.4
        dx = (x2 - x1)
        dy = (y2 - y1)
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length   # perpendicular (not used — circles along line)
        lx, ly = dx / length, dy / length     # unit along line
        # Two circles overlapping along the line direction
        for sign in (-1, 1):
            cx = mx + sign * gap * lx
            cy = my + sign * gap * ly
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    outline=colour, fill="white", width=LINE_WIDTH)

    def _draw_load_symbol(self, x: float, y: float, colour: str) -> None:
        s = 10 * self._scale
        self.canvas.create_polygon(
            x, y, x - s, y + s * 1.5, x + s, y + s * 1.5,
            fill="white", outline=colour, width=LINE_WIDTH,
        )

    # ── Hit testing ───────────────────────────────────────────────────────

    def _hit_bus(self, wx: float, wy: float) -> Optional[str]:
        """Return bus id if (wx, wy) is within tolerance of a bus."""
        for bus in self._buses.values():
            if bus.hit(wx, wy, tol=SNAP_TOL / self._scale):
                return bus.id
        return None

    def _hit_connection(self, sx: float, sy: float) -> Optional[str]:
        """Return connection id if screen point (sx, sy) is close to a connection line."""
        tol = 8
        for conn in self._connections.values():
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            d = _point_to_segment_dist(sx, sy, x1, y1, x2, y2)
            if d < tol:
                return conn.id
        return None

    def _snap_to_bus(self, wx: float, wy: float) -> Optional[str]:
        return self._hit_bus(wx, wy)

    # ── Mouse events ──────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT:
            bus_id  = self._hit_bus(wx, wy)
            conn_id = self._hit_connection(event.x, event.y)
            if bus_id:
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
            bus_id = self._snap_to_bus(wx, wy)
            if self._conn_from_bus is None:
                if bus_id:
                    self._conn_from_bus = bus_id
                    self._conn_from_x   = wx
                    if self._on_status:
                        self._on_status(f"From bus '{self._buses[bus_id].name}' — now click the destination.")
            else:
                self._finish_connection(wx, wy, bus_id)

        elif self._tool == TOOL_DELETE:
            bus_id  = self._hit_bus(wx, wy)
            conn_id = self._hit_connection(event.x, event.y)
            if bus_id:
                self._delete_bus(bus_id)
            elif conn_id:
                self._connections.pop(conn_id, None)
                self._set_selection(None, None)
                self.redraw()

    def _on_drag(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT and self._drag_bus_id and self._drag_origin:
            bus = self._buses[self._drag_bus_id]
            dx  = wx - self._drag_origin[0]
            bus.x1 += dx
            bus.x2 += dx
            bus.y  += wy - self._drag_origin[1]
            self._drag_origin = (wx, wy)
            self.redraw()

        elif self._tool == TOOL_BUS and self._bus_draw_start:
            # Preview the bus being drawn
            self.redraw()
            sx1, sy1 = self._w2s(*self._bus_draw_start)
            self.canvas.create_line(
                sx1, sy1, event.x, sy1,
                width=BUS_WIDTH, fill="#888888", dash=(4, 4),
            )

    def _on_release(self, event: tk.Event) -> None:
        if self._tool == TOOL_BUS and self._bus_draw_start:
            wx, wy = self._s2w(event.x, event.y)
            x1, y0 = self._bus_draw_start
            x2 = wx
            if abs(x2 - x1) > 10 / self._scale:  # minimum length
                bid = f"BUS-{len(self._buses)+1}"
                bus = DiagramBus(id=bid, name=bid, kv=0.0,
                                 x1=min(x1, x2), y=y0, x2=max(x1, x2))
                self._buses[bid] = bus
                self._set_selection("bus", bid)
            self._bus_draw_start = None
            self.redraw()

        self._drag_bus_id = None
        self._drag_origin = None

    def _on_motion(self, event: tk.Event) -> None:
        """Draw a preview line while waiting for a connection target."""
        if self._conn_from_bus and self._tool in (TOOL_TLINE, TOOL_FEEDER, TOOL_TRANSFORMER):
            self.redraw()
            bus = self._buses.get(self._conn_from_bus)
            if bus:
                sx, sy = self._w2s(bus.nearest_tap(self._conn_from_x), bus.y)
                self.canvas.create_line(
                    sx, sy, event.x, event.y,
                    width=LINE_WIDTH, fill="#888888", dash=(4, 4),
                )

    def _finish_connection(self, wx: float, wy: float, to_bus_id: Optional[str]) -> None:
        kind     = {TOOL_TLINE: "tline", TOOL_FEEDER: "feeder",
                    TOOL_TRANSFORMER: "transformer"}[self._tool]
        from_bus = self._buses.get(self._conn_from_bus)
        if from_bus is None:
            self._conn_from_bus = None
            return

        cid  = f"{kind.upper()}-{len(self._connections)+1}"
        name = cid

        if kind == "feeder":
            conn = DiagramConnection(
                id=cid, name=name, kind=kind,
                from_bus=self._conn_from_bus,
                from_x=self._conn_from_x,
                to_point=(wx, wy),
            )
        elif to_bus_id and to_bus_id != self._conn_from_bus:
            to_bus = self._buses[to_bus_id]
            conn = DiagramConnection(
                id=cid, name=name, kind=kind,
                from_bus=self._conn_from_bus,
                from_x=self._conn_from_x,
                to_bus=to_bus_id,
                to_x=wx,
            )
        else:
            self._conn_from_bus = None
            return

        self._connections[cid] = conn
        self._set_selection("conn", cid)
        self._conn_from_bus = None
        self.redraw()

    def _delete_bus(self, bus_id: str) -> None:
        self._buses.pop(bus_id, None)
        # Remove all connections that reference this bus
        dead = [cid for cid, c in self._connections.items()
                if c.from_bus == bus_id or c.to_bus == bus_id]
        for cid in dead:
            self._connections.pop(cid)
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
        self._scale   *= factor
        self._scale    = max(0.2, min(self._scale, 8.0))
        self.redraw()

    # ── Selection ─────────────────────────────────────────────────────────

    def _set_selection(self, kind: Optional[str], elem_id: Optional[str]) -> None:
        self._selection = (kind, elem_id) if kind else None
        if self._on_select:
            self._on_select(self._selection)
        self.redraw()


# ── Geometry utility ─────────────────────────────────────────────────────────

def _point_to_segment_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
