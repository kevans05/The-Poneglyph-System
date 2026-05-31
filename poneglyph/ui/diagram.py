"""One-line diagram canvas — paint-app style.

Tools:
  Select        — click to select, drag elements
  Bus           — multi-click polyline with 90° snapping; right-click or double-click to finish
  T-Line        — click bus → click bus
  Feeder        — click bus → click empty point (dangling load end)
  Transformer   — click anywhere to place; near a bus = snaps top terminal to it
  Source        — click anywhere to place a grid/generator source (slack)
  Load          — click anywhere to place a load (PQ)
  CT            — click on an existing connection line
  VT            — click on a bus
  Delete        — click any element to remove it

Visual conventions (IEC 60617):
  Bus           — thick polyline (horizontal/vertical segments), name above, kV below
  T-Line/Feeder — thin line; breaker shown as small filled square
  Transformer   — two coupled coil windings with an iron core between them;
                  winding-connection indicators (wye / delta / zigzag) alongside
  Source        — circle with a sine wave (AC source)
  Load          — downward filled arrow
  CT            — circle around the conductor + secondary lead
  VT            — winding bumps hanging from a bus tap, IEC ground symbol
"""

from __future__ import annotations

import cmath
import math
import tkinter as tk
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Transformer world-space geometry constants ───────────────────────────────
# All in world units so the symbol is correctly proportioned at any zoom level.
# IEC 60617 coupled-coil symbol: two horizontal coil rows (HV above, LV below),
# bumps facing outward (up/down), iron-core horizontal lines between them,
# centre conductor runs vertically top-to-bottom connecting the buses.

XFMR_BR   = 7.0    # winding bump radius (world units)
XFMR_NB   = 3      # bumps per winding
XFMR_CORE = 30.0   # gap between the two coil rows (iron-core region)
XFMR_LEAD = 14.0   # straight lead from terminal to the first coil row
XFMR_IND  = 9.0    # winding-connection indicator glyph size (world units)

_WIND_SPAN = XFMR_NB * 2 * XFMR_BR                    # 42 — horizontal span of each coil
XFMR_HALF  = XFMR_LEAD + XFMR_CORE / 2               # centre → terminal (= 29)

# ── Source / Load geometry ────────────────────────────────────────────────────
SRC_R       = 16.0   # AC source circle radius (world units)
SRC_OFFSET  = SRC_R * 2 + 16   # source centre distance above its bus
LOAD_AH     = 12.0   # load arrowhead height (world units)
LOAD_AW     = 7.0    # load arrowhead half-width (world units)
LOAD_LEAD   = 30.0   # load lead length from bus to arrowhead base

GRID_SIZE   = 20.0   # world units per grid cell (matches _draw_grid step)

# ── Element data models ──────────────────────────────────────────────────────

@dataclass
class DiagramBus:
    id: str
    name: str
    kv: float
    nodes: list   # list[tuple[float, float]] — world-space (x, y) for each node
    edges: list   # list[tuple[int, int]]     — pairs of node indices forming segments
    v_solved: Optional[complex] = None   # per-unit voltage phasor after a solve
    label_ox: float = 0.0
    label_oy: float = 0.0

    @property
    def cx(self) -> float:
        if not self.nodes:
            return 0.0
        return sum(x for x, y in self.nodes) / len(self.nodes)

    @property
    def cy_label(self) -> float:
        if not self.nodes:
            return 0.0
        return min(y for x, y in self.nodes)

    def nearest_tap(self, wx: float, wy: float) -> tuple:
        """Project (wx,wy) onto the nearest edge segment; return clamped world point."""
        best_pt = self.nodes[0] if self.nodes else (wx, wy)
        best_d  = float("inf")
        for i, j in self.edges:
            x1, y1 = self.nodes[i]
            x2, y2 = self.nodes[j]
            dx, dy  = x2 - x1, y2 - y1
            length_sq = dx*dx + dy*dy
            if length_sq < 1e-9:
                px, py = x1, y1
            else:
                t = max(0.0, min(1.0, ((wx-x1)*dx + (wy-y1)*dy) / length_sq))
                px, py = x1 + t*dx, y1 + t*dy
            d = math.hypot(wx - px, wy - py)
            if d < best_d:
                best_d  = d
                best_pt = (px, py)
        return best_pt

    def hit(self, wx: float, wy: float, tol: float = 8) -> bool:
        for i, j in self.edges:
            x1, y1 = self.nodes[i]
            x2, y2 = self.nodes[j]
            dx, dy  = x2 - x1, y2 - y1
            length_sq = dx*dx + dy*dy
            if length_sq < 1e-9:
                if math.hypot(wx-x1, wy-y1) <= tol:
                    return True
            else:
                t = max(0.0, min(1.0, ((wx-x1)*dx + (wy-y1)*dy) / length_sq))
                px, py = x1 + t*dx, y1 + t*dy
                if math.hypot(wx-px, wy-py) <= tol:
                    return True
        return False


@dataclass
class DiagramConnection:
    """T-line or feeder between buses (or to a free end point)."""
    id: str
    name: str
    kind: str           # "tline" | "feeder"
    from_bus: str
    from_tap: tuple = (0.0, 0.0)          # world (x, y) tap point on from_bus
    to_bus: Optional[str] = None
    to_tap: Optional[tuple] = None        # world (x, y) tap point on to_bus
    to_point: Optional[tuple] = None
    has_breaker_from: bool = True
    r_pu: float = 0.01
    x_pu: float = 0.10
    label_ox: float = 0.0
    label_oy: float = 0.0

    def start_point(self, buses: dict) -> Optional[tuple]:
        b = buses.get(self.from_bus)
        if b is None:
            return None
        return b.nearest_tap(*self.from_tap)

    def end_point(self, buses: dict) -> Optional[tuple]:
        if self.to_bus:
            b = buses.get(self.to_bus)
            if b is None:
                return None
            tap = self.to_tap if self.to_tap else (b.nodes[0] if b.nodes else (0.0, 0.0))
            return b.nearest_tap(*tap)
        return self.to_point


@dataclass
class DiagramTransformer:
    """Standalone transformer component — placed on the canvas, terminals optionally
    snapped to buses."""
    id: str
    name: str
    cx: float           # centre x (world)
    cy: float           # centre y (world) — midpoint between the two windings
    hv_bus: Optional[str] = None    # top terminal bus
    hv_tap_x: float = 0.0
    hv_tap_y: float = 0.0
    lv_bus: Optional[str] = None    # bottom terminal bus
    lv_tap_x: float = 0.0
    lv_tap_y: float = 0.0
    # Ratings / electrical
    mva: float = 10.0               # power rating (MVA)
    hv_kv: float = 0.0              # nominal HV winding voltage (kV)
    lv_kv: float = 0.0              # nominal LV winding voltage (kV)
    z_pct: float = 10.0             # impedance (%Z on own MVA base)
    tap_changer: str = "None"       # "None" | "LTC" | "DETC"
    r_pu: float = 0.01              # kept for the solver fallback
    x_pu: float = 0.10
    # Winding configuration (IEC 60617)
    hv_winding:  str  = "wye"       # "wye" | "delta" | "zigzag"
    lv_winding:  str  = "delta"
    hv_grounded: bool = True        # neutral grounded (wye/zigzag only)
    lv_grounded: bool = False
    label_ox: float = 0.0
    label_oy: float = 0.0
    rotation: int = 0               # degrees CCW: 0 / 90 / 180 / 270

    @property
    def top_y(self) -> float:
        return self.cy - XFMR_HALF

    @property
    def bot_y(self) -> float:
        return self.cy + XFMR_HALF

    @property
    def hv_terminal(self) -> tuple:
        r = self.rotation % 360
        if r == 90:  return (self.cx + XFMR_HALF, self.cy)
        if r == 180: return (self.cx, self.cy + XFMR_HALF)
        if r == 270: return (self.cx - XFMR_HALF, self.cy)
        return (self.cx, self.cy - XFMR_HALF)

    @property
    def lv_terminal(self) -> tuple:
        r = self.rotation % 360
        if r == 90:  return (self.cx - XFMR_HALF, self.cy)
        if r == 180: return (self.cx, self.cy - XFMR_HALF)
        if r == 270: return (self.cx + XFMR_HALF, self.cy)
        return (self.cx, self.cy + XFMR_HALF)

    @property
    def voltage_ratio(self) -> str:
        if self.hv_kv and self.lv_kv:
            return f"{self.hv_kv:g} : {self.lv_kv:g} kV"
        return "—"


@dataclass
class DiagramSource:
    """Grid / generator source. Defines the slack bus when attached to a bus."""
    id: str
    name: str
    cx: float
    cy: float
    bus: Optional[str] = None
    tap_x: float = 0.0
    tap_y: float = 0.0
    v_pu: float = 1.0
    angle_deg: float = 0.0
    base_kv: float = 0.0
    label_ox: float = 0.0
    label_oy: float = 0.0


@dataclass
class DiagramLoad:
    """Constant-power (PQ) load — balanced 3-phase or individual phases."""
    id: str
    name: str
    cx: float
    cy: float
    bus: Optional[str] = None
    tap_x: float = 0.0
    tap_y: float = 0.0
    # ── Phase mode ────────────────────────────────────────────────────────
    phase_mode: str = "balanced"   # "balanced" | "individual"
    # ── Balanced-mode spec ────────────────────────────────────────────────
    spec_mode: str = "P+Q"
    p_kw:   float = 1000.0
    q_kvar: float = 500.0
    s_kva:  float = 0.0
    pf:     float = 0.9
    v_kv:   float = 13.8
    i_amps: float = 50.0
    lagging: bool = True
    # ── Per-phase spec (individual mode) ─────────────────────────────────
    spec_mode_a: str = "P+Q"; p_kw_a: float = 333.0; q_kvar_a: float = 167.0
    s_kva_a: float = 0.0; pf_a: float = 0.9; v_kv_a: float = 13.8
    i_amps_a: float = 17.0; lagging_a: bool = True
    spec_mode_b: str = "P+Q"; p_kw_b: float = 333.0; q_kvar_b: float = 167.0
    s_kva_b: float = 0.0; pf_b: float = 0.9; v_kv_b: float = 13.8
    i_amps_b: float = 17.0; lagging_b: bool = True
    spec_mode_c: str = "P+Q"; p_kw_c: float = 333.0; q_kvar_c: float = 167.0
    s_kva_c: float = 0.0; pf_c: float = 0.9; v_kv_c: float = 13.8
    i_amps_c: float = 17.0; lagging_c: bool = True
    # ─────────────────────────────────────────────────────────────────────
    label_ox: float = 0.0
    label_oy: float = 0.0

    # ── Helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _resolve_spec(spec_mode: str, p_kw: float, q_kvar: float, s_kva: float,
                      pf: float, v_kv: float, i_amps: float, lagging: bool) -> tuple:
        """Return (p_kw, q_kvar) for one set of spec inputs."""
        pf = max(1e-4, min(1.0, pf))
        sign = 1.0 if lagging else -1.0
        m = spec_mode
        if m == "P+Q":
            return p_kw, q_kvar
        if m == "P+PF":
            q = p_kw * math.sqrt(1 - pf**2) / pf
            return p_kw, sign * abs(q)
        if m == "kVAR+PF":
            p = abs(q_kvar) * pf / math.sqrt(max(1e-9, 1 - pf**2))
            return p, sign * abs(q_kvar)
        if m == "kVA+PF":
            p = s_kva * pf; q = s_kva * math.sqrt(1 - pf**2)
            return p, sign * q
        if m == "V+I+PF":
            s = math.sqrt(3) * v_kv * i_amps
            p = s * pf; q = s * math.sqrt(1 - pf**2)
            return p, sign * q
        return p_kw, q_kvar

    def _resolved(self) -> tuple:
        """Return total 3-phase (p_kw, q_kvar)."""
        if self.phase_mode == "individual":
            pa, qa = self._resolve_spec(self.spec_mode_a, self.p_kw_a, self.q_kvar_a,
                                        self.s_kva_a, self.pf_a, self.v_kv_a,
                                        self.i_amps_a, self.lagging_a)
            pb, qb = self._resolve_spec(self.spec_mode_b, self.p_kw_b, self.q_kvar_b,
                                        self.s_kva_b, self.pf_b, self.v_kv_b,
                                        self.i_amps_b, self.lagging_b)
            pc, qc = self._resolve_spec(self.spec_mode_c, self.p_kw_c, self.q_kvar_c,
                                        self.s_kva_c, self.pf_c, self.v_kv_c,
                                        self.i_amps_c, self.lagging_c)
            return pa + pb + pc, qa + qb + qc
        return self._resolve_spec(self.spec_mode, self.p_kw, self.q_kvar,
                                  self.s_kva, self.pf, self.v_kv,
                                  self.i_amps, self.lagging)

    def _resolved_phases(self) -> list:
        """Return [(p_kw, q_kvar)] × 3 phases."""
        if self.phase_mode == "individual":
            return [
                self._resolve_spec(self.spec_mode_a, self.p_kw_a, self.q_kvar_a,
                                   self.s_kva_a, self.pf_a, self.v_kv_a,
                                   self.i_amps_a, self.lagging_a),
                self._resolve_spec(self.spec_mode_b, self.p_kw_b, self.q_kvar_b,
                                   self.s_kva_b, self.pf_b, self.v_kv_b,
                                   self.i_amps_b, self.lagging_b),
                self._resolve_spec(self.spec_mode_c, self.p_kw_c, self.q_kvar_c,
                                   self.s_kva_c, self.pf_c, self.v_kv_c,
                                   self.i_amps_c, self.lagging_c),
            ]
        p, q = self._resolved()
        return [(p/3, q/3)] * 3

    @property
    def p_mw(self) -> float:
        return self._resolved()[0] / 1000.0

    @property
    def q_mvar(self) -> float:
        return self._resolved()[1] / 1000.0

    def summary_str(self) -> str:
        p, q = self._resolved()
        s = math.sqrt(p**2 + q**2)
        pf = p / s if s > 0 else 0.0
        lag = "lag" if q >= 0 else "lead"
        if self.phase_mode == "individual":
            phases = self._resolved_phases()
            lines = []
            for ph, (pp, pq) in zip("ABC", phases):
                lines.append(f"Ph{ph}: {pp:g} kW  {pq:g} kVAR")
            lines.append(f"Tot: {p:g} kW  PF={pf:.3f} {lag}")
            return "\n".join(lines)
        return f"{p:g} kW  {q:g} kVAR\n{s:.0f} kVA  PF={pf:.3f} {lag}"


