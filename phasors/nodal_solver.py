"""
nodal_solver.py — Per-tick nodal admittance (Y-bus) power flow solver.

Builds a Y-bus from the current switch/breaker states and line impedances,
solves for per-node complex voltage phasors via numpy, and writes
wye_voltages objects into device._cache["voltage"] *before* any tree-walk
property is first accessed.  The existing recursive voltage/current getters
see the cached value and return immediately, so ring-bus topologies that
would otherwise cause infinite recursion are handled correctly.

Architecture
------------
Every primary AC device is a Y-bus node (single-port types) or two Y-bus
nodes (two-port types: PowerTransformer, VoltageRegulator).

  Single-port node key : (device, '')
  Two-port H-side key  : (device, 'H')
  Two-port X-side key  : (device, 'X')

Branch admittances
------------------
  Bus / VoltageSource connection   → Y_IDEAL (1 × 10⁶ S, ~zero impedance)
  Closed CircuitBreaker/Disconnect → Y_IDEAL
  Open  CircuitBreaker/Disconnect  → no branch (open circuit)
  PowerLine                        → Y = 1 / Z_line  (Z = (r + jx) × len)
                                     upstream end of line: ideal connection
                                     downstream end     : line admittance
  PowerTransformer / VoltageRegulator → off-nominal-tap model
                                     Y_XFMR = 1 × 10⁴ S (large ≈ ideal)
                                     a_c = ratio × exp(−j·shift_rad)
                                     Y[H][H] += Y_t / ratio²
                                     Y[X][X] += Y_t
                                     Y[H][X] −= (Y_t/ratio) × exp(−j·shift)
                                     Y[X][H] −= (Y_t/ratio) × exp(+j·shift)

Reachability
------------
A forward BFS from every VoltageSource (following connections, downstream_device,
and x_connections of *closed* switches) identifies which devices are
energised.  Devices not reachable from any source are excluded from the
Y-bus; their caches remain empty so the tree-walk returns zero volts.

Solving — normal operation
--------------------------
Three-phase balanced positive-sequence: one complex Y-bus is solved for the
phase-A phasor.  Phases B and C are derived by +120° / +240° rotation.
Three Gauss-Seidel iterations update PQ-bus current injections.

Solving — fault conditions (symmetrical components)
----------------------------------------------------
When any device has an active fault_state the solver builds all three sequence
networks (Y1=positive, Y2=negative, Y0=zero) and applies the sequence-network
Thevenin method at each faulted bus:

  1. Solve Y1 for pre-fault positive-sequence voltages V1_pf (full network).
  2. Build Y2 (= Y1 for passive networks) and Y0 (zero-seq line impedances,
     transformer zero-seq model per winding grounding).
  3. For each faulted bus f, compute the three Thevenin impedances
     Z1f, Z2f, Z0f by solving Yk_r · z = e_f (one solve per sequence).
  4. Apply fault boundary conditions (SLG / LL / LLG / 3PH) to obtain
     sequence injection currents I0, I1, I2.
  5. Superpose voltage corrections: ΔV_seq[k] = −z_col[k] · I_seq.
  6. Transform sequence → phase:
       Va = V0 + V1 + V2
       Vb = V0 + α·V1 + α²·V2   (α = exp(+j120°))
       Vc = V0 + α²·V1 + α·V2
  7. Write unbalanced wye_voltages objects to device caches.

Zero-sequence transformer model (winding grounding matters):
  YG–YG : full ideal-transformer stamp (passes zero-seq both ways)
  YG–D  : shunt admittance on H-node (delta circulates, blocks crossing)
  D–YG  : shunt admittance on X-node
  otherwise: both ports isolated in Y0

Fallback
--------
If numpy is unavailable or the reduced admittance matrix is singular,
solve_and_cache() returns False and the caller should fall back to the
existing recursive tree-walk.
"""

import cmath
import math
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Device-type sets
# ---------------------------------------------------------------------------

_PRIMARY_TYPES = frozenset({
    'Bus', 'VoltageSource', 'PowerLine',
    'CircuitBreaker', 'Disconnect',
    'PowerTransformer', 'VoltageRegulator',
    'Load', 'ShuntCapacitor', 'ShuntReactor', 'SVC',
})

_TWO_PORT_TYPES = frozenset({'PowerTransformer', 'VoltageRegulator'})
_SWITCH_TYPES   = frozenset({'CircuitBreaker', 'Disconnect'})
_LOAD_TYPES     = frozenset({'Load', 'ShuntCapacitor', 'ShuntReactor', 'SVC'})

