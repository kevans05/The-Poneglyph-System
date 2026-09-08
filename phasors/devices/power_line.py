from .bus import Bus
from ..wye_system import wye_voltages, wye_currents
from ..phasor_operations import voltage_current_multiplier
from ..utilities.power_utilities import append_3phase_details 
import math

class PowerLine(Bus):
    def __init__(self, name: str, length_km: float = 0.0, r_per_km: float = 0.0, x_per_km: float = 0.0,
                 r0_per_km: float = None, x0_per_km: float = None):
        super().__init__(name)
        self._cache = {}
        self.name = name
        self.length_km = length_km
        self.r_per_km = r_per_km
        self.x_per_km = x_per_km
        # Zero-sequence impedance defaults to 3× positive-sequence (typical overhead line)
        self.r0_per_km = r0_per_km if r0_per_km is not None else r_per_km * 3.0
        self.x0_per_km = x0_per_km if x0_per_km is not None else x_per_km * 3.0
        self.upstream_device = None
        self.downstream_device = None
        

    @property
    def voltage(self):
        if 'voltage' in self._cache: return self._cache['voltage']
        if self._evaluating_v: return None
        self._evaluating_v = True
        try:
            res = None
            if self.upstream_device:
                res = getattr(self.upstream_device, 'downstream_voltage', getattr(self.upstream_device, 'voltage', None))
            self._cache['voltage'] = res
            return res
        finally: self._evaluating_v = False

    @property
    def downstream_voltage(self): return self.voltage
    

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(
                self.upstream_device, 'downstream_connection_type',
                getattr(self.upstream_device, 'connection_type', 'wye'),
            )
        return 'wye'

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    def connect(self, downstream_device, **kwargs):
        self.downstream_device = downstream_device
        downstream_device.upstream_device = self
        return downstream_device

    

    

    def get_summary_dict(self) -> dict:
        is_delta = self.connection_type == 'delta'
        stats = {
            'Type': 'Line',
            'Length (km)': self.length_km,
            'R (Ω/km)': self.r_per_km,
            'X (Ω/km)': self.x_per_km
        }
        up_name = self.upstream_device.name if self.upstream_device else 'Source'
        down_name = self.downstream_device.name if self.downstream_device else 'End of Line'
        stats['Logical Flow'] = f'{up_name} -> [ {self.name} ] -> {down_name}'
        stats['Connection'] = 'Delta (Δ)' if is_delta else 'Wye (Y)'
        return append_3phase_details(stats, self.voltage, self.current, is_delta=is_delta)
