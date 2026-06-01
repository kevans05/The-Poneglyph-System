"""AC power flow solver — Newton-Raphson method.

Solves for bus voltage magnitudes and angles given:
  - One slack bus (fixed V and angle)
  - PQ buses (fixed P and Q load/generation)
  - PV buses (fixed P and |V|, for generators) — future extension

After solving, CT and VT secondary quantities are computed from the
bus voltages and branch currents.
"""

from __future__ import annotations

import cmath
import math
from typing import Optional

import numpy as np

from poneglyph.simulation.network import Network, Bus, Branch
from poneglyph.simulation.phasors import ThreePhaseQuantity, balanced_voltages
from poneglyph.simulation.devices.instrument_transformer import CT, VT


class PowerFlowResult:
    def __init__(self, converged: bool, iterations: int, network: Network):
        self.converged = converged
        self.iterations = iterations
        self.network = network

    def __repr__(self) -> str:
        status = "converged" if self.converged else "DID NOT CONVERGE"
        return f"<PowerFlowResult {status} in {self.iterations} iterations>"


class PowerFlowSolver:
    """AC power flow for balanced 3-phase networks (Gauss-Seidel method).

    The single-phase per-unit model is used; all quantities are
    per-phase positive-sequence. Full 3-phase quantities are recovered
    by applying balanced phase offsets.
    """

    def __init__(self, network: Network, max_iter: int = 50, tolerance: float = 1e-6):
        self.network = network
        self.max_iter = max_iter
        self.tolerance = tolerance

        # Bus scheduling: {bus_id: {"type": "slack"|"pq"|"pv", "P": ..., "Q": ...}}
        self._schedule: dict[str, dict] = {}
        self._slack_bus: Optional[str] = None

    def set_slack_bus(self, bus_id: str, v_pu: float = 1.0, angle_deg: float = 0.0) -> None:
        self._slack_bus = bus_id
        self._schedule[bus_id] = {
            "type": "slack",
            "V": v_pu,
            "angle": math.radians(angle_deg),
        }

    def set_load(self, bus_id: str, p_mw: float, q_mvar: float) -> None:
        base = self.network.base_mva
        self._schedule[bus_id] = {
            "type": "pq",
            "P": -p_mw / base,   # load is negative injection
            "Q": -q_mvar / base,
        }

    def solve(self) -> PowerFlowResult:
        """Run Newton-Raphson and update bus voltages in-place."""
        net = self.network
        buses = list(net.buses.values())
        n = len(buses)
        idx = {b.id: i for i, b in enumerate(buses)}

        # Build admittance matrix (Y-bus)
        Y = np.zeros((n, n), dtype=complex)
        for branch in net.branches.values():
            if not branch.closed:
                continue
            i, j = idx[branch.from_bus], idx[branch.to_bus]
            y = 1.0 / branch.z_pu if branch.z_pu != 0 else 0.0
            phi = getattr(branch, "phase_shift_rad", 0.0)
            if abs(phi) < 1e-9:
                # Symmetric: plain line or Yy/Dd transformer
                Y[i, i] += y
                Y[j, j] += y
                Y[i, j] -= y
                Y[j, i] -= y
            else:
                # Asymmetric complex-tap model: a = e^(jφ), HV at i, LV at j
                # Y[i,i] = y/|a|² = y  (|a|=1)
                # Y[j,j] = y
                # Y[i,j] = -y / conj(a)
                # Y[j,i] = -y / a
                a = cmath.rect(1.0, phi)
                Y[i, i] += y
                Y[j, j] += y
                Y[i, j] -= y / a.conjugate()
                Y[j, i] -= y / a

        # Initial voltage vector
        V = np.array([b.v_pu for b in buses], dtype=complex)

        # Force slack bus
        if self._slack_bus:
            si = idx[self._slack_bus]
            sched = self._schedule[self._slack_bus]
            V[si] = cmath.rect(sched["V"], sched["angle"])

        converged = False
        iterations = 0

        for iterations in range(1, self.max_iter + 1):
            # Compute power injections
            I = Y @ V
            S_calc = V * np.conj(I)

            mismatch = []
            pq_idx = []
            for bus in buses:
                bi = idx[bus.id]
                sched = self._schedule.get(bus.id, {"type": "pq", "P": 0.0, "Q": 0.0})
                if sched["type"] == "slack":
                    continue
                dP = sched.get("P", 0.0) - S_calc[bi].real
                dQ = sched.get("Q", 0.0) - S_calc[bi].imag
                mismatch.extend([dP, dQ])
                pq_idx.append(bi)

            if not mismatch:
                converged = True
                break

            err = max(abs(x) for x in mismatch)
            if err < self.tolerance:
                converged = True
                break

            # Gauss-Seidel voltage update: V_i = (I_spec - sum_{j≠i}(Y_ij*V_j)) / Y_ii
            for bi in pq_idx:
                bus = buses[bi]
                sched = self._schedule.get(bus.id, {"type": "pq", "P": 0.0, "Q": 0.0})
                S_spec = complex(sched.get("P", 0.0), sched.get("Q", 0.0))
                I_inj = np.conj(S_spec / V[bi]) if abs(V[bi]) > 1e-9 else 0.0
                off_diag = sum(Y[bi, j] * V[j] for j in range(n) if j != bi)
                if abs(Y[bi, bi]) > 1e-12:
                    V[bi] = (I_inj - off_diag) / Y[bi, bi]

        # Write results back to bus objects
        for bus in buses:
            bus.v_pu = V[idx[bus.id]]

        return PowerFlowResult(converged, iterations, net)

    def compute_instrument_transformers(
        self,
        cts: list[CT],
        vts: list[VT],
    ) -> None:
        """Populate secondary quantities on all CTs and VTs after a solve."""
        net = self.network

        for vt in vts:
            bus = net.get_bus(vt.bus_id)
            if bus is None:
                continue
            Va, Vb, Vc = balanced_voltages(abs(bus.v_volts), math.degrees(cmath.phase(bus.v_pu)))
            primary = ThreePhaseQuantity(a=Va, b=Vb, c=Vc)
            vt.secondary_voltage = vt.apply_primary(primary)

        for ct in cts:
            branch = net.branches.get(ct.branch_id)
            if branch is None or not branch.closed:
                ct.secondary_current = ThreePhaseQuantity(0j, 0j, 0j)
                continue

            from_bus = net.get_bus(branch.from_bus)
            to_bus = net.get_bus(branch.to_bus)
            if from_bus is None or to_bus is None:
                continue

            # For phase-shifted branches (Yd/Dy transformers) the HV-side current
            # is I = y*(V_HV - a*V_LV) where a = e^(jφ), matching the Y-bus model.
            phi = getattr(branch, "phase_shift_rad", 0.0)
            if abs(phi) > 1e-9:
                a = cmath.rect(1.0, phi)
                dV = from_bus.v_pu - a * to_bus.v_pu
            else:
                dV = from_bus.v_pu - to_bus.v_pu
            if abs(branch.z_pu) < 1e-12:
                i_pu = 0.0 + 0.0j
            else:
                i_pu = dV / branch.z_pu

            # Convert from per-unit to amps on the from_bus (HV) side base
            base_kv = from_bus.base_kv
            base_i = (net.base_mva * 1e6) / (base_kv * 1e3 * 3 ** 0.5)
            i_mag = abs(i_pu) * base_i
            i_ang = cmath.phase(i_pu)

            Ia, Ib, Ic = (
                cmath.rect(i_mag, i_ang + offset)
                for offset in (0.0, -2 * math.pi / 3, 2 * math.pi / 3)
            )
            primary = ThreePhaseQuantity(a=Ia, b=Ib, c=Ic)
            ct.secondary_current = ct.apply_primary(primary)