# ---------------------------------------------------------------------------
# Admittance constants
# ---------------------------------------------------------------------------

_Y_IDEAL = 1e6 + 0j   # zero-impedance connection (large but finite)
_Y_XFMR  = 1e4 + 0j   # ideal transformer branch admittance

# Phase-B/C rotation factors (codebase convention: A=0°, B=+120°, C=+240°)
_ROT_B = cmath.exp(1j * math.radians(120))   # α
_ROT_C = cmath.exp(1j * math.radians(240))   # α²

# Zero-sequence transformer: windings that pass zero-sequence current
_ZS_PASS = frozenset({"YG", "ZG"})

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def solve_and_cache(devices: dict) -> bool:
    """
    Build the Y-bus, solve for node voltages, and write wye_voltages into
    every primary device's _cache["voltage"] (and transformer-specific keys).

    Returns True on success.  Returns False — without raising — when numpy
    is not available or the network cannot be solved (singular / no source),
    signalling the caller to fall back to the recursive tree-walk.
    """
    try:
        import numpy as np
    except ImportError:
        return False

    primary = [d for d in devices.values()
               if d.__class__.__name__ in _PRIMARY_TYPES]
    if not primary:
        return False

    try:
        return _run_solver(primary, np)
    except Exception as exc:
        log.debug("nodal_solver fallback — %s: %s", type(exc).__name__, exc)
        return False


# ---------------------------------------------------------------------------
# Internal solver
# ---------------------------------------------------------------------------

def _run_solver(primary: list, np) -> bool:
    primary_set = set(primary)

    # 1. BFS: find all devices energised from any VoltageSource.
    reachable = _bfs_reachable(primary_set)
    if not reachable:
        return False

    # 2. Build node list.  Two-port devices get two nodes (H and X).
    node_keys, key_idx = _build_node_index(reachable)
    N = len(node_keys)
    if N == 0:
        return False

    # 3. Collect slack-bus entries (VoltageSource → fixed voltage).
    slack_idx: dict[int, complex] = {}
    for dev in reachable:
        if dev.__class__.__name__ == 'VoltageSource':
            v = getattr(dev, '_voltage', None)
            if v is not None:
                idx = key_idx.get((dev, ''))
                if idx is not None:
                    slack_idx[idx] = v.a.to_complex()
    if not slack_idx:
        return False

    # 4. Build positive-sequence Y-bus and solve pre-fault voltages.
    Y1 = _build_ybus(reachable, primary_set, key_idx, N, np)
    V1_pf = _iterative_solve(Y1, node_keys, key_idx, reachable, slack_idx, N, np)
    if V1_pf is None:
        return False

    # 5. Check for active faults; branch into sequence-network solve if any.
    faults = _collect_faults(reachable, key_idx)

    if not faults:
        # Balanced case: derive B/C from A by rotation.
        _write_cache(V1_pf, node_keys, key_idx, reachable)
    else:
        # Y2 = Y1 (passive network is symmetric for negative-sequence).
        Y2 = Y1
        Y0 = _build_ybus_zero(reachable, primary_set, key_idx, N, np)
        V0, V1, V2 = _seq_fault_solve(Y0, Y1, Y2, V1_pf, faults, slack_idx, N, np)
        _write_cache_seq(V0, V1, V2, node_keys, key_idx, reachable)

    return True


# ---------------------------------------------------------------------------
# BFS reachability
# ---------------------------------------------------------------------------

def _bfs_reachable(primary_set: set) -> set:
    """
    Forward BFS from VoltageSource devices, following closed switches.
    Returns the set of energised primary devices.
    """
    from collections import deque

    seeds = [d for d in primary_set if d.__class__.__name__ == 'VoltageSource']
    visited: set = set(seeds)
    queue   = deque(seeds)

    while queue:
        dev = queue.popleft()
        for nbr in _forward_neighbors(dev, primary_set):
            if nbr not in visited:
                visited.add(nbr)
                queue.append(nbr)

    return visited


