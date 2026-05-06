import math

from ..utilities.formatter import SIPrefix
from ..utilities.power_utilities import append_3phase_details
from ..wye_system import wye_voltages


class Switch:
    def __init__(self, name: str, is_closed: bool = True):
        self.name = name
        self.is_closed = is_closed
        self.upstream_device = None
        self.h_connections = []
        self.x_connections = []
        self.sensors = []
        self._evaluating = False

    def open(self):
        self.is_closed = False

    def close(self):
        self.is_closed = True

    @property
    def status(self):
        return "CLOSED" if self.is_closed else "OPEN"

    @property
    def voltage(self):
        if self._evaluating:
            return None
        self._evaluating = True
        try:
            if self.upstream_device:
                return getattr(
                    self.upstream_device,
                    "downstream_voltage",
                    getattr(self.upstream_device, "voltage", None),
                )
            return None
        finally:
            self._evaluating = False

    @property
    def current(self):
        if self._evaluating or not self.is_closed:
            return None
        self._evaluating = True
        try:
            if self.upstream_device:
                return getattr(
                    self.upstream_device,
                    "downstream_current",
                    getattr(self.upstream_device, "current", None),
                )
            return None
        finally:
            self._evaluating = False

    @property
    def downstream_voltage(self):
        return self.voltage if self.is_closed else None

    @property
    def downstream_current(self):
        return self.current if self.is_closed else None

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(
                self.upstream_device, "downstream_connection_type",
                getattr(self.upstream_device, "connection_type", "wye"),
            )
        return "wye"

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    def connect(self, downstream_device, to_bushing="X", **kwargs):
        b = to_bushing.upper()
        if b == "H" or b == "Y":
            if downstream_device not in self.h_connections:
                self.h_connections.append(downstream_device)
        else:
            if downstream_device not in self.x_connections:
                self.x_connections.append(downstream_device)

        downstream_device.upstream_device = self
        return downstream_device

    def get_summary_dict(self) -> dict:
        is_delta = self.connection_type == "delta"
        stats = {
            "Status": self.status,
            "Connection": "Delta (Δ)" if is_delta else "Wye (Y)",
        }
        v = self.voltage
        i = self.current
        if v:
            stats["Line Voltage (LL)"] = v.a.magnitude * math.sqrt(3)
        if i:
            stats["3-Phase Current"] = i.a.magnitude
        return append_3phase_details(stats, v, i, is_delta=is_delta)


class Disconnect(Switch):
    def __str__(self):
        return f"Disconnect: {self.name:<10} | Status: {self.status}"


class CircuitBreaker(Switch):
    def __init__(
        self,
        name: str,
        continuous_amps: float,
        interrupt_ka: float,
        is_closed: bool = True,
    ):
        super().__init__(name, is_closed)
        self.continuous_amps = continuous_amps
        self.interrupt_ka = interrupt_ka

    def get_summary_dict(self) -> dict:
        stats = super().get_summary_dict()
        stats["Continuous Rating"] = self.continuous_amps
        stats["Interrupt Rating"] = f"{self.interrupt_ka} kA"
        return stats
