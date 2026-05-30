"""Instrument transformer models (CT and VT).

These define measurement points in the network — the solver populates
their secondary quantities after each power-flow solution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from poneglyph.simulation.phasors import ThreePhaseQuantity


@dataclass
class CT:
    """Current transformer on a branch."""
    id: str
    name: str
    branch_id: str          # Branch it monitors
    ratio: float            # Primary:secondary (e.g. 400 for 400:1)
    polarity_reversed: bool = False

    # Solved secondary current (populated after power flow)
    secondary_current: Optional[ThreePhaseQuantity] = field(default=None, repr=False)

    def apply_primary(self, primary: ThreePhaseQuantity) -> ThreePhaseQuantity:
        scale = -1.0 / self.ratio if self.polarity_reversed else 1.0 / self.ratio
        return ThreePhaseQuantity(
            a=primary.a * scale,
            b=primary.b * scale,
            c=primary.c * scale,
        )


@dataclass
class VT:
    """Voltage transformer on a bus."""
    id: str
    name: str
    bus_id: str             # Bus it monitors
    ratio: float            # Primary:secondary (e.g. 1000 for 11kV / 11V secondary banks)
    connection: str = "WYE"  # "WYE" or "DELTA"

    # Solved secondary voltage (populated after power flow)
    secondary_voltage: Optional[ThreePhaseQuantity] = field(default=None, repr=False)

    def apply_primary(self, primary: ThreePhaseQuantity) -> ThreePhaseQuantity:
        scale = 1.0 / self.ratio
        return ThreePhaseQuantity(
            a=primary.a * scale,
            b=primary.b * scale,
            c=primary.c * scale,
        )
