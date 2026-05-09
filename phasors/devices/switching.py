import math

from ..utilities.formatter import SIPrefix
from ..utilities.power_utilities import append_3phase_details
from ..wye_system import wye_voltages


class Switch:
    def __init__(self, name: str, is_closed: bool = True):
        self.name = name
        self._manual_is_closed = is_closed
        self.trip_dc_inputs = []
        self.close_dc_inputs = []
        self.upstream_device = None
        self.h_connections = []
        self.x_connections = []
        self.sensors = []
        self._evaluating = False

    def open(self):
        self._manual_is_closed = False

    def close(self):
        self._manual_is_closed = True

    def add_trip_dc(self, source_device):
        if source_device not in self.trip_dc_inputs:
            self.trip_dc_inputs.append(source_device)
        return self

    def add_close_dc(self, source_device):
        if source_device not in self.close_dc_inputs:
            self.close_dc_inputs.append(source_device)
        return self

    @property
    def is_tripped_by_dc(self) -> bool:
        """True if any trip coil is energized."""
        for src in self.trip_dc_inputs:
            if getattr(src, "dc_output_state", False): return True
            if hasattr(src, "dc_status") and src.dc_status: return True
        return False

    @property
    def is_closed_by_dc(self) -> bool:
        """True if any close coil is energized."""
        for src in self.close_dc_inputs:
            if getattr(src, "dc_output_state", False): return True
            if hasattr(src, "dc_status") and src.dc_status: return True
        return False

    @property
    def is_closed(self) -> bool:
        # DC Trip (e.g. Lockout) has highest priority
        if self.is_tripped_by_dc:
            return False
        # DC Close pulse/signal
        if self.is_closed_by_dc:
            return True
        return self._manual_is_closed

    @is_closed.setter
    def is_closed(self, value):
        self._manual_is_closed = value

    @property
    def status(self):
        if self.is_tripped_by_dc:
            return "OPEN (Tripped by DC)"
        if self.is_closed_by_dc and not self._manual_is_closed:
            return "CLOSED (Driven by DC)"
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
        if self.is_tripped_by_dc:
            stats["Trip Coil"] = "ENERGIZED"
        if self.is_closed_by_dc:
            stats["Close Coil"] = "ENERGIZED" 
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