@dataclass
class DiagramCT:
    id: str
    name: str
    connection_id: str       # DiagramConnection id, or "" when on a transformer lead
    t: float = 0.5
    # ── Nameplate / protection data ───────────────────────────────────────
    ratio_primary:   int   = 1200     # primary amps (e.g. 1200 in 1200:5)
    ratio_secondary: int   = 5        # secondary amps (e.g. 5 in 1200:5)
    accuracy_class_relay:   str = "C200"  # IEEE C-class for relaying (C50/C100/C200/C400/C800)
    accuracy_class_metering: str = "0.3"  # ANSI metering class (0.1/0.3/0.6/1.2)
    burden_va: float = 20.0           # secondary burden (VA)
    rating_factor: float = 1.0        # continuous current rating factor (RF)
    num_taps: int = 1                 # 1 = single ratio; >1 = multi-ratio taps
    tap_ratios: str = ""              # comma-sep list of tap ratios e.g. "600:5,900:5,1200:5"
    polarity_standard: bool = True    # True = standard dot polarity (IEC/IEEE)
    # ── Winding configurations ────────────────────────────────────────────
    primary_config:   str = "Series"          # Series | Parallel | Window (core-balance)
    secondary_config: str = "Wye"             # Wye | Delta | Open-Delta | Zero-Sequence
    # ── Placement ─────────────────────────────────────────────────────────
    xfmr_id: str = ""        # transformer id when placed on a lead (else "")
    xfmr_lead: str = ""      # "hv" or "lv"
    label_ox: float = 0.0
    label_oy: float = 0.0

    @property
    def ratio_str(self) -> str:
        return f"{self.ratio_primary}:{self.ratio_secondary}A"


@dataclass
class DiagramVT:
    id: str
    name: str
    bus_id: str
    tap_x: float
    tap_y: float = 0.0
    ratio: str = "11000/110"


@dataclass
class DiagramBreaker:
    id: str
    name: str
    connection_id: str   # which DiagramConnection this lives on
    t: float = 0.5       # position along the connection (0=start, 1=end)
    closed: bool = True


@dataclass
class DiagramDisconnect:
    id: str
    name: str
    connection_id: str
    t: float = 0.5
    closed: bool = True


# ── Tool constants ────────────────────────────────────────────────────────────

TOOL_SELECT      = "select"
TOOL_BUS         = "bus"
TOOL_TLINE       = "tline"
TOOL_FEEDER      = "feeder"
TOOL_TRANSFORMER = "transformer"
TOOL_SOURCE      = "source"
TOOL_LOAD        = "load"
TOOL_CT          = "ct"
TOOL_VT          = "vt"
TOOL_DELETE      = "delete"
TOOL_BREAKER     = "breaker"
TOOL_DISCONNECT  = "disconnect"

TOOL_HINTS = {
    TOOL_SELECT:      "Select: click to select; drag a bus, transformer, source or load to move it.",
    TOOL_BUS:         "Bus: click to place nodes (90° constrained). Double-click or right-click to finish. Creates branching shapes.",
    TOOL_TLINE:       "T-Line: click a source bus, then click a destination bus.",
    TOOL_FEEDER:      "Feeder: click a bus, then click an empty point for the load end.",
    TOOL_TRANSFORMER: "Transformer: click to place. Near a bus → snaps to it automatically.",
    TOOL_SOURCE:      "Power Source: click to place. Near a bus → snaps to it (defines the slack bus).",
    TOOL_LOAD:        "Load: click to place. Near a bus → snaps to it.",
    TOOL_CT:          "Current Transformer: click on an existing line.",
    TOOL_VT:          "Voltage Transformer: click on a bus.",
    TOOL_DELETE:      "Delete: click any element to remove it.",
    TOOL_BREAKER:     "Circuit Breaker: click on an existing connection line to place a breaker.",
    TOOL_DISCONNECT:  "Disconnect Switch: click on an existing connection line to place a disconnect switch.",
}

BUS_WIDTH  = 4
LINE_WIDTH = 2
SNAP_TOL   = 16      # pixels for bus hit-tests
XFMR_SNAP  = 56      # pixels tolerance for transformer/source/load bus-snap

# Default voltage-level colour map (kV → hex colour).
# Keys are nominal kV values; _voltage_colour() picks the nearest one.
DEFAULT_VOLT_COLOURS: dict = {
    765:  "#8B008B",   # dark magenta
    500:  "#800080",   # purple
    345:  "#0000CD",   # medium blue
    230:  "#008080",   # teal
    138:  "#FF8C00",   # dark orange
    115:  "#FFA500",   # orange
    69:   "#DAA520",   # goldenrod
    34.5: "#8B4513",   # saddle brown
    13.8: "#00CED1",   # dark turquoise  (green reserved for closed devices)
    4.16: "#40C4FF",   # light blue      (green reserved for closed devices)
    0.48: "#808080",   # gray
}


# ── Diagram canvas ────────────────────────────────────────────────────────────

