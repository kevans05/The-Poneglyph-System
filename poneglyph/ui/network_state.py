"""NetworkState — bridges the diagram's visual model to the simulation Network.

The diagram tracks visual elements (DiagramBus, DiagramConnection,
DiagramTransformer). The simulation uses Network (Bus, Branch). This module
converts between them. Slack/load scheduling lives on the solver and is set up
by the caller from the diagram's sources and loads.
"""

from __future__ import annotations

import math
from typing import Optional

from poneglyph.simulation.network import Branch, Bus, Network
from poneglyph.ui.diagram import DiagramBus, DiagramConnection, DiagramTransformer


def _transformer_phase_shift(xfmr: DiagramTransformer) -> float:
    """Return phase shift in radians for the transformer branch (from_bus = HV).

    Standard ANSI/IEC rules:
      Yy / Dd  → 0°  (same winding type, no shift)
      Yd       → +30°  (HV wye leads LV delta by 30°  — vector group Yd1)
      Dy       → −30°  (LV wye leads HV delta by 30°  — vector group Dy11)
    """
    delta = {"delta"}
    hv_delta = xfmr.hv_winding in delta
    lv_delta = xfmr.lv_winding in delta
    if hv_delta == lv_delta:
        return 0.0
    return math.radians(30.0) if (not hv_delta and lv_delta) else math.radians(-30.0)


def _transformer_rx(xfmr: DiagramTransformer, base_mva: float) -> tuple[float, float]:
    """Return (r_pu, x_pu) on the system base from the transformer's %Z and MVA.

    Falls back to the stored r_pu/x_pu when MVA is unset. Assumes an X/R ratio
    of 10, typical for power transformers, to split the impedance magnitude.
    """
    if xfmr.mva and xfmr.z_pct:
        z_sys = (xfmr.z_pct / 100.0) * (base_mva / xfmr.mva)
        x = z_sys / math.sqrt(1 + (1 / 10) ** 2)   # X/R = 10
        r = x / 10.0
        return r, x
    return xfmr.r_pu, xfmr.x_pu


def build_network(
    buses: dict[str, DiagramBus],
    connections: dict[str, DiagramConnection],
    transformers: Optional[dict[str, DiagramTransformer]] = None,
    base_mva: float = 100.0,
) -> Network:
    """Build a simulation Network from the current diagram elements."""
    net = Network(name="Substation", base_mva=base_mva)

    for db in buses.values():
        net.add_bus(Bus(id=db.id, name=db.name, base_kv=db.kv))

    for dc in connections.values():
        if dc.to_bus is None:
            continue  # feeders with dangling end — skip for now
        net.add_branch(Branch(
            id=dc.id, name=dc.name,
            from_bus=dc.from_bus, to_bus=dc.to_bus,
            r_pu=dc.r_pu, x_pu=dc.x_pu,
            closed=True,
        ))

    for tx in (transformers or {}).values():
        if tx.hv_bus is None or tx.lv_bus is None:
            continue  # transformer not connected across two buses — skip
        if tx.hv_bus not in net.buses or tx.lv_bus not in net.buses:
            continue
        r, x = _transformer_rx(tx, base_mva)
        phi   = _transformer_phase_shift(tx)
        net.add_branch(Branch(
            id=tx.id, name=tx.name,
            from_bus=tx.hv_bus, to_bus=tx.lv_bus,
            r_pu=r, x_pu=x,
            closed=True,
            phase_shift_rad=phi,
        ))

    return net
