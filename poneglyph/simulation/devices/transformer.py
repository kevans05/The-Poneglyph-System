"""Two-winding power transformer model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Transformer:
    """Two-winding transformer represented as a pi-equivalent branch."""
    id: str
    name: str
    hv_bus: str         # High-voltage bus id
    lv_bus: str         # Low-voltage bus id
    mva_rating: float
    hv_kv: float
    lv_kv: float
    r_pu: float         # Resistance in per-unit on transformer base
    x_pu: float         # Leakage reactance in per-unit
    tap: float = 1.0    # Off-nominal tap ratio (1.0 = nominal)

    @property
    def turns_ratio(self) -> float:
        return (self.hv_kv / self.lv_kv) * self.tap
