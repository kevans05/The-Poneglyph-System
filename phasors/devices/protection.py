"""
protection.py — Protection device models.

Hierarchy: ProtectionDevice → CTTB / FTBlock / IsoBlock / Relay / Meter / Indicator

All protection devices share the same analog-signal aggregation logic:
  • current  → vector sum of secondary_current from each analog input
  • voltage  → vector average of secondary_voltage from each analog input
  • input_polarities dict maps input device ID → +1 or -1 (sign applied before summing)

CTTB (CT Terminal Block)
  Sums or differentials N CT secondaries into a single current bus.
  mode = "SUM" (default) or "DIFFERENTIAL".

FTBlock / IsoBlock
  Pass voltage signals through; used for isolation / filtering in the VT analog chain.

Relay
  Has logic bits (50P1, 59P1, digital inputs), evaluates equations defined in
  self.logic dict, and drives digital output terminals.
  Logic expressions are evaluated with a restricted eval() — only AND/OR/NOT and
  the named bits are available (no builtins).

DC chain: protection devices can receive DC input signals (trip coils, status
contacts) via dc_input_conns and drive DC outputs via dc_output_conns.
"""

from .bus import Bus
from ..wye_system import wye_currents, wye_voltages
from ..current_phasor import CurrentPhasor
from ..voltage_phasor import VoltagePhasor
from ..utilities.power_utilities import append_3phase_details
import cmath
import math

class ProtectionDevice(Bus):
    def __init__(self, name: str):
        super().__init__(name)
        self.inputs = [] # Analog Inputs (CT/VT)
        self.input_polarities = {}
        self.secondary_connections = [] # Analog Outputs
        
        self.dc_input_conns = [] 
        self.dc_output_conns = []
        
        self._evaluating_prot_current = False
        self._evaluating_prot_voltage = False
        self._evaluating_dc = False

    def add_input(self, source_device):
        if source_device not in self.inputs:
            self.inputs.append(source_device)
        return self

    def connect_secondary(self, downstream_device):
        if downstream_device not in self.secondary_connections:
            self.secondary_connections.append(downstream_device)
            if hasattr(downstream_device, 'add_input'):
                downstream_device.add_input(self)
        return downstream_device

    def add_dc_input_conn(self, source_device, from_label=None, to_label=None):
        conn = {"device": source_device, "from": from_label, "to": to_label}
        if conn not in self.dc_input_conns:
            self.dc_input_conns.append(conn)
        return self

    def connect_dc(self, downstream_device, from_label=None, to_label=None):
        conn = {"device": downstream_device, "from": from_label, "to": to_label}
        if conn not in self.dc_output_conns:
            self.dc_output_conns.append(conn)
            if hasattr(downstream_device, "add_dc_input_conn"):
                downstream_device.add_dc_input_conn(self, from_label, to_label)
        return downstream_device

    @property
    def dc_status(self) -> bool:
        if "dc_status" in self._cache: return self._cache["dc_status"]
        if getattr(self, '_evaluating_dc', False): return False
        self._evaluating_dc = True
        try:
            res = False
            for conn in self.dc_input_conns:
                if conn["device"].get_terminal_state(conn["from"]):
                    res = True; break
            if not res:
                for src in self.inputs:
                    if getattr(src, "dc_output_state", False) or getattr(src, "dc_status", False):
                        res = True; break
            self._cache["dc_status"] = res
            return res
        finally:
            self._evaluating_dc = False

    def get_terminal_state(self, label=None) -> bool:
        return self.dc_status

    @property
    def current(self):
        """Protection devices ONLY aggregate current from their analog inputs."""
        if "current" in self._cache: return self._cache["current"]
        if getattr(self, '_evaluating_prot_current', False): return wye_currents()
        self._evaluating_prot_current = True
        try:
            total_a, total_b, total_c = complex(0), complex(0), complex(0)
            found = False
            for i, src in enumerate(self.inputs):
                # We specifically check for secondary_current
                i_sys = getattr(src, "secondary_current", None)
                if i_sys and i_sys.is_energized():
                    sign = self.input_polarities.get(src.name, 1)
                    if getattr(self, "mode", None) == "DIFFERENTIAL" and i > 0 and src.name not in self.input_polarities:
                        sign = -1
                    total_a += sign * i_sys.a.to_complex()
                    total_b += sign * i_sys.b.to_complex()
                    total_c += sign * i_sys.c.to_complex()
                    found = True
            
            def from_c(c): mag, ang = cmath.polar(c); return CurrentPhasor(mag, math.degrees(ang))
            res = wye_currents(from_c(total_a), from_c(total_b), from_c(total_c)) if found else wye_currents()
            self._cache["current"] = res; return res
        finally: 
            self._evaluating_prot_current = False

    @property
    def voltage(self):
        """Protection devices ONLY aggregate voltage from their analog inputs."""
        if "voltage" in self._cache: return self._cache["voltage"]
        if getattr(self, '_evaluating_prot_voltage', False): return wye_voltages()
        self._evaluating_prot_voltage = True
        try:
            total_a, total_b, total_c = complex(0), complex(0), complex(0)
            found, count = False, 0
            for src in self.inputs:
                v_sys = getattr(src, "secondary_voltage", None) or getattr(src, "secondary2_voltage", None)
                if v_sys and v_sys.is_energized():
                    sign = self.input_polarities.get(src.name, 1)
                    total_a += sign * v_sys.a.to_complex()
                    total_b += sign * v_sys.b.to_complex()
                    total_c += sign * v_sys.c.to_complex()
                    found = True; count += 1
            
            if found:
                if count > 1: total_a /= count; total_b /= count; total_c /= count
                def from_c(c): mag, ang = cmath.polar(c); return VoltagePhasor(mag, math.degrees(ang))
                res = wye_voltages(from_c(total_a), from_c(total_b), from_c(total_c))
            else:
                res = wye_voltages()
            self._cache["voltage"] = res; return res
        finally: 
            self._evaluating_prot_voltage = False

    @property
    def secondary_current(self): return None # Base protection doesn't have secondary winding
    @property
    def secondary_voltage(self): return None

    def get_summary_dict(self):
        stats = {"Type": self.__class__.__name__, "Inputs": len(self.inputs)}
        return append_3phase_details(stats, self.voltage, self.current)