def _forward_neighbors(dev, primary_set: set) -> list:
    """Downstream primary-device neighbors, respecting open switches."""
    cls = dev.__class__.__name__
    out = []

    # Bus, VoltageSource, Load-types, VoltageRegulator — use .connections
    for c in getattr(dev, 'connections', []):
        if c in primary_set:
            out.append(c)

    if cls == 'PowerLine':
        dd = getattr(dev, 'downstream_device', None)
        if dd and dd in primary_set:
            out.append(dd)

    elif cls in _SWITCH_TYPES:
        if getattr(dev, 'is_closed', True):
            for c in getattr(dev, 'x_connections', []):
                if c in primary_set:
                    out.append(c)

    elif cls == 'PowerTransformer':
        # Transformer is always conducting (no "open" state).
        for c in getattr(dev, 'x_connections', []):
            if c in primary_set:
                out.append(c)

    return out


# ---------------------------------------------------------------------------
# Node index
# ---------------------------------------------------------------------------

def _build_node_index(reachable: set) -> tuple:
    """
    Returns (node_keys list, key_idx dict).
    node_key = (dev, '')        for single-port devices
             = (dev, 'H'/'X')  for two-port devices
    """
    node_keys: list = []
    key_idx:   dict = {}

    # Deterministic ordering for reproducible matrix layout.
    for dev in sorted(reachable, key=lambda d: d.name):
        cls = dev.__class__.__name__
        if cls in _TWO_PORT_TYPES:
            for side in ('H', 'X'):
                k = (dev, side)
                key_idx[k] = len(node_keys)
                node_keys.append(k)
        else:
            k = (dev, '')
            key_idx[k] = len(node_keys)
            node_keys.append(k)

    return node_keys, key_idx


def _dev_key(dev, upstream_side: bool = True) -> tuple:
    """
    Node key for a device from a given perspective.
    upstream_side=True  → H-node (or '' for single-port)
    upstream_side=False → X-node (or '' for single-port)
    """
    if dev.__class__.__name__ in _TWO_PORT_TYPES:
        return (dev, 'H') if upstream_side else (dev, 'X')
    return (dev, '')


# ---------------------------------------------------------------------------
# Y-bus construction
# ---------------------------------------------------------------------------

def _build_ybus(reachable: set, primary_set: set, key_idx: dict, N: int, np):
    Y    = np.zeros((N, N), dtype=complex)
    seen: set = set()   # (min_i, max_i) — prevents double-stamping

    def stamp(ki, kj, y):
        i = key_idx.get(ki)
        j = key_idx.get(kj)
        if i is None or j is None or i == j:
            return
        edge = (min(i, j), max(i, j))
        if edge in seen:
            return
        seen.add(edge)
        Y[i, i] += y
        Y[j, j] += y
        Y[i, j] -= y
        Y[j, i] -= y

    def stamp_xfmr(ki_h, ki_x, ratio, shift_deg):
        """Ideal off-nominal-tap transformer branch."""
        i = key_idx.get(ki_h)
        j = key_idx.get(ki_x)
        if i is None or j is None:
            return
        edge = (min(i, j), max(i, j))
        if edge in seen:
            return
        seen.add(edge)
        shift = math.radians(shift_deg)
        # a_c = ratio × exp(−j·shift)
        # Constraint: V_X = V_H / a_c = (V_H / ratio) × exp(+j·shift)
        Y[i, i] += _Y_XFMR / (ratio * ratio)
        Y[j, j] += _Y_XFMR
        Y[i, j] -= (_Y_XFMR / ratio) * cmath.exp(-1j * shift)
        Y[j, i] -= (_Y_XFMR / ratio) * cmath.exp(+1j * shift)

    for dev in reachable:
        cls  = dev.__class__.__name__
        k_h  = _dev_key(dev, True)    # H / main node
        k_x  = _dev_key(dev, False)   # X node (same as k_h for single-port)

        # ── PowerTransformer ──────────────────────────────────────────────
        if cls == 'PowerTransformer':
            stamp_xfmr(k_h, k_x, dev.ratio, dev.phase_shift_deg)
            # H-side ↔ upstream device
            up = getattr(dev, 'upstream_device', None)
            if up in reachable:
                stamp(_dev_key(up, False), k_h, _Y_IDEAL)
            # X-side ↔ each downstream device
            for c in getattr(dev, 'x_connections', []):
                if c in reachable:
                    stamp(k_x, _dev_key(c, True), _Y_IDEAL)

        # ── VoltageRegulator ──────────────────────────────────────────────
        elif cls == 'VoltageRegulator':
            # ratio = V_H / V_X  (same sense as PowerTransformer.ratio)
            stamp_xfmr(k_h, k_x, dev.ratio, 0.0)
            up = getattr(dev, 'upstream_device', None)
            if up in reachable:
                stamp(_dev_key(up, False), k_h, _Y_IDEAL)
            # VoltageRegulator uses .connections (not .x_connections)
            for c in getattr(dev, 'connections', []):
                if c in reachable:
                    stamp(k_x, _dev_key(c, True), _Y_IDEAL)

        # ── Bus / VoltageSource / Load-types ─────────────────────────────
        elif cls in ('Bus', 'VoltageSource') or cls in _LOAD_TYPES:
            for c in getattr(dev, 'connections', []):
                if c in reachable:
                    stamp(k_h, _dev_key(c, True), _Y_IDEAL)

        # ── PowerLine ─────────────────────────────────────────────────────
        elif cls == 'PowerLine':
            # Upstream end: ideal connection (line node ≈ upstream bus)
            up = getattr(dev, 'upstream_device', None)
            if up in reachable:
                stamp(_dev_key(up, False), k_h, _Y_IDEAL)
            # Downstream end: line series impedance
            dd = getattr(dev, 'downstream_device', None)
            if dd in reachable:
                z = complex(dev.r_per_km, dev.x_per_km) * dev.length_km
                y_line = (1.0 / z) if abs(z) > 1e-12 else _Y_IDEAL
                stamp(k_h, _dev_key(dd, True), y_line)

        # ── CircuitBreaker / Disconnect ───────────────────────────────────
        elif cls in _SWITCH_TYPES:
            if getattr(dev, 'is_closed', True):
                up = getattr(dev, 'upstream_device', None)
                if up in reachable:
                    stamp(_dev_key(up, False), k_h, _Y_IDEAL)
                for c in getattr(dev, 'x_connections', []):
                    if c in reachable:
                        stamp(k_h, _dev_key(c, True), _Y_IDEAL)
            # Open switch: Bus-to-CB edge still stamped when Bus processes
            # its connections list (Bus → CB ideal, CB → Bus2 nothing).

    return Y


