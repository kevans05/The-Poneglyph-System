"""Network topology model.

A Network is a graph of Buses connected by Branches.
Devices (transformers, breakers, CTs, VTs) sit on buses or along branches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Bus:
    """A voltage node in the network."""
    id: str
    name: str
    base_kv: float
    # Solved quantities (populated by the power-flow solver)
    v_pu: complex = complex(1.0, 0.0)  # per-unit voltage phasor

    @property
    def v_volts(self) -> complex:
        """Line-to-neutral voltage in volts."""
        return self.v_pu * (self.base_kv * 1000 / (3 ** 0.5))


@dataclass
class Branch:
    """An impedance path between two buses (line, transformer winding, etc.)."""
    id: str
    name: str
    from_bus: str   # Bus id
    to_bus: str     # Bus id
    r_pu: float     # Resistance in per-unit
    x_pu: float     # Reactance in per-unit
    closed: bool = True  # False when an in-series breaker is open

    @property
    def z_pu(self) -> complex:
        return complex(self.r_pu, self.x_pu)


@dataclass
class Network:
    """Complete network topology."""
    name: str
    base_mva: float = 100.0
    buses: dict[str, Bus] = field(default_factory=dict)
    branches: dict[str, Branch] = field(default_factory=dict)

    def add_bus(self, bus: Bus) -> None:
        self.buses[bus.id] = bus

    def add_branch(self, branch: Branch) -> None:
        self.branches[branch.id] = branch

    def get_bus(self, bus_id: str) -> Optional[Bus]:
        return self.buses.get(bus_id)

    def connected_branches(self, bus_id: str) -> list[Branch]:
        return [
            b for b in self.branches.values()
            if b.closed and (b.from_bus == bus_id or b.to_bus == bus_id)
        ]
