import math

from ..phasor_operations import voltage_current_multiplier
from ..utilities.power_utilities import append_3phase_details
from ..wye_system import wye_currents, wye_voltages


class Bus:
    def __init__(self, name: str, nominal_voltage=None, nominal_current=None):
        self._cache = {}
        self.name = name
        self._voltage = nominal_voltage
        self._current = nominal_current
        self.upstream_device = None
        self.connections = []
        self.h_connections = []
        self.x_connections = []
        self._evaluating = False

    @property
    def voltage(self):
        if "voltage" in self._cache: return self._cache["voltage"]
        if self._voltage: return self._voltage
        if self._evaluating: return None
        self._evaluating = True
        try:
            res = None
            if self.upstream_device:
                res = getattr(self.upstream_device, "downstream_voltage", getattr(self.upstream_device, "voltage", None))
            self._cache["voltage"] = res
            return res
        finally: self._evaluating = False

    @property
    def current(self):
        if "current" in self._cache: return self._cache["current"]
        if self._current: return self._current
        if self._evaluating: return None
        self._evaluating = True
        try:
            res = None
            if self.upstream_device:
                res = getattr(self.upstream_device, "downstream_current", getattr(self.upstream_device, "current", None))
            self._cache["current"] = res
            return res
        finally: self._evaluating = False

    @property
    def downstream_voltage(self):
        return self.voltage

    @property
    def downstream_current(self):
        return self.current

    @property
    def connection_type(self) -> str:
        if self._evaluating:
            return "wye"
        self._evaluating = True
        try:
            if self.upstream_device:
                return getattr(
                    self.upstream_device,
                    "downstream_connection_type",
                    getattr(self.upstream_device, "connection_type", "wye"),
                )
            return "wye"
        finally:
            self._evaluating = False

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    def connect(self, downstream_device, to_bushing=None, **kwargs):
        if downstream_device not in self.connections:
            self.connections.append(downstream_device)

        # Avoid setting upstream_device if it creates a cycle?
        # For now, just set it and let _evaluating handle it.
        downstream_device.upstream_device = self
        return downstream_device

    def get_summary_dict(self):
        stats = {"Type": "Bus", "Connections": len(self.connections)}
        return append_3phase_details(stats, self.voltage, self.current)