# ---------------------------------------------------------------------------
# Iterative solve
# ---------------------------------------------------------------------------

def _iterative_solve(Y, node_keys, key_idx, reachable, slack_idx, N, np):
    """
    Partition [Y][V] = [I] into slack (known V) and unknown rows/cols.
    Iterates 3 times, updating PQ current injections each pass.
    Returns complex voltage vector of length N, or None if matrix is singular.
    """
    slack_list   = sorted(slack_idx.keys())
    slack_set    = set(slack_list)
    unknown_list = [i for i in range(N) if i not in slack_set]

    if not unknown_list:
        # Every node is a slack bus.
        V = np.zeros(N, dtype=complex)
        for i, va in slack_idx.items():
            V[i] = va
        return V

    # Flat-start: unknowns initialised to slack voltage magnitude, angle 0.
    V_init_mag = abs(next(iter(slack_idx.values())))
    V = np.zeros(N, dtype=complex)
    for i, va in slack_idx.items():
        V[i] = va
    for i in unknown_list:
        V[i] = complex(V_init_mag)

    # Extract sub-matrices (constant across iterations).
    Y_uu = Y[np.ix_(unknown_list, unknown_list)]
    Y_us = Y[np.ix_(unknown_list, slack_list)]
    V_s  = np.array([V[i] for i in slack_list], dtype=complex)

    # Check Y_uu is non-singular before iterating.
    if np.linalg.matrix_rank(Y_uu) < len(unknown_list):
        return None

    for _iter in range(3):
        # Build injection vector for PQ buses.
        I = np.zeros(N, dtype=complex)
        for dev in reachable:
            if dev.__class__.__name__ not in _LOAD_TYPES:
                continue
            k = key_idx.get(_dev_key(dev, True))
            if k is None:
                continue
            va_node = V[k]
            if abs(va_node) < 1e-6:
                va_node = complex(V_init_mag)
            try:
                pq  = dev.get_phase_pq()
                s_a = complex(pq['a'][0], pq['a'][1])
                # Load absorbs power → negative current injection into bus.
                # I = conj(S/V)  → I_inj = −conj(S/V) = −S*.conj() / V.conj()
                I[k] += -(s_a.conjugate()) / (va_node.conjugate())
            except Exception:
                pass

        rhs = I[unknown_list] - Y_us @ V_s
        try:
            V_u = np.linalg.solve(Y_uu, rhs)
        except np.linalg.LinAlgError:
            return None

        for idx, val in zip(unknown_list, V_u):
            V[idx] = val

    return V