class Diagram(tk.Frame):
    """Paint-app one-line diagram editor."""

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Optional[Callable] = None,
        on_status: Optional[Callable] = None,
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._on_status = on_status

        self._buses:        dict = {}
        self._connections:  dict = {}
        self._transformers: dict = {}
        self._sources:      dict = {}
        self._loads:        dict = {}
        self._cts:          dict = {}
        self._vts:          dict = {}
        self._breakers:     dict = {}
        self._disconnects:  dict = {}

        self._volt_colours: dict = dict(DEFAULT_VOLT_COLOURS)

        self._tool = TOOL_SELECT
        self._selection = None

        self._scale    = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0

        self._drag_id:        Optional[str]   = None
        self._drag_kind:      Optional[str]   = None
        self._drag_origin:    Optional[tuple] = None
        self._drag_node_idx:  Optional[int]   = None   # bus-node being dragged
        self._drag_axis:      Optional[str]   = None   # "h" | "v" | "free" — locked at drag start
        self._term_anchor:    Optional[tuple] = None   # screen (sx,sy) of the fixed terminal end
        self._snap_grid_on:   bool            = True   # snap all placements/drags to grid
        self._conn_from_bus:  Optional[str]   = None
        self._conn_from_tap:  tuple           = (0.0, 0.0)
        self._pan_start_pt:   Optional[tuple] = None
        self._sticky_tool:    bool            = False   # hold-Shift keeps tool active

        # Bus polyline drawing state
        self._bus_draw_nodes: list = []   # accumulated world-space nodes
        self._preview_point:  Optional[tuple] = None   # live cursor position for preview

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
        self.canvas.bind("<ButtonPress-3>",   self._on_right_press)
        self.canvas.bind("<B3-Motion>",       self._pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._pan_end)
        self.canvas.bind("<MouseWheel>",      self._scroll)
        self.canvas.bind("<Button-4>",        self._scroll)
        self.canvas.bind("<Button-5>",        self._scroll)
        self.canvas.bind("<Configure>",       lambda _e: self.redraw())
        self.canvas.bind("<Motion>",          self._on_motion)
        self.canvas.bind("<Escape>",          self._on_escape)

    # ── Public API ────────────────────────────────────────────────────────

    def set_tool(self, tool: str, sticky: bool = False) -> None:
        self._tool        = tool
        self._sticky_tool = sticky
        self._conn_from_bus  = None
        # Cancel any in-progress bus drawing
        self._bus_draw_nodes = []
        self._preview_point  = None
        if self._on_status:
            hint = TOOL_HINTS.get(tool, "")
            if tool == TOOL_BUS:
                hint = "Bus: click to place first node."
            if sticky:
                hint += "  [STICKY — hold Shift or press key again to keep tool]"
            self._on_status(hint)
        cursor = {TOOL_SELECT: "arrow", TOOL_DELETE: "X_cursor"}.get(tool, "crosshair")
        self.canvas.configure(cursor=cursor)
        self.redraw()

    def _revert_to_select(self, event: Optional[tk.Event] = None) -> None:
        """After a single placement, revert to select unless sticky or Shift held."""
        shift_held = event and bool(event.state & 0x0001)
        if not self._sticky_tool and not shift_held:
            self.set_tool(TOOL_SELECT)

    def get_buses(self)        -> dict: return self._buses
    def get_connections(self)  -> dict: return self._connections
    def get_transformers(self) -> dict: return self._transformers
    def get_sources(self)      -> dict: return self._sources
    def get_loads(self)        -> dict: return self._loads
    def get_cts(self)          -> dict: return self._cts
    def get_vts(self)          -> dict: return self._vts
    def get_breakers(self)     -> dict: return self._breakers
    def get_disconnects(self)  -> dict: return self._disconnects
    def get_selection(self)    -> Optional[tuple]: return self._selection

    def get_volt_colours(self) -> dict:
        return self._volt_colours

    def set_volt_colours(self, mapping: dict) -> None:
        self._volt_colours = dict(mapping)
        self.redraw()

    _UNSET_COLOUR = "#333333"   # neutral dark for elements with no voltage level set

    def _voltage_colour(self, kv: float, selected: bool = False) -> str:
        """Return the colour for a given voltage level (kV)."""
        if selected:
            return "#0066CC"
        if not self._volt_colours or kv <= 0:
            return self._UNSET_COLOUR
        nearest = min(self._volt_colours, key=lambda v: abs(v - kv))
        if abs(nearest - kv) / max(nearest, 1) > 0.25:
            return self._UNSET_COLOUR   # no close match — don't mis-colour
        return self._volt_colours[nearest]

    def clear(self) -> None:
        self._buses.clear()
        self._connections.clear()
        self._transformers.clear()
        self._sources.clear()
        self._loads.clear()
        self._cts.clear()
        self._vts.clear()
        self._breakers.clear()
        self._disconnects.clear()
        self._selection = None
        self._bus_draw_nodes = []
        self._preview_point  = None
        self.redraw()

    def clear_results(self) -> None:
        """Forget the last power-flow solution (clears voltage annotations)."""
        for bus in self._buses.values():
            bus.v_solved = None
        self.redraw()

    # ── Coordinates ───────────────────────────────────────────────────────

    def _w2s(self, wx: float, wy: float) -> tuple:
        return wx * self._scale + self._offset_x, wy * self._scale + self._offset_y

    def _s2w(self, sx: float, sy: float) -> tuple:
        return (sx - self._offset_x) / self._scale, (sy - self._offset_y) / self._scale

    # ── Redraw ────────────────────────────────────────────────────────────

    def _sg(self, wx: float, wy: float) -> tuple:
        """Snap world point to grid if snap is enabled."""
        if not self._snap_grid_on:
            return wx, wy
        return (round(wx / GRID_SIZE) * GRID_SIZE,
                round(wy / GRID_SIZE) * GRID_SIZE)

    def rotate_selected(self) -> None:
        """Rotate the selected transformer 90° CCW."""
        if self._selection is None:
            return
        kind, eid = self._selection
        if kind == "transformer" and eid in self._transformers:
            xfmr = self._transformers[eid]
            xfmr.rotation = (xfmr.rotation + 90) % 360
            self.redraw()

    def toggle_selected_device(self) -> None:
        """Toggle open/closed state of the selected breaker or disconnect."""
        if self._selection is None:
            return
        kind, eid = self._selection
        if kind == "breaker" and eid in self._breakers:
            self._breakers[eid].closed = not self._breakers[eid].closed
            self.redraw()
        elif kind == "disconnect" and eid in self._disconnects:
            self._disconnects[eid].closed = not self._disconnects[eid].closed
            self.redraw()

    def toggle_snap_grid(self) -> None:
        self._snap_grid_on = not self._snap_grid_on
        if self._on_status:
            state = "ON" if self._snap_grid_on else "OFF"
            self._on_status(f"Grid snap {state}  (G to toggle)")
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._draw_grid()
        for conn in self._connections.values():
            self._draw_connection(conn)
        for xfmr in self._transformers.values():
            self._draw_transformer(xfmr)
        for src in self._sources.values():
            self._draw_source(src)
        for ld in self._loads.values():
            self._draw_load(ld)
        for bus in self._buses.values():
            self._draw_bus(bus)
        for ct in self._cts.values():
            self._draw_ct(ct)
        for vt in self._vts.values():
            self._draw_vt(vt)
        # Draw in-progress bus preview
        self._draw_bus_preview()

    def _draw_grid(self) -> None:
        w = self.canvas.winfo_width()  or 800
        h = self.canvas.winfo_height() or 600
        step = GRID_SIZE * self._scale
        if step < 6:
            return
        dot_col  = "#BBBBBB" if self._snap_grid_on else "#EEEEEE"
        dot_r    = 1.5 if self._snap_grid_on else 1
        x = self._offset_x % step
        while x < w:
            y = self._offset_y % step
            while y < h:
                self.canvas.create_oval(x - dot_r, y - dot_r,
                                        x + dot_r, y + dot_r,
                                        fill=dot_col, outline="")
                y += step
            x += step

    # ── Bus ───────────────────────────────────────────────────────────────

    def _draw_bus(self, bus: DiagramBus) -> None:
        sel    = self._selection == ("bus", bus.id)
        colour = self._voltage_colour(bus.kv, selected=sel)

        for i, j in bus.edges:
            sx1, sy1 = self._w2s(*bus.nodes[i])
            sx2, sy2 = self._w2s(*bus.nodes[j])
            self.canvas.create_line(sx1, sy1, sx2, sy2,
                                    width=BUS_WIDTH, fill=colour, capstyle=tk.ROUND)

        # Branch-node dots (degree >= 3 only)
        degree = Counter()
        for i, j in bus.edges:
            degree[i] += 1
            degree[j] += 1
        for ni, (nx, ny) in enumerate(bus.nodes):
            if degree[ni] >= 3:
                sx, sy = self._w2s(nx, ny)
                r = BUS_WIDTH * self._scale
                self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, fill=colour, outline=colour)

        # When selected: draw draggable node handles and mid-segment add-node hints
        if sel:
            hr = max(5, 5 * self._scale)
            for ni, (nx, ny) in enumerate(bus.nodes):
                sx, sy = self._w2s(nx, ny)
                self.canvas.create_rectangle(sx-hr, sy-hr, sx+hr, sy+hr,
                                             outline="#0066CC", fill="white", width=2)
            # Mid-point diamonds on each segment — shift-click to insert node
            for i, j in bus.edges:
                mx = (bus.nodes[i][0] + bus.nodes[j][0]) / 2
                my = (bus.nodes[i][1] + bus.nodes[j][1]) / 2
                sx, sy = self._w2s(mx, my)
                dm = max(4, 4 * self._scale)
                self.canvas.create_polygon(sx, sy-dm, sx+dm, sy, sx, sy+dm, sx-dm, sy,
                                           outline="#0066CC", fill="#CCE5FF", width=1)

        # Name label at top-centre (offset if user has dragged it)
        lx_w = bus.cx + bus.label_ox
        ly_w = bus.cy_label + bus.label_oy
        cxs, cys = self._w2s(lx_w, ly_w)
        self.canvas.create_text(cxs, cys - 12, text=bus.name,
                                font=("TkDefaultFont", 9, "bold"), fill=colour, anchor="s")
        if bus.kv:
            self.canvas.create_text(cxs, cys - 2, text=f"{bus.kv} kV",
                                    font=("TkDefaultFont", 8), fill=colour, anchor="n")
        if bus.v_solved is not None:
            import cmath as _cm
            mag = abs(bus.v_solved)
            ang = math.degrees(_cm.phase(bus.v_solved))
            kv_actual = mag * bus.kv if bus.kv else 0.0
            txt = f"{mag:.3f} pu ∠{ang:.1f}°"
            if kv_actual:
                txt += f"  ({kv_actual:.2f} kV)"
            self.canvas.create_text(cxs, cys + 14, text=txt,
                                    font=("TkDefaultFont", 8, "bold"), fill="#118811", anchor="n")

    def _draw_bus_preview(self) -> None:
        """Draw in-progress bus polyline as a dashed preview."""
        pts = self._bus_draw_nodes
        if not pts:
            return
        colour = "#888888"
        # Draw already-placed segments
        for k in range(len(pts) - 1):
            sx1, sy1 = self._w2s(*pts[k])
            sx2, sy2 = self._w2s(*pts[k+1])
            self.canvas.create_line(sx1, sy1, sx2, sy2,
                                    width=BUS_WIDTH, fill=colour, dash=(4, 4))
        # Draw preview segment to current cursor position
        if self._preview_point:
            last = pts[-1]
            snapped = self._snap_90(last, *self._preview_point)
            sx1, sy1 = self._w2s(*last)
            sx2, sy2 = self._w2s(*snapped)
            self.canvas.create_line(sx1, sy1, sx2, sy2,
                                    width=BUS_WIDTH, fill=colour, dash=(4, 4))
        # Small dot at first node
        sx, sy = self._w2s(*pts[0])
        r = BUS_WIDTH * self._scale
        self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, fill=colour, outline=colour)

    # ── Connections (T-line / feeder) ─────────────────────────────────────

    def _draw_connection(self, conn: DiagramConnection) -> None:
        start = conn.start_point(self._buses)
        end   = conn.end_point(self._buses)
        if start is None or end is None:
            return
        x1, y1 = self._w2s(*start)
        x2, y2 = self._w2s(*end)
        sel    = self._selection == ("conn", conn.id)
        from_bus = self._buses.get(conn.from_bus)
        kv = from_bus.kv if from_bus else 0.0
        colour = self._voltage_colour(kv, selected=sel)

        # Collect all switching devices on this connection, sorted by t.
        devices = []
        for br in self._breakers.values():
            if br.connection_id == conn.id:
                devices.append((br.t, "breaker", br))
        for dc in self._disconnects.values():
            if dc.connection_id == conn.id:
                devices.append((dc.t, "disconnect", dc))
        devices.sort(key=lambda d: d[0])

        # Also include the legacy has_breaker_from as a pseudo-device.
        if conn.has_breaker_from:
            devices.append((0.15, "_legacy_breaker", None))
            devices.sort(key=lambda d: d[0])

        if not devices:
            self.canvas.create_line(x1, y1, x2, y2, width=LINE_WIDTH, fill=colour)
        else:
            # Draw the line as segments interrupted by device symbols.
            prev_sx, prev_sy = x1, y1
            gap = 10 * self._scale
            for t_dev, dev_kind, dev_obj in devices:
                dx_seg = x1 + (x2 - x1) * t_dev
                dy_seg = y1 + (y2 - y1) * t_dev
                if dev_kind == "_legacy_breaker":
                    # Draw line to device, then legacy filled square symbol.
                    self.canvas.create_line(prev_sx, prev_sy, dx_seg, dy_seg,
                                            width=LINE_WIDTH, fill=colour)
                    self._draw_legacy_breaker_square(dx_seg, dy_seg, colour)
                    prev_sx, prev_sy = dx_seg, dy_seg
                elif dev_kind == "breaker":
                    sw_col = "#00AA00" if dev_obj.closed else "#CC0000"
                    self._draw_breaker_symbol(prev_sx, prev_sy, x1, y1, x2, y2,
                                              t_dev, sw_col, dev_obj, gap)
                    # Advance past gap
                    length = math.hypot(x2 - x1, y2 - y1) or 1
                    dt = gap / length
                    prev_sx = x1 + (x2 - x1) * min(1.0, t_dev + dt)
                    prev_sy = y1 + (y2 - y1) * min(1.0, t_dev + dt)
                elif dev_kind == "disconnect":
                    sw_col = "#00AA00" if dev_obj.closed else "#CC0000"
                    self._draw_disconnect_symbol(prev_sx, prev_sy, x1, y1, x2, y2,
                                                 t_dev, sw_col, dev_obj, gap)
                    length = math.hypot(x2 - x1, y2 - y1) or 1
                    dt = gap / length
                    prev_sx = x1 + (x2 - x1) * min(1.0, t_dev + dt)
                    prev_sy = y1 + (y2 - y1) * min(1.0, t_dev + dt)
            # Draw the remaining segment.
            self.canvas.create_line(prev_sx, prev_sy, x2, y2, width=LINE_WIDTH, fill=colour)

        if conn.kind == "feeder":
            self._draw_load_triangle(x2, y2, colour)

        # Label — offset if user has dragged it; erase wire underneath when offset
        lbl_sx = (x1 + x2) / 2 + conn.label_ox * self._scale
        lbl_sy = (y1 + y2) / 2 + conn.label_oy * self._scale
        if conn.label_ox != 0.0 or conn.label_oy != 0.0:
            # Blank out the wire under the label so text is readable
            line_len = math.hypot(x2 - x1, y2 - y1) or 1
            lx_rel = lbl_sx - x1
            ly_rel = lbl_sy - y1
            ldx, ldy = (x2 - x1) / line_len, (y2 - y1) / line_len
            t_lbl = (lx_rel * ldx + ly_rel * ldy) / line_len
            half_gap = 38 / line_len
            t0 = max(0.0, t_lbl - half_gap)
            t1 = min(1.0, t_lbl + half_gap)
            if 0.0 < t0:
                self.canvas.create_line(x1, y1, x1 + (x2-x1)*t0, y1 + (y2-y1)*t0,
                                        width=LINE_WIDTH, fill=colour)
            if t1 < 1.0:
                self.canvas.create_line(x1 + (x2-x1)*t1, y1 + (y2-y1)*t1, x2, y2,
                                        width=LINE_WIDTH, fill=colour)
        self.canvas.create_text(lbl_sx + 4, lbl_sy, text=conn.name,
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    def _draw_legacy_breaker_square(self, bx: float, by: float, colour: str) -> None:
        """Original filled-square breaker symbol (for has_breaker_from)."""
        h = 5 * self._scale
        self.canvas.create_rectangle(bx - h, by - h, bx + h, by + h,
                                     fill=colour, outline=colour)

    def _draw_breaker_symbol(self, prev_sx, prev_sy, x1, y1, x2, y2,
                             t: float, colour: str, br, gap: float) -> None:
        """IEC-style circuit breaker: open or filled square, gap in line when open."""
        cx = x1 + (x2 - x1) * t
        cy = y1 + (y2 - y1) * t
        s  = 8 * self._scale
        # Draw segment up to the gap start.
        length = math.hypot(x2 - x1, y2 - y1) or 1
        dt = gap / length
        gap_start_x = x1 + (x2 - x1) * max(0.0, t - dt / 2)
        gap_start_y = y1 + (y2 - y1) * max(0.0, t - dt / 2)
        self.canvas.create_line(prev_sx, prev_sy, gap_start_x, gap_start_y,
                                width=LINE_WIDTH, fill=colour)
        # Direction perpendicular to the line.
        lx, ly = (x2 - x1) / length, (y2 - y1) / length
        px, py = -ly, lx
        # Box corners (perpendicular sides ±s from midpoint).
        corners = [
            (cx - lx * s + px * s, cy - ly * s + py * s),
            (cx + lx * s + px * s, cy + ly * s + py * s),
            (cx + lx * s - px * s, cy + ly * s - py * s),
            (cx - lx * s - px * s, cy - ly * s - py * s),
        ]
        flat = [v for pt in corners for v in pt]
        if br.closed:
            self.canvas.create_polygon(*flat, fill=colour, outline=colour)
        else:
            self.canvas.create_polygon(*flat, fill="white", outline=colour, width=LINE_WIDTH)
        # Label.
        lbl_x = cx + px * (s + 4)
        lbl_y = cy + py * (s + 4)
        self.canvas.create_text(lbl_x, lbl_y, text=br.name,
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    def _draw_disconnect_symbol(self, prev_sx, prev_sy, x1, y1, x2, y2,
                                t: float, colour: str, dc, gap: float) -> None:
        """IEC isolator (disconnect switch): diagonal blade."""
        cx = x1 + (x2 - x1) * t
        cy = y1 + (y2 - y1) * t
        blade_len = 10 * self._scale
        length = math.hypot(x2 - x1, y2 - y1) or 1
        dt = gap / length
        gap_start_x = x1 + (x2 - x1) * max(0.0, t - dt / 2)
        gap_start_y = y1 + (y2 - y1) * max(0.0, t - dt / 2)
        self.canvas.create_line(prev_sx, prev_sy, gap_start_x, gap_start_y,
                                width=LINE_WIDTH, fill=colour)
        lx, ly = (x2 - x1) / length, (y2 - y1) / length
        px, py = -ly, lx
        if dc.closed:
            # Blade at 45°: from one side of gap to other, offset in perpendicular direction.
            bx1 = cx - lx * blade_len / 2
            by1 = cy - ly * blade_len / 2
            bx2 = cx + lx * blade_len / 2 + px * blade_len / 2
            by2 = cy + ly * blade_len / 2 + py * blade_len / 2
        else:
            # Blade at ~90° from conductor (open): perpendicular stub.
            bx1 = cx
            by1 = cy
            bx2 = cx + px * blade_len
            by2 = cy + py * blade_len
        self.canvas.create_line(bx1, by1, bx2, by2,
                                width=LINE_WIDTH + 1, fill=colour, capstyle=tk.ROUND)
        # Hinge dot.
        r = 3 * self._scale
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                fill=colour, outline=colour)
        # Label.
        lbl_x = cx + px * (blade_len + 4)
        lbl_y = cy + py * (blade_len + 4)
        self.canvas.create_text(lbl_x, lbl_y, text=dc.name,
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

    # ── Transformer (standalone, world-space IEC coupled-coil symbol) ─────

    def _xr(self, xfmr, wx: float, wy: float) -> tuple:
        """Rotate world point (wx,wy) CCW around xfmr centre by xfmr.rotation degrees."""
        dx, dy = wx - xfmr.cx, wy - xfmr.cy
        r = xfmr.rotation % 360
        if r == 90:  return xfmr.cx - dy, xfmr.cy + dx
        if r == 180: return xfmr.cx - dx, xfmr.cy - dy
        if r == 270: return xfmr.cx + dy, xfmr.cy - dx
        return wx, wy

    def _draw_elbow_lead(self, ax, ay, bx, by, vert_exit: bool, colour: str) -> None:
        """Draw a Z-shaped 90° lead from (ax,ay) to (bx,by) with the bend at midpoint.
        vert_exit=True  → exit vertically, bend halfway along Y, then go horizontal
        vert_exit=False → exit horizontally, bend halfway along X, then go vertical
        Collapses to a straight line when already aligned.
        """
        if vert_exit:
            my = (ay + by) / 2
            mx1, my1 = ax, my
            mx2, my2 = bx, my
        else:
            mx = (ax + bx) / 2
            mx1, my1 = mx, ay
            mx2, my2 = mx, by
        raw = [(ax, ay), (mx1, my1), (mx2, my2), (bx, by)]
        pts = [self._w2s(wx, wy) for wx, wy in raw]
        # Remove consecutive near-duplicates (collapsed segments)
        uniq = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - uniq[-1][0]) > 0.5 or abs(p[1] - uniq[-1][1]) > 0.5:
                uniq.append(p)
        if len(uniq) >= 2:
            self.canvas.create_line(*[v for pt in uniq for v in pt],
                                    fill=colour, width=LINE_WIDTH)

    def _draw_transformer(self, xfmr: DiagramTransformer) -> None:
        sel      = self._selection == ("transformer", xfmr.id)
        hv_col   = self._voltage_colour(xfmr.hv_kv, selected=sel)
        lv_col   = self._voltage_colour(xfmr.lv_kv, selected=sel)
        core_col = "#0066CC" if sel else self._UNSET_COLOUR
        n    = XFMR_NB
        r    = XFMR_BR
        half = _WIND_SPAN / 2
        rot  = xfmr.rotation % 360
        # vert_exit: True when terminal exits vertically (rotation 0 or 180)
        vert_exit = (rot % 180 == 0)

        # Local y offsets of the two coil spine rows (at rotation=0)
        hv_y_loc = -XFMR_CORE / 2
        lv_y_loc = +XFMR_CORE / 2

        # Coil spine world positions after rotation
        hv_spine = self._xr(xfmr, xfmr.cx, xfmr.cy + hv_y_loc)
        lv_spine = self._xr(xfmr, xfmr.cx, xfmr.cy + lv_y_loc)

        # Terminal world positions (rotation-aware)
        hv_term = xfmr.hv_terminal
        lv_term = xfmr.lv_terminal

        # ── HV lead: bus tap → coil spine (L-shaped) ─────────────────────
        if xfmr.hv_bus and xfmr.hv_bus in self._buses:
            bus = self._buses[xfmr.hv_bus]
            tap = bus.nearest_tap(xfmr.hv_tap_x, xfmr.hv_tap_y)
            self._draw_elbow_lead(tap[0], tap[1], hv_spine[0], hv_spine[1], vert_exit, hv_col)
        else:
            t_sx, t_sy = self._w2s(*hv_term)
            ct_sx, ct_sy = self._w2s(*hv_spine)
            self.canvas.create_line(t_sx, t_sy, ct_sx, ct_sy, fill=hv_col, width=LINE_WIDTH)
            self._terminal_dot(t_sx, t_sy, hv_col)

        # ── LV lead: coil spine → bus tap (L-shaped) ─────────────────────
        if xfmr.lv_bus and xfmr.lv_bus in self._buses:
            bus = self._buses[xfmr.lv_bus]
            tap = bus.nearest_tap(xfmr.lv_tap_x, xfmr.lv_tap_y)
            self._draw_elbow_lead(lv_spine[0], lv_spine[1], tap[0], tap[1], vert_exit, lv_col)
        else:
            cb_sx, cb_sy = self._w2s(*lv_spine)
            b_sx,  b_sy  = self._w2s(*lv_term)
            self.canvas.create_line(cb_sx, cb_sy, b_sx, b_sy, fill=lv_col, width=LINE_WIDTH)
            self._terminal_dot(b_sx, b_sy, lv_col)

        # ── Coil bumps (rotated) ──────────────────────────────────────────
        for i in range(n):
            bx_loc = -half + r + i * 2 * r
            hv_pts, lv_pts = [], []
            for j in range(19):
                t_ang = -math.pi / 2 + math.pi * j / 18
                lx = bx_loc + r * math.sin(t_ang)
                cos_t = r * math.cos(t_ang)
                # HV: bumps downward (toward core) → sign +1
                wx, wy = self._xr(xfmr, xfmr.cx + lx, xfmr.cy + hv_y_loc + cos_t)
                hv_pts.extend(self._w2s(wx, wy))
                # LV: bumps upward (toward core) → sign -1
                wx, wy = self._xr(xfmr, xfmr.cx + lx, xfmr.cy + lv_y_loc - cos_t)
                lv_pts.extend(self._w2s(wx, wy))
            if len(hv_pts) >= 4:
                self.canvas.create_line(*hv_pts, fill=hv_col, width=LINE_WIDTH, smooth=True)
                self.canvas.create_line(*lv_pts, fill=lv_col, width=LINE_WIDTH, smooth=True)

        # ── Iron core (two lines, rotated) ────────────────────────────────
        for off in (-2.5, 2.5):
            ic_l = self._xr(xfmr, xfmr.cx - half, xfmr.cy + off)
            ic_r = self._xr(xfmr, xfmr.cx + half, xfmr.cy + off)
            self.canvas.create_line(*self._w2s(*ic_l), *self._w2s(*ic_r),
                                    fill=core_col, width=LINE_WIDTH + 1)

        # ── Winding indicators (rotated) ──────────────────────────────────
        ind_loc_x = half + XFMR_IND + 16
        hv_ind = self._xr(xfmr, xfmr.cx + ind_loc_x, xfmr.cy + hv_y_loc)
        lv_ind = self._xr(xfmr, xfmr.cx + ind_loc_x, xfmr.cy + lv_y_loc)
        self._draw_winding_indicator(hv_ind[0], hv_ind[1],
                                     xfmr.hv_winding, xfmr.hv_grounded, hv_col)
        self._draw_winding_indicator(lv_ind[0], lv_ind[1],
                                     xfmr.lv_winding, xfmr.lv_grounded, lv_col)

        # ── kV labels (rotated) ───────────────────────────────────────────
        kv_loc_x = -half - 6
        if xfmr.hv_kv:
            kv_hv = self._xr(xfmr, xfmr.cx + kv_loc_x, xfmr.cy + hv_y_loc)
            kv_sx, kv_sy = self._w2s(*kv_hv)
            self.canvas.create_text(kv_sx, kv_sy, text=f"{xfmr.hv_kv:g} kV",
                                    font=("TkDefaultFont", 8, "bold"), fill=hv_col, anchor="e")
        if xfmr.lv_kv:
            kv_lv = self._xr(xfmr, xfmr.cx + kv_loc_x, xfmr.cy + lv_y_loc)
            kv_sx, kv_sy = self._w2s(*kv_lv)
            self.canvas.create_text(kv_sx, kv_sy, text=f"{xfmr.lv_kv:g} kV",
                                    font=("TkDefaultFont", 8, "bold"), fill=lv_col, anchor="e")

        # ── Name label ────────────────────────────────────────────────────
        label = xfmr.name
        if xfmr.mva:
            label += f"\n{xfmr.mva:g} MVA"
        l_sx, l_sy = self._w2s(xfmr.cx + kv_loc_x + xfmr.label_ox,
                               xfmr.cy + xfmr.label_oy)
        self.canvas.create_text(l_sx, l_sy, text=label, justify="right",
                                font=("TkDefaultFont", 8), fill="#444444", anchor="e")

    def _terminal_dot(self, sx: float, sy: float, colour: str) -> None:
        rd = max(3, 3 * self._scale)
        self.canvas.create_oval(sx - rd, sy - rd, sx + rd, sy + rd,
                                fill=colour, outline=colour)

    def _draw_coil(self, cx_w: float, y_top_w: float, n: int, r: float,
                   bulge_left: bool, colour: str) -> None:
        """Draw a vertical coil of n half-loop bumps starting at y_top_w."""
        N = 18
        sign = -1.0 if bulge_left else 1.0
        for i in range(n):
            by = y_top_w + r + i * 2 * r
            pts = []
            for j in range(N + 1):
                t  = -math.pi / 2 + math.pi * j / N
                wx = cx_w + sign * r * math.cos(t)
                wy = by + r * math.sin(t)
                sx, sy = self._w2s(wx, wy)
                pts.extend([sx, sy])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

    def _draw_winding_indicator(self, ax_w: float, ay_w: float,
                                wtype: str, grounded: bool, colour: str) -> None:
        """Draw IEC winding-connection indicator (wye / delta / zigzag) at world point."""
        s = XFMR_IND

        if wtype == "wye":
            # Y / star: one arm up, two arms down-left and down-right.
            cx_s, cy_s = self._w2s(ax_w, ay_w)
            for ang in (-math.pi / 2, math.pi / 6, 5 * math.pi / 6):
                ex, ey = self._w2s(ax_w + s * math.cos(ang), ay_w + s * math.sin(ang))
                self.canvas.create_line(cx_s, cy_s, ex, ey, fill=colour, width=LINE_WIDTH)
            if grounded:
                self._draw_ground_stub(ax_w, ay_w, colour)

        elif wtype == "delta":
            # Equilateral triangle, point up.
            pts_w = [(ax_w, ay_w - s * 0.75),
                     (ax_w - s * 0.7, ay_w + s * 0.55),
                     (ax_w + s * 0.7, ay_w + s * 0.55)]
            pts_s = []
            for wx, wy in pts_w:
                px, py = self._w2s(wx, wy)
                pts_s.extend([px, py])
            self.canvas.create_polygon(*pts_s, outline=colour, fill="", width=LINE_WIDTH)

        elif wtype == "zigzag":
            # Vertical zigzag (interconnected-star) glyph.
            steps = [(0.0, -1.0), (0.55, -0.5), (-0.55, 0.0), (0.55, 0.5), (0.0, 1.0)]
            pts_s = []
            for fx, fy in steps:
                px, py = self._w2s(ax_w + fx * s, ay_w + fy * s)
                pts_s.extend([px, py])
            self.canvas.create_line(*pts_s, fill=colour, width=LINE_WIDTH)
            if grounded:
                self._draw_ground_stub(ax_w, ay_w, colour)

    def _draw_ground_stub(self, ax_w: float, ay_w: float, colour: str) -> None:
        """Small IEC earth symbol on a short stub to the left of (ax_w, ay_w)."""
        stub = XFMR_IND * 0.9
        x0_sx, x0_sy = self._w2s(ax_w, ay_w)
        end_sx, end_sy = self._w2s(ax_w - stub, ay_w)
        self.canvas.create_line(x0_sx, x0_sy, end_sx, end_sy, fill=colour, width=LINE_WIDTH)
        for k, half in enumerate((5.0, 3.0, 1.5)):
            bx_w = ax_w - stub - k * 2.0
            t_sx, t_sy = self._w2s(bx_w, ay_w - half)
            b_sx, b_sy = self._w2s(bx_w, ay_w + half)
            self.canvas.create_line(t_sx, t_sy, b_sx, b_sy, fill=colour, width=LINE_WIDTH)

    # ── Source (AC source / grid / generator) ─────────────────────────────

    def _draw_source(self, src: DiagramSource) -> None:
        sel    = self._selection == ("source", src.id)
        colour = "#0066CC" if sel else "black"
        rs = SRC_R * self._scale
        csx, csy = self._w2s(src.cx, src.cy)

        # Lead from bottom of circle to bus (or free terminal).
        bot_sx, bot_sy = self._w2s(src.cx, src.cy + SRC_R)
        if src.bus and src.bus in self._buses:
            bus = self._buses[src.bus]
            tap_pt = bus.nearest_tap(src.tap_x, src.tap_y)
            tsx, tsy = self._w2s(*tap_pt)
            self.canvas.create_line(bot_sx, bot_sy, tsx, tsy, fill=colour, width=LINE_WIDTH)
        else:
            self._terminal_dot(bot_sx, bot_sy, colour)

        self.canvas.create_oval(csx - rs, csy - rs, csx + rs, csy + rs,
                                outline=colour, fill="white", width=LINE_WIDTH)

        # Sine wave inside the circle.
        half = SRC_R * 0.6
        amp  = SRC_R * 0.38
        pts = []
        N = 26
        for k in range(N + 1):
            frac = k / N
            wx = src.cx - half + 2 * half * frac
            wy = src.cy - amp * math.sin(2 * math.pi * frac)
            sx, sy = self._w2s(wx, wy)
            pts.extend([sx, sy])
        self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        lsx, lsy = self._w2s(src.cx + SRC_R + 6 + src.label_ox, src.cy + src.label_oy)
        label = f"{src.name}\n{src.v_pu:g} pu"
        self.canvas.create_text(lsx, lsy, text=label, justify="left",
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    # ── Load (downward filled arrow) ──────────────────────────────────────

    def _draw_load(self, ld: DiagramLoad) -> None:
        sel    = self._selection == ("load", ld.id)
        colour = "#0066CC" if sel else "black"

        base_w = ld.cy - LOAD_AH                 # arrowhead base
        tip_sx, tip_sy   = self._w2s(ld.cx, ld.cy)
        base_sx, base_sy = self._w2s(ld.cx, base_w)

        # Lead from bus (or free terminal) down to the arrowhead base.
        if ld.bus and ld.bus in self._buses:
            bus = self._buses[ld.bus]
            tap_pt = bus.nearest_tap(ld.tap_x, ld.tap_y)
            tsx, tsy = self._w2s(*tap_pt)
            self.canvas.create_line(tsx, tsy, base_sx, base_sy, fill=colour, width=LINE_WIDTH)
        else:
            top_sx, top_sy = self._w2s(ld.cx, base_w - LOAD_LEAD)
            self.canvas.create_line(top_sx, top_sy, base_sx, base_sy, fill=colour, width=LINE_WIDTH)
            self._terminal_dot(top_sx, top_sy, colour)

        aw = LOAD_AW * self._scale
        self.canvas.create_polygon(tip_sx, tip_sy,
                                   base_sx - aw, base_sy,
                                   base_sx + aw, base_sy,
                                   fill=colour, outline=colour)

        lsx, lsy = self._w2s(ld.cx + LOAD_AW + 6 + ld.label_ox, ld.cy - LOAD_AH / 2 + ld.label_oy)
        self.canvas.create_text(lsx, lsy, text=f"{ld.name}\n{ld.summary_str()}",
                                justify="left",
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    # ── CT ────────────────────────────────────────────────────────────────

    def _ct_lead_segs(self, ct: "DiagramCT"):
        """Return list of (ax,ay,bx,by) world segments for the wire the CT is on."""
        if ct.xfmr_id:
            xfmr = self._transformers.get(ct.xfmr_id)
            if xfmr is None:
                return []
            return [(ax,ay,bx,by)
                    for (lead,ax,ay,bx,by) in self._xfmr_lead_segments(xfmr)
                    if lead == ct.xfmr_lead]
        else:
            conn = self._connections.get(ct.connection_id)
            if conn is None:
                return []
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                return []
            return [(start[0], start[1], end[0], end[1])]

    def _ct_wire_endpoints(self, ct: "DiagramCT"):
        """Return (wx1,wy1, wx2,wy2, wx,wy) — segment endpoints + position at ct.t."""
        segs = self._ct_lead_segs(ct)
        if not segs:
            return None
        lengths = [math.hypot(bx-ax, by-ay) for ax,ay,bx,by in segs]
        total   = sum(lengths) or 1.0
        target  = ct.t * total
        acc = 0.0
        for (ax,ay,bx,by), seg_len in zip(segs, lengths):
            if acc + seg_len >= target or seg_len < 1e-6:
                local_t = (target - acc) / max(seg_len, 1e-6)
                wx = ax + (bx - ax) * local_t
                wy = ay + (by - ay) * local_t
                return ax, ay, bx, by, wx, wy
            acc += seg_len
        ax,ay,bx,by = segs[-1]
        return ax, ay, bx, by, bx, by

    def _ct_project_t(self, ct: "DiagramCT", wx: float, wy: float) -> float:
        """Project world point (wx,wy) onto the CT's full wire polyline, return t."""
        segs = self._ct_lead_segs(ct)
        if not segs:
            return ct.t
        lengths  = [math.hypot(bx-ax, by-ay) for ax,ay,bx,by in segs]
        total    = sum(lengths) or 1.0
        best_dist = float("inf")
        best_t    = ct.t
        acc = 0.0
        for (ax,ay,bx,by), seg_len in zip(segs, lengths):
            if seg_len < 1e-9:
                acc += seg_len; continue
            sdx, sdy = bx-ax, by-ay
            loc_t = max(0.0, min(1.0, ((wx-ax)*sdx + (wy-ay)*sdy) / (seg_len**2)))
            px = ax + loc_t*sdx; py = ay + loc_t*sdy
            d  = math.hypot(wx-px, wy-py)
            if d < best_dist:
                best_dist = d
                best_t    = (acc + loc_t * seg_len) / total
            acc += seg_len
        return best_t

    def _draw_ct(self, ct: DiagramCT) -> None:
        pts = self._ct_wire_endpoints(ct)
        if pts is None:
            return
        wx1, wy1, wx2, wy2, wx, wy = pts
        sx, sy = self._w2s(wx, wy)

        sel    = self._selection == ("ct", ct.id)
        colour = "#0066CC" if sel else "black"

        # Wire direction unit vector and perpendicular (screen space)
        dx, dy = wx2 - wx1, wy2 - wy1
        length = math.hypot(dx, dy) or 1
        s1 = self._w2s(wx1, wy1)
        s2 = self._w2s(wx1 + dx/length, wy1 + dy/length)
        raw = (s2[0]-s1[0], s2[1]-s1[1])
        aln = math.hypot(*raw) or 1
        alx, aly = raw[0]/aln, raw[1]/aln   # along-wire unit (screen)
        pxn, pyn = -aly, alx                 # perpendicular (90° CCW) = "left" of downward wire

        R  = 10 * self._scale   # arc radius
        tk =  7 * self._scale   # secondary tick length
        lw = LINE_WIDTH

        # Two C-arcs side-by-side (touching, no gap): both open in +pxn direction.
        # Centres at ±R along the wire so the arcs share their inner diameter edge.
        # Flat diameter of each C is perpendicular to wire.
        # Wire is redrawn through each centre so it threads through both openings.
        #
        #  Layout for vertical wire (wire goes down, pxn points left):
        #
        #        |          ← wire above symbol
        #   ─(   |          ← upper C, flat side on wire
        #   ─(   |          ← lower C, flat side on wire
        #        |          ← wire below symbol

        wire_angle_deg = math.degrees(math.atan2(-aly, alx))
        # Flat diameter along wire, arc bulge opens perpendicular (+pxn).
        # arc_start = wire_angle_deg gives exactly this orientation.
        arc_start = wire_angle_deg

        for sign in (-1, +1):             # sign=-1 → upper arc, +1 → lower arc
            cx = sx + alx * sign * R
            cy = sy + aly * sign * R
            self.canvas.create_arc(cx-R, cy-R, cx+R, cy+R,
                                   start=arc_start, extent=180,
                                   outline=colour, style="arc", width=lw)
            # Redraw wire through the flat opening of this C
            self.canvas.create_line(cx - alx*R, cy - aly*R,
                                    cx + alx*R, cy + aly*R,
                                    fill=colour, width=lw)

        # Polarity dot near tip of upper arc (+pxn side)
        if ct.polarity_standard:
            pr = max(2, 2.5 * self._scale)
            uc_x = sx - alx*R + pxn*R*0.85
            uc_y = sy - aly*R + pyn*R*0.85
            self.canvas.create_oval(uc_x-pr, uc_y-pr, uc_x+pr, uc_y+pr,
                                    fill=colour, outline=colour)

        # Terminal ticks at ends of each flat diameter (along wire):
        # outer top, shared centre, outer bottom
        top_x = sx - alx*2*R;  top_y = sy - aly*2*R
        bot_x = sx + alx*2*R;  bot_y = sy + aly*2*R

        for px, py in [(top_x, top_y), (sx, sy), (bot_x, bot_y)]:
            self.canvas.create_line(px, py,
                                    px + pxn*tk*0.6, py + pyn*tk*0.6,
                                    fill=colour, width=lw)

        # Secondary lead from arc tips out in +pxn direction, with crossbar
        # Both arc tips are at cx+pxn*R for each arc; connect them and lead out
        tip_top_x = sx - alx*R + pxn*R;  tip_top_y = sy - aly*R + pyn*R
        tip_bot_x = sx + alx*R + pxn*R;  tip_bot_y = sy + aly*R + pyn*R
        # Vertical connecting line between the two tips
        self.canvas.create_line(tip_top_x, tip_top_y, tip_bot_x, tip_bot_y,
                                fill=colour, width=lw)
        # Lead from midpoint of that line outward
        mid_x = (tip_top_x + tip_bot_x) / 2
        mid_y = (tip_top_y + tip_bot_y) / 2
        lead_ex = mid_x + pxn * tk * 2
        lead_ey = mid_y + pyn * tk * 2
        self.canvas.create_line(mid_x, mid_y, lead_ex, lead_ey,
                                fill=colour, width=lw)
        self.canvas.create_line(lead_ex - alx*tk/2, lead_ey - aly*tk/2,
                                lead_ex + alx*tk/2, lead_ey + aly*tk/2,
                                fill=colour, width=lw)

        label = f"{ct.ratio_str}\n{ct.name}"
        self.canvas.create_text(lead_ex + pxn*4 + ct.label_ox*self._scale,
                                lead_ey + pyn*4 + ct.label_oy*self._scale,
                                text=label, font=("TkDefaultFont", 8),
                                fill="#444444",
                                anchor="w" if pxn >= 0 else "e")
        end_x = tip_x + pxn * tk_len * 2
        end_y = tip_y + pyn * tk_len * 2
        self.canvas.create_line(tip_x, tip_y, end_x, end_y, fill=colour, width=lw)
        self.canvas.create_line(end_x - alx*tk_len/2, end_y - aly*tk_len/2,
                                end_x + alx*tk_len/2, end_y + aly*tk_len/2,
                                fill=colour, width=lw)

        # Label: ratio + name
        label = f"{ct.ratio_str}\n{ct.name}"
        lbl_anchor = "w" if pxn >= 0 else "e"
        self.canvas.create_text(end_x + pxn*4 + ct.label_ox*self._scale,
                                end_y + pyn*4 + ct.label_oy*self._scale,
                                text=label, font=("TkDefaultFont", 8),
                                fill="#444444", anchor=lbl_anchor)

    # ── VT ────────────────────────────────────────────────────────────────

    def _draw_vt(self, vt: DiagramVT) -> None:
        bus = self._buses.get(vt.bus_id)
        if bus is None:
            return
        tap_pt = bus.nearest_tap(vt.tap_x, vt.tap_y)
        sx, sy = self._w2s(*tap_pt)

        sel    = self._selection == ("vt", vt.id)
        colour = "#0066CC" if sel else "black"

        r    = 6 * self._scale
        drop = 12 * self._scale

        self.canvas.create_line(sx, sy, sx, sy + drop, fill=colour, width=LINE_WIDTH)

        winding_top = sy + drop
        n = 3
        N = 16
        for i in range(n):
            by = winding_top + r + i * 2 * r
            pts = []
            for j in range(N + 1):
                t = -math.pi / 2 + math.pi * j / N
                pts.extend([sx + r * math.cos(t), by + r * math.sin(t)])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        winding_bot = winding_top + n * 2 * r
        r2 = r * 0.75
        sec_top = winding_bot + r * 0.5
        for i in range(n):
            by = sec_top + r2 + i * 2 * r2
            pts = []
            for j in range(N + 1):
                t = -math.pi / 2 + math.pi * j / N
                pts.extend([sx - r2 * math.cos(t), by + r2 * math.sin(t)])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        sec_bot = sec_top + n * 2 * r2
        gy = sec_bot + 4 * self._scale
        self.canvas.create_line(sx, sec_bot, sx, gy, fill=colour, width=LINE_WIDTH)
        for k, w in enumerate([10, 6, 3]):
            ws = w * self._scale
            yy = gy + k * 4 * self._scale
            self.canvas.create_line(sx - ws, yy, sx + ws, yy, fill=colour, width=LINE_WIDTH)

        self.canvas.create_text(sx + 14 * self._scale,
                                winding_top + (winding_bot - winding_top) / 2,
                                text=vt.name, font=("TkDefaultFont", 8),
                                fill="#444444", anchor="w")

    # ── Helper: nearest connection ────────────────────────────────────────

    def _nearest_connection(self, sx: float, sy: float, max_px: float = 20.0):
        """Return (conn_id, t) for the connection whose line is closest to screen point (sx,sy), or None."""
        best_dist = max_px
        best = None
        for conn in self._connections.values():
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            dx, dy = x2 - x1, y2 - y1
            length_sq = dx*dx + dy*dy
            if length_sq < 1:
                continue
            t = max(0.0, min(1.0, ((sx-x1)*dx + (sy-y1)*dy) / length_sq))
            px, py = x1 + t*dx, y1 + t*dy
            dist = math.hypot(sx-px, sy-py)
            if dist < best_dist:
                best_dist = dist
                best = (conn.id, t)
        return best

    def _xfmr_lead_segments(self, xfmr: "DiagramTransformer"):
        """Return [(ax,ay,bx,by,label)] for each drawn lead segment of a transformer."""
        rot = xfmr.rotation % 360
        vert_exit = (rot % 180 == 0)
        hv_y_loc = -XFMR_CORE / 2
        lv_y_loc = +XFMR_CORE / 2
        hv_spine = self._xr(xfmr, xfmr.cx, xfmr.cy + hv_y_loc)
        lv_spine = self._xr(xfmr, xfmr.cx, xfmr.cy + lv_y_loc)
        segs = []
        if xfmr.hv_bus and xfmr.hv_bus in self._buses:
            tap = self._buses[xfmr.hv_bus].nearest_tap(xfmr.hv_tap_x, xfmr.hv_tap_y)
            ax, ay, bx, by = tap[0], tap[1], hv_spine[0], hv_spine[1]
            if vert_exit:
                my = (ay + by) / 2
                segs += [("hv", ax, ay, ax, my), ("hv", ax, my, bx, my), ("hv", bx, my, bx, by)]
            else:
                mx = (ax + bx) / 2
                segs += [("hv", ax, ay, mx, ay), ("hv", mx, ay, mx, by), ("hv", mx, by, bx, by)]
        if xfmr.lv_bus and xfmr.lv_bus in self._buses:
            tap = self._buses[xfmr.lv_bus].nearest_tap(xfmr.lv_tap_x, xfmr.lv_tap_y)
            ax, ay, bx, by = lv_spine[0], lv_spine[1], tap[0], tap[1]
            if vert_exit:
                my = (ay + by) / 2
                segs += [("lv", ax, ay, ax, my), ("lv", ax, my, bx, my), ("lv", bx, my, bx, by)]
            else:
                mx = (ax + bx) / 2
                segs += [("lv", ax, ay, mx, ay), ("lv", mx, ay, mx, by), ("lv", mx, by, bx, by)]
        return segs

    def _nearest_wire(self, sx: float, sy: float, max_px: float = 20.0):
        """Return (kind, id, t) for the closest wire to screen point, or None.
        kind="conn" → DiagramConnection; kind="xfmr_hv"/"xfmr_lv" → transformer lead."""
        best_dist = max_px
        best = None
        # Check DiagramConnections
        for conn in self._connections.values():
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            dx, dy = x2 - x1, y2 - y1
            lsq = dx*dx + dy*dy
            if lsq < 1:
                continue
            t = max(0.0, min(1.0, ((sx-x1)*dx + (sy-y1)*dy) / lsq))
            dist = math.hypot(sx - (x1+t*dx), sy - (y1+t*dy))
            if dist < best_dist:
                best_dist = dist
                best = ("conn", conn.id, t)
        # Check transformer leads
        for xfmr in self._transformers.values():
            for (lead, ax, ay, bx, by) in self._xfmr_lead_segments(xfmr):
                x1, y1 = self._w2s(ax, ay)
                x2, y2 = self._w2s(bx, by)
                dx, dy = x2 - x1, y2 - y1
                lsq = dx*dx + dy*dy
                if lsq < 1:
                    continue
                t = max(0.0, min(1.0, ((sx-x1)*dx + (sy-y1)*dy) / lsq))
                dist = math.hypot(sx - (x1+t*dx), sy - (y1+t*dy))
                if dist < best_dist:
                    best_dist = dist
                    best = (f"xfmr_{lead}", xfmr.id, t)
        return best

    # ── Hit testing ───────────────────────────────────────────────────────

    def _hit_bus(self, wx: float, wy: float) -> Optional[str]:
        for bus in self._buses.values():
            if bus.hit(wx, wy, tol=SNAP_TOL / self._scale):
                return bus.id
        return None

    def _snap_bus(self, wx: float, wy: float) -> Optional[str]:
        """Snap for transformer/source/load placement: cursor must be near a bus segment."""
        tol = XFMR_SNAP / self._scale
        for bus in self._buses.values():
            if bus.hit(wx, wy, tol=tol):
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
            if _point_to_segment_dist(sx, sy, x1, y1, x2, y2) < 16:
                return conn.id
        return None

    def _hit_transformer(self, wx: float, wy: float) -> Optional[str]:
        for xfmr in self._transformers.values():
            if math.hypot(wx - xfmr.cx, wy - xfmr.cy) < XFMR_HALF + 4:
                return xfmr.id
        return None

    def _hit_source(self, wx: float, wy: float) -> Optional[str]:
        for src in self._sources.values():
            if math.hypot(wx - src.cx, wy - src.cy) < SRC_R + 4:
                return src.id
        return None

    def _hit_load(self, wx: float, wy: float) -> Optional[str]:
        for ld in self._loads.values():
            top = ld.cy - LOAD_AH - LOAD_LEAD - 4
            if abs(wx - ld.cx) < LOAD_AW + 6 and top <= wy <= ld.cy + 4:
                return ld.id
        return None

    def _hit_ct(self, sx: float, sy: float) -> Optional[str]:
        for ct in self._cts.values():
            pts = self._ct_wire_endpoints(ct)
            if pts is None:
                continue
            _, _, _, _, wx, wy = pts
            csx, csy = self._w2s(wx, wy)
            if math.hypot(sx - csx, sy - csy) < 12 * self._scale:
                return ct.id
        return None

    def _hit_vt(self, wx: float, wy: float) -> Optional[str]:
        tol = SNAP_TOL / self._scale
        for vt in self._vts.values():
            bus = self._buses.get(vt.bus_id)
            if bus is None:
                continue
            tap_pt = bus.nearest_tap(vt.tap_x, vt.tap_y)
            if math.hypot(tap_pt[0] - wx, tap_pt[1] - wy) < tol * 2:
                return vt.id
        return None

    def _hit_breaker(self, sx: float, sy: float) -> Optional[str]:
        """Return the id of the breaker closest to screen point within 10px."""
        for br in self._breakers.values():
            conn = self._connections.get(br.connection_id)
            if conn is None:
                continue
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            cx = x1 + (x2 - x1) * br.t
            cy = y1 + (y2 - y1) * br.t
            if math.hypot(sx - cx, sy - cy) < 10:
                return br.id
        return None

    def _hit_disconnect(self, sx: float, sy: float) -> Optional[str]:
        """Return the id of the disconnect closest to screen point within 10px."""
        for dc in self._disconnects.values():
            conn = self._connections.get(dc.connection_id)
            if conn is None:
                continue
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            cx = x1 + (x2 - x1) * dc.t
            cy = y1 + (y2 - y1) * dc.t
            if math.hypot(sx - cx, sy - cy) < 10:
                return dc.id
        return None

    def _hit_label(self, sx: float, sy: float):
        """Return (kind, elem_id) if screen point is near a rendered label."""
        TX, TY = 54, 12   # hit-box half-extents in screen pixels

        for bus in self._buses.values():
            lx, ly = self._w2s(bus.cx + bus.label_ox, bus.cy_label + bus.label_oy - 12 / self._scale)
            if abs(sx - lx) < TX and abs(sy - ly) < TY:
                return ("bus", bus.id)

        for xfmr in self._transformers.values():
            base_x = xfmr.cx - _WIND_SPAN / 2 - 6
            lx, ly = self._w2s(base_x + xfmr.label_ox, xfmr.cy + xfmr.label_oy)
            if abs(sx - lx) < TX and abs(sy - ly) < TY:
                return ("transformer", xfmr.id)

        for src in self._sources.values():
            lx, ly = self._w2s(src.cx + SRC_R + 6 + src.label_ox, src.cy + src.label_oy)
            if abs(sx - lx) < TX and abs(sy - ly) < TY:
                return ("source", src.id)

        for ld in self._loads.values():
            lx, ly = self._w2s(ld.cx + LOAD_AW + 6 + ld.label_ox,
                               ld.cy - LOAD_AH / 2 + ld.label_oy)
            if abs(sx - lx) < TX and abs(sy - ly) < TY:
                return ("load", ld.id)

        for conn in self._connections.values():
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start and end:
                mwx = (start[0] + end[0]) / 2
                mwy = (start[1] + end[1]) / 2
                lx = (self._w2s(mwx, mwy)[0]) + conn.label_ox * self._scale
                ly = (self._w2s(mwx, mwy)[1]) + conn.label_oy * self._scale
                if abs(sx - lx) < TX and abs(sy - ly) < TY:
                    return ("conn", conn.id)

        return None

    def _hit_terminal(self, sx: float, sy: float, wx: float, wy: float):
        """Return (kind, elem_id, anchor_sx, anchor_sy) if click is near a terminal dot/lead-tip."""
        tol = max(10, 10 * self._scale)

        for xfmr in self._transformers.values():
            hv_spine = self._xr(xfmr, xfmr.cx, xfmr.cy - XFMR_CORE / 2)
            lv_spine = self._xr(xfmr, xfmr.cx, xfmr.cy + XFMR_CORE / 2)
            coil_hv_sx, coil_hv_sy = self._w2s(*hv_spine)
            coil_lv_sx, coil_lv_sy = self._w2s(*lv_spine)
            if xfmr.hv_bus and xfmr.hv_bus in self._buses:
                hv_tip = self._buses[xfmr.hv_bus].nearest_tap(xfmr.hv_tap_x, xfmr.hv_tap_y)
                hv_tip_sx, hv_tip_sy = self._w2s(*hv_tip)
            else:
                hv_tip_sx, hv_tip_sy = self._w2s(*xfmr.hv_terminal)
            if xfmr.lv_bus and xfmr.lv_bus in self._buses:
                lv_tip = self._buses[xfmr.lv_bus].nearest_tap(xfmr.lv_tap_x, xfmr.lv_tap_y)
                lv_tip_sx, lv_tip_sy = self._w2s(*lv_tip)
            else:
                lv_tip_sx, lv_tip_sy = self._w2s(*xfmr.lv_terminal)
            if math.hypot(sx - hv_tip_sx, sy - hv_tip_sy) <= tol:
                return ("xfmr_hv", xfmr.id, coil_hv_sx, coil_hv_sy)
            if math.hypot(sx - lv_tip_sx, sy - lv_tip_sy) <= tol:
                return ("xfmr_lv", xfmr.id, coil_lv_sx, coil_lv_sy)

        for src in self._sources.values():
            if src.bus and src.bus in self._buses:
                tip = self._buses[src.bus].nearest_tap(src.tap_x, src.tap_y)
                tip_sx, tip_sy = self._w2s(*tip)
            else:
                tip_sx, tip_sy = self._w2s(src.cx, src.cy + SRC_R)
            anchor_sx, anchor_sy = self._w2s(src.cx, src.cy + SRC_R)
            if math.hypot(sx - tip_sx, sy - tip_sy) <= tol:
                return ("src_term", src.id, anchor_sx, anchor_sy)

        for ld in self._loads.values():
            base_w = ld.cy - LOAD_AH
            if ld.bus and ld.bus in self._buses:
                tip = self._buses[ld.bus].nearest_tap(ld.tap_x, ld.tap_y)
                tip_sx, tip_sy = self._w2s(*tip)
            else:
                tip_sx, tip_sy = self._w2s(ld.cx, base_w - LOAD_LEAD)
            anchor_sx, anchor_sy = self._w2s(ld.cx, base_w)
            if math.hypot(sx - tip_sx, sy - tip_sy) <= tol:
                return ("load_term", ld.id, anchor_sx, anchor_sy)

        return None

    # ── Bus polyline tool helpers ──────────────────────────────────────────

    def _snap_90(self, last: tuple, wx: float, wy: float) -> tuple:
        """Constrain (wx, wy) to be axis-aligned (H or V) from last node."""
        dx, dy = wx - last[0], wy - last[1]
        if abs(dx) >= abs(dy):
            return (wx, last[1])   # horizontal
        else:
            return (last[0], wy)   # vertical

    def _finish_bus(self) -> None:
        pts = self._bus_draw_nodes
        self._bus_draw_nodes = []
        self._preview_point  = None
        if len(pts) < 2:
            self.redraw()
            return
        bid = f"BUS-{len(self._buses) + 1}"
        nodes = list(pts)
        edges = [(i, i+1) for i in range(len(pts)-1)]
        self._buses[bid] = DiagramBus(bid, bid, 0.0, nodes, edges)
        self._selection = ("bus", bid)
        if self._on_select:
            self._on_select(("bus", bid))
        if self._on_status:
            self._on_status("Bus: click to place first node.")
        self.redraw()

    def _bus_insert_node(self, bus: DiagramBus, edge_idx: int) -> None:
        """Split edge at its midpoint, inserting a new node."""
        i, j = bus.edges[edge_idx]
        nx = (bus.nodes[i][0] + bus.nodes[j][0]) / 2
        ny = (bus.nodes[i][1] + bus.nodes[j][1]) / 2
        new_idx = len(bus.nodes)
        bus.nodes.append((nx, ny))
        bus.edges[edge_idx] = (i, new_idx)
        bus.edges.append((new_idx, j))
        self.redraw()

    def _bus_delete_node(self, bus: DiagramBus, ni: int) -> None:
        """Remove a node; reconnect its two neighbours if it was degree-2."""
        neighbours_as_i = [(idx, e) for idx, e in enumerate(bus.edges) if e[0] == ni]
        neighbours_as_j = [(idx, e) for idx, e in enumerate(bus.edges) if e[1] == ni]
        connected_edges = neighbours_as_i + neighbours_as_j
        if len(connected_edges) == 2:
            # Degree-2 node: merge the two edges
            other_nodes = []
            for _, e in connected_edges:
                other_nodes.extend([n for n in e if n != ni])
            # Remove both edges, add one merged edge
            idxs_to_remove = sorted([idx for idx, _ in connected_edges], reverse=True)
            for idx in idxs_to_remove:
                bus.edges.pop(idx)
            if len(other_nodes) == 2:
                bus.edges.append((other_nodes[0], other_nodes[1]))
        elif len(connected_edges) == 1:
            # End node: just remove its edge
            bus.edges.pop(connected_edges[0][0])
        # Remove the node; remap edge indices
        bus.nodes.pop(ni)
        bus.edges = [
            (i if i < ni else i - 1, j if j < ni else j - 1)
            for i, j in bus.edges
        ]
        self.redraw()

    def _on_escape(self, _e=None) -> None:
        if self._bus_draw_nodes:
            self._finish_bus()

    # ── Mouse events ──────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT:
            shift = bool(event.state & 0x0001)

            # ── Bus node editing (only when a bus is already selected) ────
            if self._selection and self._selection[0] == "bus":
                bus = self._buses.get(self._selection[1])
                if bus:
                    node_tol = max(7, 7 * self._scale)
                    # Check for click on an existing node handle
                    for ni, (nx, ny) in enumerate(bus.nodes):
                        sx, sy = self._w2s(nx, ny)
                        if math.hypot(event.x - sx, event.y - sy) <= node_tol:
                            if shift:
                                # Shift-click node: delete it (merge adjacent edges)
                                self._bus_delete_node(bus, ni)
                            else:
                                # Start dragging this node
                                self._drag_id       = bus.id
                                self._drag_kind     = "bus_node"
                                self._drag_node_idx = ni
                                self._drag_origin   = (wx, wy)
                            return
                    # Check for shift-click on a segment mid-diamond → insert node
                    if shift:
                        seg_tol = max(10, 10 * self._scale)
                        for idx, (i, j) in enumerate(bus.edges):
                            mx = (bus.nodes[i][0] + bus.nodes[j][0]) / 2
                            my = (bus.nodes[i][1] + bus.nodes[j][1]) / 2
                            sx, sy = self._w2s(mx, my)
                            if math.hypot(event.x - sx, event.y - sy) <= seg_tol:
                                self._bus_insert_node(bus, idx)
                                return

            # ── Label drag ───────────────────────────────────────────────────
            lbl_hit = self._hit_label(event.x, event.y)
            if lbl_hit:
                lkind, lid = lbl_hit
                self._drag_id     = lid
                self._drag_kind   = f"label_{lkind}"
                self._drag_origin = (wx, wy)
                return

            # ── Terminal drag: grab a free or connected lead tip ─────────────
            term_hit = self._hit_terminal(event.x, event.y, wx, wy)
            if term_hit:
                kind, elem_id, anchor_sx, anchor_sy = term_hit
                self._drag_id     = elem_id
                self._drag_kind   = kind          # "xfmr_hv" | "xfmr_lv" | "src_term" | "load_term"
                self._drag_origin = (wx, wy)
                self._term_anchor = (anchor_sx, anchor_sy)
                if kind == "xfmr_hv":
                    self._set_selection("transformer", elem_id)
                elif kind == "xfmr_lv":
                    self._set_selection("transformer", elem_id)
                elif kind == "src_term":
                    self._set_selection("source", elem_id)
                elif kind == "load_term":
                    self._set_selection("load", elem_id)
                return

            xfmr_id  = self._hit_transformer(wx, wy)
            src_id   = self._hit_source(wx, wy)
            load_id  = self._hit_load(wx, wy)
            ct_id    = self._hit_ct(event.x, event.y)
            vt_id    = self._hit_vt(wx, wy)
            br_id    = self._hit_breaker(event.x, event.y)
            dc_id    = self._hit_disconnect(event.x, event.y)
            bus_id   = self._hit_bus(wx, wy)
            conn_id  = self._hit_connection(event.x, event.y)
            if xfmr_id:
                self._begin_drag("transformer", xfmr_id, wx, wy)
            elif src_id:
                self._begin_drag("source", src_id, wx, wy)
            elif load_id:
                self._begin_drag("load", load_id, wx, wy)
            elif ct_id:
                self._set_selection("ct", ct_id)
                self._begin_drag("ct", ct_id, wx, wy)
            elif vt_id:
                self._set_selection("vt", vt_id)
            elif br_id:
                self._set_selection("breaker", br_id)
            elif dc_id:
                self._set_selection("disconnect", dc_id)
            elif bus_id:
                self._begin_drag("bus", bus_id, wx, wy)
            elif conn_id:
                self._set_selection("conn", conn_id)
            else:
                self._set_selection(None, None)

        elif self._tool == TOOL_BUS:
            if self._bus_draw_nodes:
                # Already drawing — constrain to 90° from last node, then grid snap
                last = self._bus_draw_nodes[-1]
                snapped_wx, snapped_wy = self._snap_90(last, *self._sg(wx, wy))
                # Double-click detection: new node very close to last node in screen space
                sx_last, sy_last = self._w2s(*last)
                sx_new,  sy_new  = self._w2s(snapped_wx, snapped_wy)
                if math.hypot(sx_new - sx_last, sy_new - sy_last) < 10:
                    # Double-click — finish the bus
                    self._finish_bus()
                    return
                self._bus_draw_nodes.append((snapped_wx, snapped_wy))
                if self._on_status:
                    self._on_status(
                        "Bus: click to add segment (90° snap). Double-click or right-click to finish."
                    )
            else:
                # Start a new bus at the clicked position
                wx, wy = self._sg(wx, wy)
                self._bus_draw_nodes = [(wx, wy)]
                self._preview_point  = (wx, wy)
                if self._on_status:
                    self._on_status(
                        "Bus: click to add segment (90° snap). Double-click or right-click to finish."
                    )
            self.redraw()

        elif self._tool in (TOOL_TLINE, TOOL_FEEDER):
            bus_id = self._hit_bus(wx, wy)
            if self._conn_from_bus is None:
                if bus_id:
                    self._conn_from_bus = bus_id
                    self._conn_from_tap = (wx, wy)
                    if self._on_status:
                        self._on_status(
                            f"From '{self._buses[bus_id].name}' — now click the destination."
                        )
            else:
                self._finish_connection(wx, wy, bus_id)

        elif self._tool == TOOL_TRANSFORMER:
            snap_id = self._snap_bus(wx, wy)
            tid = f"XFMR-{len(self._transformers) + 1}"
            if snap_id:
                bus = self._buses[snap_id]
                tap_pt = bus.nearest_tap(*self._sg(wx, wy))
                tap_x, tap_y = self._sg(*tap_pt)
                xfmr = DiagramTransformer(
                    id=tid, name=tid,
                    cx=tap_x,
                    cy=tap_y + XFMR_HALF,
                    hv_bus=snap_id, hv_tap_x=tap_x, hv_tap_y=tap_y,
                    hv_kv=bus.kv or 0.0,
                )
            else:
                wx, wy = self._sg(wx, wy)
                xfmr = DiagramTransformer(id=tid, name=tid, cx=wx, cy=wy)
            self._transformers[tid] = xfmr
            self._set_selection("transformer", tid)
            self._revert_to_select(event)

        elif self._tool == TOOL_SOURCE:
            snap_id = self._snap_bus(wx, wy)
            sid = f"SRC-{len(self._sources) + 1}"
            if snap_id:
                bus = self._buses[snap_id]
                tap_pt = bus.nearest_tap(*self._sg(wx, wy))
                tap_x, tap_y = self._sg(*tap_pt)
                src = DiagramSource(sid, sid, cx=tap_x, cy=tap_y - SRC_OFFSET,
                                    bus=snap_id, tap_x=tap_x, tap_y=tap_y,
                                    base_kv=bus.kv or 0.0)
            else:
                wx, wy = self._sg(wx, wy)
                src = DiagramSource(sid, sid, cx=wx, cy=wy)
            self._sources[sid] = src
            self._set_selection("source", sid)
            self._revert_to_select(event)

        elif self._tool == TOOL_LOAD:
            snap_id = self._snap_bus(wx, wy)
            lid = f"LOAD-{len(self._loads) + 1}"
            if snap_id:
                bus = self._buses[snap_id]
                tap_pt = bus.nearest_tap(*self._sg(wx, wy))
                tap_x, tap_y = self._sg(*tap_pt)
                ld = DiagramLoad(lid, lid, cx=tap_x,
                                 cy=tap_y + LOAD_LEAD + LOAD_AH,
                                 bus=snap_id, tap_x=tap_x, tap_y=tap_y)
            else:
                wx, wy = self._sg(wx, wy)
                ld = DiagramLoad(lid, lid, cx=wx, cy=wy)
            self._loads[lid] = ld
            self._set_selection("load", lid)
            self._revert_to_select(event)

        elif self._tool == TOOL_CT:
            result = self._nearest_wire(event.x, event.y)
            if result:
                kind, eid, t = result
                # Keep CT away from the transformer end of a lead (clamp to 20–80%)
                if kind.startswith("xfmr_"):
                    t = max(0.20, min(0.80, t))
                else:
                    t = max(0.10, min(0.90, t))
                cid = f"CT-{len(self._cts) + 1}"
                if kind == "conn":
                    ct = DiagramCT(cid, cid, eid, t)
                elif kind == "xfmr_hv":
                    ct = DiagramCT(cid, cid, "", t, xfmr_id=eid, xfmr_lead="hv")
                else:  # xfmr_lv
                    ct = DiagramCT(cid, cid, "", t, xfmr_id=eid, xfmr_lead="lv")
                self._cts[cid] = ct
                self._set_selection("ct", cid)
                self._revert_to_select(event)

        elif self._tool == TOOL_VT:
            bus_id = self._hit_bus(wx, wy)
            if bus_id:
                bus = self._buses[bus_id]
                tap_pt = bus.nearest_tap(wx, wy)
                vid = f"VT-{len(self._vts) + 1}"
                self._vts[vid] = DiagramVT(vid, vid, bus_id, tap_pt[0], tap_pt[1])
                self._set_selection("vt", vid)
                self._revert_to_select(event)

        elif self._tool == TOOL_BREAKER:
            result = self._nearest_connection(event.x, event.y)
            if result:
                conn_id, t = result
                bid = f"BKR-{len(self._breakers) + 1}"
                self._breakers[bid] = DiagramBreaker(bid, bid, conn_id, t)
                self._set_selection("breaker", bid)
                self._revert_to_select(event)

        elif self._tool == TOOL_DISCONNECT:
            result = self._nearest_connection(event.x, event.y)
            if result:
                conn_id, t = result
                did = f"DSW-{len(self._disconnects) + 1}"
                self._disconnects[did] = DiagramDisconnect(did, did, conn_id, t)
                self._set_selection("disconnect", did)
                self._revert_to_select(event)

        elif self._tool == TOOL_DELETE:
            self._delete_at(event, wx, wy)

    def _on_right_press(self, event: tk.Event) -> None:
        """Right-click: finish bus drawing if active; otherwise pan."""
        if self._tool == TOOL_BUS and self._bus_draw_nodes:
            self._finish_bus()
        else:
            self._pan_start(event)

    def _begin_drag(self, kind: str, elem_id: str, wx: float, wy: float) -> None:
        self._set_selection(kind, elem_id)
        self._drag_id     = elem_id
        self._drag_kind   = kind
        self._drag_origin = (wx, wy)

    def _delete_at(self, event: tk.Event, wx: float, wy: float) -> None:
        xfmr_id = self._hit_transformer(wx, wy)
        src_id  = self._hit_source(wx, wy)
        load_id = self._hit_load(wx, wy)
        ct_id   = self._hit_ct(event.x, event.y)
        vt_id   = self._hit_vt(wx, wy)
        bus_id  = self._hit_bus(wx, wy)
        conn_id = self._hit_connection(event.x, event.y)
        if xfmr_id:
            self._transformers.pop(xfmr_id, None)
            self._set_selection(None, None); self.redraw()
        elif src_id:
            self._sources.pop(src_id, None)
            self._set_selection(None, None); self.redraw()
        elif load_id:
            self._loads.pop(load_id, None)
            self._set_selection(None, None); self.redraw()
        elif ct_id:
            self._cts.pop(ct_id, None)
            self._set_selection(None, None); self.redraw()
        elif vt_id:
            self._vts.pop(vt_id, None)
            self._set_selection(None, None); self.redraw()
        elif bus_id:
            self._delete_bus(bus_id)
        elif conn_id:
            self._delete_connection(conn_id)

    def _on_drag(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT and self._drag_id and self._drag_origin:
            gx, gy = self._sg(wx, wy)
            dx = gx - self._drag_origin[0]
            dy = gy - self._drag_origin[1]
            if self._drag_kind == "bus":
                bus = self._buses[self._drag_id]
                bus.nodes = [(nx + dx, ny + dy) for nx, ny in bus.nodes]
            elif self._drag_kind == "bus_node":
                wx, wy = self._sg(wx, wy)   # snap before axis-lock
                bus = self._buses[self._drag_id]
                ni  = self._drag_node_idx
                ox, oy = bus.nodes[ni]   # original node position at drag start
                neighbours = [j for i,j in bus.edges if i==ni] + [i for i,j in bus.edges if j==ni]

                # Determine & lock the allowed axis on the first movement
                if self._drag_axis is None:
                    if len(neighbours) == 1:
                        # End node: lock to the existing segment's axis
                        nbx, nby = bus.nodes[neighbours[0]]
                        self._drag_axis = "v" if abs(nbx - ox) < 1 else "h"
                    elif len(neighbours) == 2:
                        nbx0, nby0 = bus.nodes[neighbours[0]]
                        nbx1, nby1 = bus.nodes[neighbours[1]]
                        if abs(nby0 - oy) < 1 and abs(nby1 - oy) < 1:
                            # Both neighbours on same Y → straight horizontal run → slide H
                            self._drag_axis = "h"
                        elif abs(nbx0 - ox) < 1 and abs(nbx1 - ox) < 1:
                            # Both neighbours on same X → straight vertical run → slide V
                            self._drag_axis = "v"
                        else:
                            # Corner node (one H, one V neighbour):
                            # lock to whichever axis the user first drags more
                            ddx = abs(wx - self._drag_origin[0])
                            ddy = abs(wy - self._drag_origin[1])
                            if ddx < 2 and ddy < 2:
                                return   # haven't moved enough yet — wait
                            self._drag_axis = "h" if ddx >= ddy else "v"
                    else:
                        self._drag_axis = "free"

                # Apply the locked axis constraint
                if self._drag_axis == "h":
                    wy = oy
                elif self._drag_axis == "v":
                    wx = ox

                bus.nodes[ni] = (wx, wy)
                self.redraw()
                return
            elif self._drag_kind and self._drag_kind.startswith("label_"):
                # Labels are dragged freely (no grid snap — fine positioning needed)
                raw_wx, raw_wy = self._s2w(event.x, event.y)
                ddx = raw_wx - self._drag_origin[0]
                ddy = raw_wy - self._drag_origin[1]
                lkind = self._drag_kind[6:]
                eid   = self._drag_id
                if lkind == "bus" and eid in self._buses:
                    b = self._buses[eid]; b.label_ox += ddx; b.label_oy += ddy
                elif lkind == "transformer" and eid in self._transformers:
                    t = self._transformers[eid]; t.label_ox += ddx; t.label_oy += ddy
                elif lkind == "source" and eid in self._sources:
                    s = self._sources[eid]; s.label_ox += ddx; s.label_oy += ddy
                elif lkind == "load" and eid in self._loads:
                    l = self._loads[eid]; l.label_ox += ddx; l.label_oy += ddy
                elif lkind == "conn" and eid in self._connections:
                    c = self._connections[eid]; c.label_ox += ddx; c.label_oy += ddy
                self._drag_origin = (raw_wx, raw_wy)
                self.redraw()
                return
            elif self._drag_kind in ("xfmr_hv", "xfmr_lv", "src_term", "load_term"):
                # Terminal rewire drag: show rubber-band + snap highlight
                self.redraw()
                snap_id = self._snap_bus(wx, wy)
                anc_sx, anc_sy = self._term_anchor
                if snap_id:
                    bus = self._buses[snap_id]
                    tap_pt = bus.nearest_tap(wx, wy)
                    tap_sx, tap_sy = self._w2s(*tap_pt)
                    self.canvas.create_line(anc_sx, anc_sy, tap_sx, tap_sy,
                                            fill="#0066CC", width=LINE_WIDTH, dash=(4, 3))
                    r = 7
                    self.canvas.create_oval(tap_sx - r, tap_sy - r,
                                            tap_sx + r, tap_sy + r,
                                            fill="#0066CC", outline="white", width=2)
                else:
                    self.canvas.create_line(anc_sx, anc_sy, event.x, event.y,
                                            fill="#888888", width=LINE_WIDTH, dash=(4, 3))
                return
            elif self._drag_kind == "transformer":
                xfmr = self._transformers[self._drag_id]
                xfmr.cx += dx;  xfmr.cy += dy
                # Re-snap taps and straighten leads when centre aligns with tap axis
                for attr_bus, attr_tx, attr_ty in (
                        ("hv_bus", "hv_tap_x", "hv_tap_y"),
                        ("lv_bus", "lv_tap_x", "lv_tap_y")):
                    bid = getattr(xfmr, attr_bus)
                    if bid and bid in self._buses:
                        tap = self._buses[bid].nearest_tap(
                            getattr(xfmr, attr_tx), getattr(xfmr, attr_ty))
                        setattr(xfmr, attr_tx, tap[0])
                        setattr(xfmr, attr_ty, tap[1])
                        # If transformer centre is within one grid cell of the tap
                        # axis, snap it onto that axis for a perfectly straight lead
                        snap_tol = GRID_SIZE * 1.2
                        if abs(xfmr.cx - tap[0]) < snap_tol:
                            xfmr.cx = tap[0]
                        if abs(xfmr.cy - tap[1]) < snap_tol:
                            xfmr.cy = tap[1]
            elif self._drag_kind == "source":
                src = self._sources[self._drag_id]
                src.cx += dx;  src.cy += dy
            elif self._drag_kind == "load":
                ld = self._loads[self._drag_id]
                ld.cx += dx;  ld.cy += dy
            elif self._drag_kind == "ct":
                ct = self._cts.get(self._drag_id)
                if ct:
                    t_raw = self._ct_project_t(ct, wx, wy)
                    if ct.xfmr_id:
                        ct.t = max(0.20, min(0.80, t_raw))
                    else:
                        ct.t = max(0.10, min(0.90, t_raw))
            self._drag_origin = (gx, gy)
            self.redraw()

    def _on_release(self, event: tk.Event) -> None:
        if self._drag_kind in ("xfmr_hv", "xfmr_lv", "src_term", "load_term"):
            wx, wy = self._s2w(event.x, event.y)
            snap_id = self._snap_bus(wx, wy)
            kind    = self._drag_kind
            eid     = self._drag_id
            if kind == "xfmr_hv" and eid in self._transformers:
                xfmr = self._transformers[eid]
                if snap_id:
                    tap = self._buses[snap_id].nearest_tap(wx, wy)
                    xfmr.hv_bus   = snap_id
                    xfmr.hv_tap_x = tap[0]
                    xfmr.hv_tap_y = tap[1]
                    xfmr.hv_kv    = self._buses[snap_id].kv or xfmr.hv_kv
                else:
                    xfmr.hv_bus = None
            elif kind == "xfmr_lv" and eid in self._transformers:
                xfmr = self._transformers[eid]
                if snap_id:
                    tap = self._buses[snap_id].nearest_tap(wx, wy)
                    xfmr.lv_bus   = snap_id
                    xfmr.lv_tap_x = tap[0]
                    xfmr.lv_tap_y = tap[1]
                    xfmr.lv_kv    = self._buses[snap_id].kv or xfmr.lv_kv
                else:
                    xfmr.lv_bus = None
            elif kind == "src_term" and eid in self._sources:
                src = self._sources[eid]
                if snap_id:
                    tap = self._buses[snap_id].nearest_tap(wx, wy)
                    src.bus     = snap_id
                    src.tap_x   = tap[0]
                    src.tap_y   = tap[1]
                    src.base_kv = self._buses[snap_id].kv or src.base_kv
                else:
                    src.bus = None
            elif kind == "load_term" and eid in self._loads:
                ld = self._loads[eid]
                if snap_id:
                    tap = self._buses[snap_id].nearest_tap(wx, wy)
                    ld.bus   = snap_id
                    ld.tap_x = tap[0]
                    ld.tap_y = tap[1]
                else:
                    ld.bus = None
            self.redraw()

        self._drag_id       = None
        self._drag_kind     = None
        self._drag_origin   = None
        self._drag_node_idx = None
        self._drag_axis     = None
        self._term_anchor   = None

    def _on_motion(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_BUS and self._bus_draw_nodes:
            self._preview_point = (wx, wy)
            self.redraw()
            return

        if self._tool in (TOOL_TLINE, TOOL_FEEDER) and self._conn_from_bus:
            self.redraw()
            bus = self._buses.get(self._conn_from_bus)
            if bus:
                tap_pt = bus.nearest_tap(*self._conn_from_tap)
                sx, sy = self._w2s(*tap_pt)
                self.canvas.create_line(sx, sy, event.x, event.y,
                                        width=LINE_WIDTH, fill="#888888", dash=(4, 4))

        elif self._tool in (TOOL_TRANSFORMER, TOOL_SOURCE, TOOL_LOAD):
            snap_id = self._snap_bus(wx, wy)
            self.redraw()
            if snap_id:
                bus = self._buses[snap_id]
                tap_pt = bus.nearest_tap(wx, wy)
                tap_sx, tap_sy = self._w2s(*tap_pt)
                # Snap dot on the bus
                r = 7
                self.canvas.create_oval(tap_sx - r, tap_sy - r,
                                        tap_sx + r, tap_sy + r,
                                        fill="#0066CC", outline="white", width=2)
                # For transformers, draw a dashed ghost showing where it will land
                if self._tool == TOOL_TRANSFORMER:
                    tap_x, tap_y = tap_pt
                    ghost_cy = tap_y + XFMR_HALF
                    ghost_bot_sx, ghost_bot_sy = self._w2s(tap_x, ghost_cy + XFMR_HALF)
                    self.canvas.create_line(tap_sx, tap_sy, tap_sx, ghost_bot_sy,
                                            fill="#0066CC", width=1, dash=(4, 3))
            else:
                # Show a subtle X when not over a bus so user knows snap is needed
                r = 5
                self.canvas.create_line(event.x-r, event.y-r, event.x+r, event.y+r,
                                        fill="#AAAAAA", width=1)
                self.canvas.create_line(event.x-r, event.y+r, event.x+r, event.y-r,
                                        fill="#AAAAAA", width=1)

    def _finish_connection(self, wx: float, wy: float, to_bus_id: Optional[str]) -> None:
        kind = "tline" if self._tool == TOOL_TLINE else "feeder"
        if self._conn_from_bus not in self._buses:
            self._conn_from_bus = None
            return
        cid = f"{kind.upper()}-{len(self._connections) + 1}"
        from_tap = self._conn_from_tap
        if kind == "feeder":
            conn = DiagramConnection(cid, cid, kind, self._conn_from_bus,
                                     from_tap=from_tap, to_point=(wx, wy))
        elif to_bus_id and to_bus_id != self._conn_from_bus:
            conn = DiagramConnection(cid, cid, kind, self._conn_from_bus,
                                     from_tap=from_tap, to_bus=to_bus_id, to_tap=(wx, wy))
        else:
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
        for cid in [k for k, c in self._connections.items()
                    if c.from_bus == bus_id or c.to_bus == bus_id]:
            self._delete_connection(cid)
        for vid in [k for k, v in self._vts.items() if v.bus_id == bus_id]:
            self._vts.pop(vid)
        # Detach elements that referenced this bus.
        for xfmr in self._transformers.values():
            if xfmr.hv_bus == bus_id:
                xfmr.hv_bus = None
            if xfmr.lv_bus == bus_id:
                xfmr.lv_bus = None
        for src in self._sources.values():
            if src.bus == bus_id:
                src.bus = None
        for ld in self._loads.values():
            if ld.bus == bus_id:
                ld.bus = None
        self._set_selection(None, None)
        self.redraw()

    def _delete_connection(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
        for cid in [k for k, c in self._cts.items() if c.connection_id == conn_id]:
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


def _point_to_segment_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)))
    return math.hypot(px - x1 - t*dx, py - y1 - t*dy)