class CTTB(ProtectionDevice):
    def __init__(self, name: str, mode: str = "SUM", input_polarities: dict = None):
        super().__init__(name)
        self.mode = mode.upper().strip()
        self.input_polarities = input_polarities or {}
    @property
    def secondary_current(self): return self.current

class FTBlock(ProtectionDevice):
    @property
    def secondary_voltage(self): return self.voltage

class IsoBlock(FTBlock): pass

class Relay(ProtectionDevice):
    def __init__(self, name: str, function: str = "Differential", input_polarities: dict = None, category: str = "Numerical",
                 logic: dict = None, settings: dict = None, digital_inputs: list = None, digital_outputs: list = None):
        super().__init__(name)
        self.function, self.input_polarities, self.category = function, input_polarities or {}, category
        self.target_dropped = False
        self.digital_inputs = digital_inputs or ["IN101", "IN102"]
        self.digital_outputs = digital_outputs or ["OUT101", "OUT102"]
        self.settings = settings or {"50P1P": 5.0, "59P1P": 120.0}
        self.logic = logic or {"TRIP": "50P1 OR IN101", "CLOSE": "0", "OUT101": "50P1"}
        self.output_manual_overrides = {}
        self._sim_pickup_timers = {}

    def get_logic_bits(self):
        if "logic_bits" in self._cache: return self._cache["logic_bits"]
        bits = {}
        i, v = self.current, self.voltage
        bits["50P1"] = max(i.a.magnitude, i.b.magnitude, i.c.magnitude) >= float(self.settings.get("50P1P", 5.0)) if i else False
        bits["59P1"] = max(v.a.magnitude, v.b.magnitude, v.c.magnitude) >= float(self.settings.get("59P1P", 120.0)) if v else False
        for label in self.digital_inputs:
            bits[label] = False
            for conn in self.dc_input_conns:
                if conn["to"] == label:
                    if conn["device"].get_terminal_state(conn["from"]): bits[label] = True; break
        self._cache["logic_bits"] = bits; return bits

    def get_terminal_state(self, label=None) -> bool:
        if not label or label == "DC_OUT": label = "TRIP"
        cache_key = f"term_{label}"
        if cache_key in self._cache: return self._cache[cache_key]
        if self.output_manual_overrides.get(label, False): return True
        if getattr(self, "is_sim", False) and label in getattr(self, "_sim_active_outputs", {}): return self._sim_active_outputs[label]
        if getattr(self, '_evaluating_dc', False): return False
        self._evaluating_dc = True
        try:
            eq = self.logic.get(label, "0")
            res = self._evaluate_equation(eq, self.get_logic_bits())
            self._cache[cache_key] = res; return res
        finally: self._evaluating_dc = False

    def sim_step(self, sim_time_ms):
        fault_events = self._sim_step_fault(sim_time_ms)
        if not getattr(self, "is_sim", False): return []
        if not hasattr(self, "_sim_active_outputs"): self._sim_active_outputs = {}
        events, logic_bits = fault_events, self.get_logic_bits()
        for label, eq in self.logic.items():
            raw_state = self._evaluate_equation(eq, logic_bits)
            delay = float(self.settings.get(f"{label}_DELAY", 0.0))
            if delay <= 0: self._sim_active_outputs[label] = raw_state; continue
            if raw_state:
                if label not in self._sim_pickup_timers: self._sim_pickup_timers[label] = sim_time_ms
                if sim_time_ms - self._sim_pickup_timers[label] >= delay and not self._sim_active_outputs.get(label):
                    self._sim_active_outputs[label] = True
                    events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {"device_id": self.name, "label": label}})
            else:
                if label in self._sim_pickup_timers: del self._sim_pickup_timers[label]
                if self._sim_active_outputs.get(label):
                    self._sim_active_outputs[label] = False
                    events.append({"type": "RELAY_DROPOUT", "delay": 0, "data": {"device_id": self.name, "label": label}})
        return events

    @property
    def dc_output_state(self) -> bool: return self.get_terminal_state("TRIP")

    @dc_output_state.setter
    def dc_output_state(self, value): self.output_manual_overrides["TRIP"] = value

    def _evaluate_equation(self, eq, bits):
        if eq == "0": return False
        if eq == "1": return True
        try:
            safe_eq = eq.replace("OR", " or ").replace("AND", " and ").replace("NOT", " not ")
            return eval(safe_eq, {"__builtins__": None}, bits)
        except: return False

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Category"] = self.category
        bits = self.get_logic_bits()
        stats["--- LOGIC ELEMENTS ---"] = "HEADER"
        for b, val in bits.items(): stats[b] = "ASSERTED" if val else "0"
        stats["--- OUTPUTS ---"] = "HEADER"
        for out in self.digital_outputs + ([o for o in ["TRIP", "CLOSE"] if o not in self.digital_outputs]):
            res, man = self.get_terminal_state(out), " (MANUAL)" if self.output_manual_overrides.get(out) else ""
            stats[f"{out}{man}"] = "HIGH" if res else "0"
        if self.category == "Electromechanical": stats["Target / Flag"] = "DROPPED" if self.target_dropped else "SET" 
        return stats

