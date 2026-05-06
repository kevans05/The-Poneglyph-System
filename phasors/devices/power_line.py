from ..wye_system import wye_voltages, wye_currents
from ..phasor_operations import voltage_current_multiplier
from ..utilities.power_utilities import append_3phase_details 
import math

class PowerLine:
    def __init__(self, name: str):
        self.name = name
        self.upstream_device = None
        self.downstream_device = None
        self._evaluating = False

    @property
    def voltage(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            if self.upstream_device:
                return getattr(self.upstream_device, 'downstream_voltage', getattr(self.upstream_device, 'voltage', None))
            return None
        finally: self._evaluating = False

    @property
    def current(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            if self.upstream_device:
                return getattr(self.upstream_device, 'downstream_current', getattr(self.upstream_device, 'current', None))
            return None
        finally: self._evaluating = False

    @property
    def downstream_voltage(self): return self.voltage
    @property
    def downstream_current(self): return self.current

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

    def connect(self, downstream_device, **kwargs):
        self.downstream_device = downstream_device
        downstream_device.upstream_device = self
        return downstream_device

    def get_summary_dict(self) -> dict:
        is_delta = self.connection_type == "delta"
        stats = {}
        up_name = self.upstream_device.name if self.upstream_device else 'Source'
        down_name = self.downstream_device.name if self.downstream_device else 'End of Line'
        stats['Logical Flow'] = f'{up_name} -> [ {self.name} ] -> {down_name}'
        stats['Connection'] = 'Delta (Δ)' if is_delta else 'Wye (Y)'
        v = self.voltage; i = self.current
        if v: stats['Line Voltage (LL)'] = v.a.magnitude * math.sqrt(3)
        if i and v:
            try:
                sa = voltage_current_multiplier(v.a, i.a)
                sb = voltage_current_multiplier(v.b, i.b)
                sc = voltage_current_multiplier(v.c, i.c)
                s_total = sa.complex_power + sb.complex_power + sc.complex_power
                stats['3-Phase Current'] = i.a.magnitude
                stats['Active Power'] = s_total.real
                stats['Reactive Power'] = s_total.imag
                stats['Apparent Power'] = abs(s_total)
            except: pass
        return append_3phase_details(stats, v, i, is_delta=is_delta)