# ---------------------------------------------------------------------------
# Write voltages back to device caches
# ---------------------------------------------------------------------------

def _write_cache(V, node_keys, key_idx, reachable) -> None:
    from .voltage_phasor import VoltagePhasor
    from .wye_system import wye_voltages

    def _make_wye(va: complex) -> wye_voltages:
        """Phase-A complex phasor → balanced three-phase wye_voltages."""
        def _vp(vc: complex) -> VoltagePhasor:
            mag, ang_rad = cmath.polar(vc)
            return VoltagePhasor(max(0.0, mag), math.degrees(ang_rad))
        return wye_voltages(_vp(va), _vp(va * _ROT_B), _vp(va * _ROT_C))

    for dev in reachable:
        cls = dev.__class__.__name__

        if cls == 'PowerTransformer':
            idx_h = key_idx.get((dev, 'H'))
            idx_x = key_idx.get((dev, 'X'))
            if idx_h is not None:
                wv_h = _make_wye(V[idx_h])
                dev._cache['primary_voltage']   = wv_h
            if idx_x is not None:
                wv_x = _make_wye(V[idx_x])
                dev._cache['voltage']           = wv_x
                dev._cache['secondary_voltage'] = wv_x

        elif cls == 'VoltageRegulator':
            idx_x = key_idx.get((dev, 'X'))
            if idx_x is not None:
                dev._cache['voltage'] = _make_wye(V[idx_x])

        else:
            idx = key_idx.get((dev, ''))
            if idx is not None:
                dev._cache['voltage'] = _make_wye(V[idx])


# ---------------------------------------------------------------------------
# Fault collection
# ---------------------------------------------------------------------------

def _collect_faults(reachable: set, key_idx: dict) -> list:
    """Return [(node_idx, fault_state)] for every device with an active fault."""
    result = []
    for dev in reachable:
        fs = getattr(dev, 'fault_state', None)
        if fs is None:
            continue
        cls = dev.__class__.__name__
        # Two-port devices: fault sits on the X (secondary) node.
        k = (dev, 'X') if cls in _TWO_PORT_TYPES else (dev, '')
        idx = key_idx.get(k)
        if idx is not None:
            result.append((idx, fs))
    return result


# ---------------------------------------------------------------------------
# Zero-sequence Y-bus
# ---------------------------------------------------------------------------

