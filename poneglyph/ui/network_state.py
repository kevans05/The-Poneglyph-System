"""NetworkState — bridges the diagram's visual model to the simulation Network.

The diagram tracks visual elements (DiagramBus, DiagramConnection).
The simulation uses Network (Bus, Branch). This module converts between them.
Populated after a power flow solve to feed predicted values back to the diagram.
"""

from __future__ import annotations

from poneglyph.simulation.network import Branch, Bus, Network
from poneglyph.ui.diagram import DiagramBus, DiagramConnection


def build_network(
    buses: dict[str, DiagramBus],
    connections: dict[str, DiagramConnection],
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

    return net