class AuxiliaryTransformer(ProtectionDevice):
    def __init__(self, name: str, phase_shift_deg: float = 0.0, ratio: float = 1.0):
        super().__init__(name)
        self.phase_shift_deg, self.ratio = phase_shift_deg, ratio
    def _apply(self, system):
        if not system or not system.is_energized(): return system
        rotation = cmath.rect(1, math.radians(self.phase_shift_deg))
        def p(ph):
            c = (ph.to_complex() * self.ratio) * rotation; m, a = cmath.polar(c)
            return type(ph)(m, math.degrees(a))
        return type(system)(p(system.a), p(system.b), p(system.c))
    @property
    def current(self): return self._apply(super().current)
    @property
    def voltage(self): return self._apply(super().voltage)
    @property
    def secondary_current(self): return self.current
    @property
    def secondary_voltage(self): return self.voltage

class Meter(ProtectionDevice):
    def get_summary_dict(self):
        stats = super().get_summary_dict()
        v, i = self.voltage, self.current
        if v and i and v.is_energized() and i.is_energized():
            p = sum((getattr(v,ph).to_complex() * getattr(i,ph).to_complex().conjugate()).real for ph in 'abc')
            stats["Total Active Power"] = f"{p/1e6:.2f} MW"
        return stats

class Indicator(ProtectionDevice):
    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Status"] = "ON (Energized)" if self.dc_status else "OFF"
        return stats