def _build_ybus_zero(reachable: set, primary_set: set, key_idx: dict, N: int, np):
    """
    Build zero-sequence admittance matrix.

    Differences from positive-sequence Y-bus:
    - PowerLine: uses r0_per_km / x0_per_km (default 3× positive-seq).
    - PowerTransformer: zero-sequence model depends on winding grounding.
    """
    Y = np.zeros((N, N), dtype=complex)
    seen: set = set()

    def stamp(ki, kj, y):
        i = key_idx.get(ki)
        j = key_idx.get(kj)
        if i is None or j is None or i == j:
            return
        edge = (min(i, j), max(i, j))
        if edge in seen:
            return
        seen.add(edge)
        Y[i, i] += y
        Y[j, j] += y
        Y[i, j] -= y
        Y[j, i] -= y

    def stamp_shunt(ki, y):
        i = key_idx.get(ki)
        if i is not None:
            Y[i, i] += y

    def stamp_xfmr_zero(ki_h, ki_x, h_winding, x_winding, ratio, shift_deg):
        h_pass = h_winding in _ZS_PASS
        x_pass = x_winding in _ZS_PASS
        i = key_idx.get(ki_h)
        j = key_idx.get(ki_x)
        if h_pass and x_pass:
            if i is None or j is None:
                return
            edge = (min(i, j), max(i, j))
            if edge in seen:
                return
            seen.add(edge)
            shift = math.radians(shift_deg)
            Y[i, i] += _Y_XFMR / (ratio * ratio)
            Y[j, j] += _Y_XFMR
            Y[i, j] -= (_Y_XFMR / ratio) * cmath.exp(-1j * shift)
            Y[j, i] -= (_Y_XFMR / ratio) * cmath.exp(+1j * shift)
        elif h_pass and not x_pass:
            # Delta/ungrounded-Y on X: H-side shunt to ground (delta circulates).
            stamp_shunt(ki_h, _Y_XFMR)
        elif not h_pass and x_pass:
            # Delta/ungrounded-Y on H: X-side shunt to ground.
            stamp_shunt(ki_x, _Y_XFMR)
        # else: both blocked — no stamp.

    for dev in reachable:
        cls = dev.__class__.__name__
        k_h = _dev_key(dev, True)
        k_x = _dev_key(dev, False)

        if cls == 'PowerTransformer':
            stamp_xfmr_zero(k_h, k_x, dev.h_winding, dev.x_winding,
                             dev.ratio, dev.phase_shift_deg)
            up = getattr(dev, 'upstream_device', None)
            if up in reachable:
                stamp(_dev_key(up, False), k_h, _Y_IDEAL)
            for c in getattr(dev, 'x_connections', []):
                if c in reachable:
                    stamp(k_x, _dev_key(c, True), _Y_IDEAL)

        elif cls == 'VoltageRegulator':
            # Assume grounded-wye on both sides for zero-sequence.
            stamp_xfmr_zero(k_h, k_x, 'YG', 'YG', dev.ratio, 0.0)
            up = getattr(dev, 'upstream_device', None)
            if up in reachable:
                stamp(_dev_key(up, False), k_h, _Y_IDEAL)
            for c in getattr(dev, 'connections', []):
                if c in reachable:
                    stamp(k_x, _dev_key(c, True), _Y_IDEAL)

        elif cls in ('Bus', 'VoltageSource') or cls in _LOAD_TYPES:
            for c in getattr(dev, 'connections', []):
                if c in reachable:
                    stamp(k_h, _dev_key(c, True), _Y_IDEAL)

        elif cls == 'PowerLine':
            up = getattr(dev, 'upstream_device', None)
            if up in reachable:
                stamp(_dev_key(up, False), k_h, _Y_IDEAL)
            dd = getattr(dev, 'downstream_device', None)
            if dd in reachable:
                z0 = complex(dev.r0_per_km, dev.x0_per_km) * dev.length_km
                y0_line = (1.0 / z0) if abs(z0) > 1e-12 else _Y_IDEAL
                stamp(k_h, _dev_key(dd, True), y0_line)

        elif cls in _SWITCH_TYPES:
            if getattr(dev, 'is_closed', True):
                up = getattr(dev, 'upstream_device', None)
                if up in reachable:
                    stamp(_dev_key(up, False), k_h, _Y_IDEAL)
                for c in getattr(dev, 'x_connections', []):
                    if c in reachable:
                        stamp(k_h, _dev_key(c, True), _Y_IDEAL)

    return Y


# ---------------------------------------------------------------------------
# Sequence-network fault solve (superposition / Thevenin)
# ---------------------------------------------------------------------------

