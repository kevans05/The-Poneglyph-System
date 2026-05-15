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
    """
    Static VAR Compensator.

    Fixed-Q mode (v_setpoint_kv == 0): injects mvar_setting into the network.
    Voltage-control mode (v_setpoint_kv > 0): treated as a PV bus by the
    nodal solver; Q floats within [mvar_min, mvar_max] to hold terminal voltage.
    """
    def __init__(self, name: str, mvar_min: float = -50.0, mvar_max: float = 50.0,
                 mvar_setting: float = 0.0, kv_rating: float = 115.0,
                 v_setpoint_kv: float = 0.0):
        super().__init__(name, load_va=abs(mvar_setting) * 1e6, power_factor=0.0, is_balanced=True)
        self.mvar_min      = mvar_min
        self.mvar_max      = mvar_max
        self.mvar_setting  = mvar_setting
        self.kv_rating     = kv_rating
        self.v_setpoint_kv = float(v_setpoint_kv)
        # Reactive output when in voltage-control mode (written by solver).
        self.q_mvar_solved = mvar_setting

    def get_phase_pq(self):
        q = self.q_mvar_solved * 1e6 / 3
        return {"a": (0.0, -q), "b": (0.0, -q), "c": (0.0, -q)}

    def get_summary_dict(self) -> dict:
        mode = "Capacitive" if self.mvar_setting > 0 else "Inductive" if self.mvar_setting < 0 else "Off (Bypass)"
        stats = {
            "Type": "Static VAR Compensator",
            "MVAr Range": f"{self.mvar_min:.0f} to +{self.mvar_max:.0f} Mvar",
            "Current Setting": f"{self.mvar_setting:+.2f} Mvar ({mode})",
            "Rated kV": self.kv_rating,
        }
        if self.v_setpoint_kv > 0:
            stats["V Control"] = f"{self.v_setpoint_kv:.3f} kV  (Q={self.q_mvar_solved:+.2f} Mvar solved)"
        if not self.voltage: stats["Status"] = "DEAD (Disconnected)"
        return append_3phase_details(stats, self.voltage, self.current)


class Generator(Bus):
    """
    Synchronous generator — PV bus.

    Holds terminal voltage at v_setpoint_kv (line-to-neutral) while
    injecting p_mw real power.  Reactive output floats within
    [q_min_mvar, q_max_mvar]; when a limit is hit the bus converts to PQ.

    JSON fields: p_mw, v_setpoint_kv, q_min_mvar, q_max_mvar.
    """

    def __init__(self, name: str, p_mw: float = 0.0,
                 v_setpoint_kv: float = 0.0,
                 q_min_mvar: float = -9999.0,
                 q_max_mvar: float = 9999.0):
        super().__init__(name)
        self.p_mw          = float(p_mw)
        self.v_setpoint_kv = float(v_setpoint_kv)   # L-N kV
        self.q_min_mvar    = float(q_min_mvar)
        self.q_max_mvar    = float(q_max_mvar)
        # Reactive output solved by the Y-bus; exposed for monitoring.
        self.q_mvar_solved = 0.0

    def get_phase_pq(self):
        """Per-phase PQ seen from the network (generation = negative load)."""
        p3 = self.p_mw * 1e6
        q3 = self.q_mvar_solved * 1e6
        return {
            "a": (-p3 / 3, -q3 / 3),
            "b": (-p3 / 3, -q3 / 3),
            "c": (-p3 / 3, -q3 / 3),
        }

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Generator (PV bus)",
            "P scheduled": f"{self.p_mw:.2f} MW",
            "V setpoint": f"{self.v_setpoint_kv:.3f} kV (L-N)",
            "Q limits": f"{self.q_min_mvar:.0f} … {self.q_max_mvar:.0f} Mvar",
            "Q solved": f"{self.q_mvar_solved:.2f} Mvar",
        }
        if not self.voltage:
            stats["Status"] = "DEAD (Disconnected)"
        return append_3phase_details(stats, self.voltage, self.current)
