import math
from ..current_phasor import CurrentPhasor
from ..utilities.power_utilities import append_3phase_details
from ..wye_system import wye_currents, wye_voltages
from .bus import Bus

class VoltageSource(Bus):
    """A specialized Bus that acts as an infinite voltage source."""
    def __init__(
        self,
        name: str,
        nominal_voltage: wye_voltages,
        nominal_current: wye_currents = None,
        winding_type: str = "Y",
        phase_shift_deg: float = 0.0,
    ):
        super().__init__(
            name, nominal_voltage=nominal_voltage, nominal_current=nominal_current
        )
        self.winding_type = winding_type.upper()
        self.phase_shift_deg = phase_shift_deg

    @property
    def downstream_connection_type(self) -> str:
        return "delta" if self.winding_type == "D" else "wye"

    def get_summary_dict(self) -> dict:
        stats = super().get_summary_dict()
        stats["Type"] = "Infinite Voltage Source"
        winding_label = {
            "Y": "Wye (Y)", "YG": "Wye Grounded (YG)", "D": "Delta (Δ)"
        }.get(self.winding_type, self.winding_type)
        stats["Winding"] = winding_label
        stats["Phase Shift"] = f"{self.phase_shift_deg:.1f}°"
        if not self.current:
            stats["Status"] = "OPEN CIRCUIT (No Load)"
        return stats

class Load(Bus):
    """A device that consumes power. Supports balanced and unbalanced configurations."""
    def __init__(self, name: str, load_va: float = 0, power_factor: float = 1.0, is_balanced: bool = True):
        self._cache = {}
        super().__init__(name)
        self.load_va = load_va
        self.power_factor = power_factor
        self.is_balanced = is_balanced
        
        # Per-phase overrides (used if not is_balanced)
        self.phase_va = {"a": load_va / 3, "b": load_va / 3, "c": load_va / 3}
        self.phase_pf = {"a": power_factor, "b": power_factor, "c": power_factor}

    def get_total_pq(self):
        """Returns (P_total, Q_total) in Watts and Vars."""
        pq = self.get_phase_pq()
        return sum(v[0] for v in pq.values()), sum(v[1] for v in pq.values())

    def get_phase_pq(self):
        """Returns {"a": (P_a, Q_a), "b": ..., "c": ...} in Watts and Vars."""
        result = {}
        if self.is_balanced:
            phi = math.acos(max(0.0, min(1.0, self.power_factor)))
            p_phase = self.load_va * self.power_factor / 3
            q_phase = self.load_va * math.sin(phi) / 3
            for ph in ("a", "b", "c"):
                result[ph] = (p_phase, q_phase)
        else:
            for ph in ("a", "b", "c"):
                pf = self.phase_pf[ph]
                phi = math.acos(max(0.0, min(1.0, pf)))
                result[ph] = (self.phase_va[ph] * pf, self.phase_va[ph] * math.sin(phi))
        return result

    def get_summary_dict(self) -> dict:
        p, q = self.get_total_pq()
        s = math.sqrt(p**2 + q**2)
        is_delta = self.connection_type == "delta"
        stats = {
            "Type": "Electrical Load",
            "Connection": "Delta (Δ)" if is_delta else "Wye (Y)",
            "Mode": "Balanced" if self.is_balanced else "Independent Phases",
            "Total Active Power": f"{p / 1e6:.2f} MW",
            "Total Reactive Power": f"{q / 1e6:.2f} Mvar",
            "Total Apparent Power": f"{s / 1e6:.2f} MVA",
            "System PF": f"{p/s:.3f}" if s > 0 else "1.000",
        }
        if not self.voltage:
            stats["Status"] = "DEAD (Disconnected)"
        return append_3phase_details(stats, self.voltage, self.current, is_delta=is_delta)

class ShuntCapacitor(Load):
    """Shunt capacitor bank — supplies reactive power (leading current, Q < 0 consumed)."""
    def __init__(self, name: str, mvar_rating: float = 10.0, kv_rating: float = 115.0):
        self._cache = {}
        super().__init__(name, load_va=mvar_rating * 1e6, power_factor=0.0, is_balanced=True)
        self.mvar_rating = mvar_rating
        self.kv_rating = kv_rating

    def get_phase_pq(self):
        q = self.mvar_rating * 1e6 / 3
        return {"a": (0.0, -q), "b": (0.0, -q), "c": (0.0, -q)}

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Shunt Capacitor Bank",
            "Rated MVAr": self.mvar_rating,
            "Rated kV": self.kv_rating,
            "Reactive Output": f"{self.mvar_rating:.2f} Mvar (Capacitive)",
        }
        if not self.voltage: stats["Status"] = "DEAD (Disconnected)"
        return append_3phase_details(stats, self.voltage, self.current)

class ShuntReactor(Load):
    """Shunt reactor — absorbs reactive power (lagging current, Q > 0 consumed)."""
    def __init__(self, name: str, mvar_rating: float = 10.0, kv_rating: float = 115.0):
        self._cache = {}
        super().__init__(name, load_va=mvar_rating * 1e6, power_factor=0.0, is_balanced=True)
        self.mvar_rating = mvar_rating
        self.kv_rating = kv_rating

    def get_phase_pq(self):
        q = self.mvar_rating * 1e6 / 3
        return {"a": (0.0, q), "b": (0.0, q), "c": (0.0, q)}

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Shunt Reactor",
            "Rated MVAr": self.mvar_rating,
            "Rated kV": self.kv_rating,
            "Reactive Absorption": f"{self.mvar_rating:.2f} Mvar (Inductive)",
        }
        if not self.voltage: stats["Status"] = "DEAD (Disconnected)"
        return append_3phase_details(stats, self.voltage, self.current)

class SVC(Load):
    """Static VAR Compensator — variable reactive power compensation."""
    def __init__(self, name: str, mvar_min: float = -50.0, mvar_max: float = 50.0,
                 mvar_setting: float = 0.0, kv_rating: float = 115.0):
        super().__init__(name, load_va=abs(mvar_setting) * 1e6, power_factor=0.0, is_balanced=True)
        self.mvar_min = mvar_min
        self.mvar_max = mvar_max
        self.mvar_setting = mvar_setting
        self.kv_rating = kv_rating

    def get_phase_pq(self):
        q = self.mvar_setting * 1e6 / 3
        return {"a": (0.0, -q), "b": (0.0, -q), "c": (0.0, -q)}

    def get_summary_dict(self) -> dict:
        mode = "Capacitive" if self.mvar_setting > 0 else "Inductive" if self.mvar_setting < 0 else "Off (Bypass)"
        stats = {
            "Type": "Static VAR Compensator",
            "MVAr Range": f"{self.mvar_min:.0f} to +{self.mvar_max:.0f} Mvar",
            "Current Setting": f"{self.mvar_setting:+.2f} Mvar ({mode})",
            "Rated kV": self.kv_rating,
        }
        if not self.voltage: stats["Status"] = "DEAD (Disconnected)"
        return append_3phase_details(stats, self.voltage, self.current)