def _seq_fault_solve(Y0, Y1, Y2, V1_pf, faults: list, slack_idx: dict, N: int, np):
    """
    Apply sequence-network Thevenin method for each active fault.

    Algorithm per fault bus f:
      - Reduce each Y-bus by grounding slacks (V=0 in seq 0,2; Vf in seq 1).
      - Solve Y_r · z = e_f to get impedance column Z[:,f].
      - Compute sequence injection currents from fault boundary conditions.
      - Accumulate voltage corrections ΔV_seq[k] = −Z[k,f] · I_seq.

    Returns (V0, V1, V2) arrays of length N.
    """
    alpha  = _ROT_B   # exp(+j120°)
    alpha2 = _ROT_C   # exp(+j240°)

    V0 = np.zeros(N, dtype=complex)
    V1 = V1_pf.copy()
    V2 = np.zeros(N, dtype=complex)

    slack_set = set(slack_idx.keys())
    free = [i for i in range(N) if i not in slack_set]
    if not free:
        return V0, V1, V2

    Y0r = Y0[np.ix_(free, free)]
    Y1r = Y1[np.ix_(free, free)]
    Y2r = Y2[np.ix_(free, free)]

    if (np.linalg.matrix_rank(Y1r) < len(free) or
            np.linalg.matrix_rank(Y0r) < len(free) or
            np.linalg.matrix_rank(Y2r) < len(free)):
        return V0, V1, V2

    free_map = {node: pos for pos, node in enumerate(free)}

    for f_idx, fs in faults:
        if f_idx not in free_map:
            continue
        f_pos = free_map[f_idx]

        Vf = V1_pf[f_idx]
        if abs(Vf) < 1e-6:
            continue

        # Thevenin impedance columns: solve Y·z = e_f in each sequence network.
        e_f = np.zeros(len(free), dtype=complex)
        e_f[f_pos] = 1.0
        try:
            z1_col = np.linalg.solve(Y1r, e_f)
            z2_col = np.linalg.solve(Y2r, e_f)
            z0_col = np.linalg.solve(Y0r, e_f)
        except np.linalg.LinAlgError:
            continue

        Z1f = z1_col[f_pos]
        Z2f = z2_col[f_pos]
        Z0f = z0_col[f_pos]

        # Fault impedance (R + jX from magnitude and X/R ratio).
        z_mag = float(fs.get("current_impedance", fs.get("impedance", 0.01)))
        xr    = float(fs.get("x_r_ratio", 15.0))
        scale = math.sqrt(1.0 + xr * xr)
        Zf    = complex(z_mag / scale, z_mag * xr / scale)

        ftype = fs.get("fault_type", "3PH")

        # Sequence injection currents at fault bus.
        if ftype in ("3PH", "Symmetric"):
            I1 = Vf / (Z1f + Zf)
            I2 = 0j
            I0 = 0j

        elif ftype.startswith("SLG"):
            # SLG on any single phase: I1 = I2 = I0
            I1 = Vf / (Z1f + Z2f + Z0f + 3 * Zf)
            I2 = I1
            I0 = I1

        elif ftype.startswith("LLG"):
            # Double line-to-ground: Z2 parallel with (Z0 + 3Zf) in series with Z1.
            denom = Z2f + Z0f + 3 * Zf
            Z20   = Z2f * (Z0f + 3 * Zf) / denom
            I1    = Vf / (Z1f + Z20)
            I2    = -I1 * (Z0f + 3 * Zf) / denom
            I0    = -I1 * Z2f / denom

        elif ftype.startswith("LL"):
            # Line-to-line (any phase pair): I1 = −I2, I0 = 0.
            I1 = Vf / (Z1f + Z2f + Zf)
            I2 = -I1
            I0 = 0j

        else:
            continue

        # Superpose voltage corrections onto all free buses.
        for pos, node in enumerate(free):
            V1[node] -= z1_col[pos] * I1
            V2[node] -= z2_col[pos] * I2
            V0[node] -= z0_col[pos] * I0

    return V0, V1, V2


# ---------------------------------------------------------------------------
# Write unbalanced sequence voltages to device caches
# ---------------------------------------------------------------------------

def _write_cache_seq(V0, V1, V2, node_keys: list, key_idx: dict, reachable: set) -> None:
    """Transform sequence voltages → unbalanced per-phase wye_voltages and cache."""
    from .voltage_phasor import VoltagePhasor
    from .wye_system import wye_voltages

    alpha  = _ROT_B   # exp(+j120°)
    alpha2 = _ROT_C   # exp(+j240°)

    def _vp(vc: complex) -> VoltagePhasor:
        mag, ang_rad = cmath.polar(vc)
        return VoltagePhasor(max(0.0, mag), math.degrees(ang_rad))

    def _make_wye_seq(v0: complex, v1: complex, v2: complex) -> wye_voltages:
        va = v0 + v1 + v2
        vb = v0 + alpha  * v1 + alpha2 * v2
        vc = v0 + alpha2 * v1 + alpha  * v2
        return wye_voltages(_vp(va), _vp(vb), _vp(vc))

    for dev in reachable:
        cls = dev.__class__.__name__

        if cls == 'PowerTransformer':
            idx_h = key_idx.get((dev, 'H'))
            idx_x = key_idx.get((dev, 'X'))
            if idx_h is not None:
                dev._cache['primary_voltage'] = _make_wye_seq(
                    V0[idx_h], V1[idx_h], V2[idx_h])
            if idx_x is not None:
                wv = _make_wye_seq(V0[idx_x], V1[idx_x], V2[idx_x])
                dev._cache['voltage']           = wv
                dev._cache['secondary_voltage'] = wv

        elif cls == 'VoltageRegulator':
            idx_x = key_idx.get((dev, 'X'))
            if idx_x is not None:
                dev._cache['voltage'] = _make_wye_seq(
                    V0[idx_x], V1[idx_x], V2[idx_x])

        else:
            idx = key_idx.get((dev, ''))
            if idx is not None:
                dev._cache['voltage'] = _make_wye_seq(V0[idx], V1[idx], V2[idx])
