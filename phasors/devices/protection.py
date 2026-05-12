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
import re

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
        self._sim_pickup_timers = {}   # label → sim_time_ms when pickup condition first asserted
        self._sim_dropout_timers = {}  # label → sim_time_ms when pickup condition first cleared
        # 51-series IDMT state (integrating accumulator per element)
        self._51_accumulators = {}  # elem_name → float 0.0–1.0 (1.0 = operated)
        self._51_operated = {}      # elem_name → bool
        self._51_prev_time = None   # sim_time_ms of last _update_51_timers call

    def get_logic_bits(self):
        if "logic_bits" in self._cache: return self._cache["logic_bits"]
        bits = {}
        i, v = self.current, self.voltage
        bits["50P1"] = max(i.a.magnitude, i.b.magnitude, i.c.magnitude) >= float(self.settings.get("50P1P", 5.0)) if i else False
        bits["59P1"] = max(v.a.magnitude, v.b.magnitude, v.c.magnitude) >= float(self.settings.get("59P1P", 120.0)) if v else False
        # 51-series: bit is True only once the IDMT accumulator has reached 1.0 (element operated)
        for elem_name in self._get_51_element_names():
            bits[elem_name] = self._51_operated.get(elem_name, False)
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
        # Update 51-series IDMT integrators before evaluating logic so operated bits are current
        idmt_events = self._update_51_timers(sim_time_ms)
        events, logic_bits = fault_events + idmt_events, self.get_logic_bits()
        for label, eq in self.logic.items():
            raw_state = self._evaluate_equation(eq, logic_bits)
            pickup_delay = float(self.settings.get(f"{label}_DELAY", 0.0))
            reset_delay  = float(self.settings.get(f"{label}_RESET_DELAY", 0.0))

            if pickup_delay <= 0 and reset_delay <= 0:
                # No timing on either edge — instant in both directions (no event needed)
                self._sim_active_outputs[label] = raw_state
                continue

            if raw_state:
                # Condition asserting: cancel any pending dropout
                if label in self._sim_dropout_timers:
                    del self._sim_dropout_timers[label]

                if pickup_delay > 0:
                    if label not in self._sim_pickup_timers:
                        self._sim_pickup_timers[label] = sim_time_ms
                    if sim_time_ms - self._sim_pickup_timers[label] >= pickup_delay and not self._sim_active_outputs.get(label):
                        self._sim_active_outputs[label] = True
                        events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {"device_id": self.name, "label": label}})
                elif not self._sim_active_outputs.get(label):
                    # Has reset delay but no pickup delay — assert immediately
                    self._sim_active_outputs[label] = True
                    events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {"device_id": self.name, "label": label}})
            else:
                # Condition cleared: cancel any pending pickup
                if label in self._sim_pickup_timers:
                    del self._sim_pickup_timers[label]

                if self._sim_active_outputs.get(label):
                    if reset_delay > 0:
                        # Start dropout timer if not already running
                        if label not in self._sim_dropout_timers:
                            self._sim_dropout_timers[label] = sim_time_ms
                        if sim_time_ms - self._sim_dropout_timers[label] >= reset_delay:
                            del self._sim_dropout_timers[label]
                            self._sim_active_outputs[label] = False
                            events.append({"type": "RELAY_DROPOUT", "delay": 0, "data": {"device_id": self.name, "label": label}})
                        # else: output stays asserted while reset delay runs
                    else:
                        # No reset delay — instant dropout
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
            # Standard relay function names (50P1, 59P1, etc.) start with a digit and
            # are not valid Python identifiers — eval raises SyntaxError on them.
            # Mangle any digit-leading names by prefixing "_b_" in both the equation
            # string and the namespace dict. Sort longest-first to avoid partial matches
            # (e.g. 50P1G must be replaced before 50P1).
            mangled_bits = {}
            mangled_eq = eq
            for key in sorted(bits, key=len, reverse=True):
                if key and key[0].isdigit():
                    mkey = f"_b_{key}"
                    mangled_bits[mkey] = bits[key]
                    # \b word-boundary ensures 50P1 inside _b_50P1G is not re-matched
                    mangled_eq = re.sub(r'\b' + re.escape(key) + r'\b', mkey, mangled_eq)
                else:
                    mangled_bits[key] = bits[key]
            safe_eq = mangled_eq.replace("OR", " or ").replace("AND", " and ").replace("NOT", " not ")
            return bool(eval(safe_eq, {"__builtins__": None}, mangled_bits))
        except: return False

    def _get_51_element_names(self):
        """Return list of configured 51-series element names (e.g. '51P1' from setting '51P1P')."""
        names = []
        for key in self.settings:
            if re.match(r'^51[A-Z]\d+P$', key):
                names.append(key[:-1])  # strip trailing 'P' pickup suffix
        return names

    @staticmethod
    def _idmt_time(curve: str, multiple: float, tms: float) -> float:
        """Return operating time in seconds for a given curve, current multiple (I/Ip > 1), and TMS."""
        if multiple <= 1.0:
            return float('inf')
        m = multiple
        # IEC 60255-151
        if curve == 'IEC_SI':    return tms * 0.14     / (m ** 0.02 - 1)
        if curve == 'IEC_VI':    return tms * 13.5     / (m - 1)
        if curve == 'IEC_EI':    return tms * 80.0     / (m ** 2 - 1)
        if curve == 'IEC_LTI':   return tms * 120.0    / (m - 1)
        # IEEE C37.112
        if curve == 'IEEE_MI':   return tms * (0.0515  / (m ** 0.02 - 1) + 0.114)
        if curve == 'IEEE_VI':   return tms * (19.61   / (m ** 2  - 1)   + 0.491)
        if curve == 'IEEE_EI':   return tms * (28.2    / (m ** 2  - 1)   + 0.1217)
        return tms  # definite-time fallback: tms treated as operating time in seconds

    def _update_51_timers(self, sim_time_ms: float) -> list:
        """Advance IDMT integrating accumulators for all configured 51-series elements.
        Returns notification events (RELAY_PICKUP / RELAY_DROPOUT) for operated/reset elements."""
        if self._51_prev_time is None:
            self._51_prev_time = sim_time_ms
            return []
        dt_ms = min(sim_time_ms - self._51_prev_time, 200.0)  # cap to prevent large jumps on resume
        self._51_prev_time = sim_time_ms
        if dt_ms <= 0:
            return []

        events = []
        i_sys = self.current

        for elem_name in self._get_51_element_names():
            pickup  = float(self.settings.get(f'{elem_name}P', 0.0))
            tms     = float(self.settings.get(f'{elem_name}TMS', self.settings.get(f'{elem_name}TDS', 1.0)))
            curve   = self.settings.get(f'{elem_name}CURVE', 'IEC_SI')

            # Determine measured current for this element type
            etype = elem_name[2] if len(elem_name) > 2 else 'P'  # 'P', 'N', 'G', 'Q', etc.
            if etype in ('N', 'G') and i_sys and i_sys.is_energized():
                # Residual current: |Ia + Ib + Ic|
                I = abs(i_sys.a.to_complex() + i_sys.b.to_complex() + i_sys.c.to_complex())
            elif i_sys and i_sys.is_energized():
                I = max(i_sys.a.magnitude, i_sys.b.magnitude, i_sys.c.magnitude)
            else:
                I = 0.0

            multiple = (I / pickup) if pickup > 0 else 0.0
            acc      = self._51_accumulators.get(elem_name, 0.0)
            operated = self._51_operated.get(elem_name, False)

            if multiple > 1.0:
                t_op_s = self._idmt_time(curve, multiple, tms)
                if t_op_s != float('inf') and t_op_s > 0:
                    acc = min(1.0, acc + dt_ms / (t_op_s * 1000.0))
                if acc >= 1.0 and not operated:
                    self._51_operated[elem_name] = True
                    events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {
                        "device_id": self.name, "label": elem_name,
                        "multiple": round(multiple, 2),
                        "curve": curve,
                        "t_op_s": round(t_op_s, 3) if t_op_s != float('inf') else None,
                    }})
            elif multiple <= 0.9:
                # Below reset threshold — instantaneous reset
                acc = 0.0
                if operated:
                    self._51_operated[elem_name] = False
                    events.append({"type": "RELAY_DROPOUT", "delay": 0, "data": {
                        "device_id": self.name, "label": elem_name
                    }})

            self._51_accumulators[elem_name] = acc

        return events

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Category"] = self.category
        bits = self.get_logic_bits()
        stats["--- LOGIC ELEMENTS ---"] = "HEADER"
        for b, val in bits.items(): stats[b] = "ASSERTED" if val else "0"
        # Show 51-series accumulator progress
        for elem_name in self._get_51_element_names():
            acc = self._51_accumulators.get(elem_name, 0.0)
            operated = self._51_operated.get(elem_name, False)
            pickup   = self.settings.get(f'{elem_name}P', '?')
            tms      = self.settings.get(f'{elem_name}TMS', self.settings.get(f'{elem_name}TDS', '?'))
            curve    = self.settings.get(f'{elem_name}CURVE', 'IEC_SI')
            status   = "OPERATED" if operated else f"{acc * 100:.0f}% charged"
            stats[f"51 {elem_name}"] = f"{status} | P={pickup}A TMS={tms} {curve}"
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
