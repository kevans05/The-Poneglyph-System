"""Central network state shared between the diagram and network editor.

Holds the live Network object, layout positions, and instrument transformers.
Observers register a callback that fires whenever the state is mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from poneglyph.simulation.network import Bus, Branch, Network
from poneglyph.simulation.devices.instrument_transformer import CT, VT
from poneglyph.ui.oneline import BranchLayout, BusLayout


@dataclass
class NetworkState:
    network:         Network
    bus_layouts:     dict[str, BusLayout]    = field(default_factory=dict)
    branch_layouts:  dict[str, BranchLayout] = field(default_factory=dict)
    cts:             dict[str, CT]            = field(default_factory=dict)
    vts:             dict[str, VT]            = field(default_factory=dict)

    _observers: list[Callable[[], None]] = field(default_factory=list, repr=False, compare=False)

    def subscribe(self, cb: Callable[[], None]) -> None:
        self._observers.append(cb)

    def notify(self) -> None:
        for cb in self._observers:
            cb()

    # ── Convenience mutators (all call notify) ────────────────────────────

    def add_bus(self, bus: Bus, x: float = 0, y: float = 0, length: float = 140) -> None:
        self.network.add_bus(bus)
        self.bus_layouts[bus.id] = BusLayout(bus.id, x=x, y=y, length=length)
        self.notify()

    def remove_bus(self, bus_id: str) -> None:
        self.network.buses.pop(bus_id, None)
        self.bus_layouts.pop(bus_id, None)
        # Remove dangling VTs
        for vid in [k for k, v in self.vts.items() if v.bus_id == bus_id]:
            self.vts.pop(vid)
        self.notify()

    def add_branch(self, branch: Branch, layout: BranchLayout | None = None) -> None:
        self.network.add_branch(branch)
        self.branch_layouts[branch.id] = layout or BranchLayout(branch.id)
        self.notify()

    def remove_branch(self, branch_id: str) -> None:
        self.network.branches.pop(branch_id, None)
        self.branch_layouts.pop(branch_id, None)
        # Remove dangling CTs
        for cid in [k for k, v in self.cts.items() if v.branch_id == branch_id]:
            self.cts.pop(cid)
        self.notify()

    def add_ct(self, ct: CT) -> None:
        self.cts[ct.id] = ct
        bl = self.branch_layouts.get(ct.branch_id)
        if bl and ct.id not in bl.ct_ids:
            bl.ct_ids.append(ct.id)
        self.notify()

    def remove_ct(self, ct_id: str) -> None:
        ct = self.cts.pop(ct_id, None)
        if ct:
            bl = self.branch_layouts.get(ct.branch_id)
            if bl and ct_id in bl.ct_ids:
                bl.ct_ids.remove(ct_id)
        self.notify()

    def add_vt(self, vt: VT) -> None:
        self.vts[vt.id] = vt
        self.notify()

    def remove_vt(self, vt_id: str) -> None:
        self.vts.pop(vt_id, None)
        self.notify()


def make_demo_state() -> NetworkState:
    """Return a ready-to-use 3-bus demo network state."""
    net = Network(name="Demo Substation", base_mva=100)

    buses = [
        Bus("BUS-HV", "132kV Bus", base_kv=132),
        Bus("BUS-MV", "33kV Bus",  base_kv=33),
        Bus("BUS-LV", "11kV Bus",  base_kv=11),
    ]
    for b in buses:
        net.add_bus(b)

    branches = [
        Branch("XFMR-1", "132/33kV Tx", "BUS-HV", "BUS-MV", r_pu=0.01, x_pu=0.10),
        Branch("XFMR-2", "33/11kV Tx",  "BUS-MV", "BUS-LV", r_pu=0.01, x_pu=0.08),
    ]
    for br in branches:
        net.add_branch(br)

    state = NetworkState(network=net)

    state.bus_layouts = {
        "BUS-HV": BusLayout("BUS-HV", x=300, y=100, length=200),
        "BUS-MV": BusLayout("BUS-MV", x=300, y=280, length=180),
        "BUS-LV": BusLayout("BUS-LV", x=300, y=440, length=160),
    }
    state.branch_layouts = {
        "XFMR-1": BranchLayout("XFMR-1", is_transformer=True, ct_ids=["CT-HV"]),
        "XFMR-2": BranchLayout("XFMR-2", is_transformer=True, ct_ids=["CT-MV"]),
    }
    state.cts = {
        "CT-HV": CT("CT-HV", "CT1 HV", "XFMR-1", ratio=200),
        "CT-MV": CT("CT-MV", "CT2 MV", "XFMR-2", ratio=100),
    }
    state.vts = {
        "VT-HV": VT("VT-HV", "VT1 HV", "BUS-HV", ratio=1200),
        "VT-LV": VT("VT-LV", "VT2 LV", "BUS-LV", ratio=100),
    }
    return state
