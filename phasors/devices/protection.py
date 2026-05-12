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
from .protection_elements import build_elements_from_settings
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
        self._input_windings = {}  # source_name → winding number (1 or 2, for DualWindingVT)
        self.secondary_connections = [] # Analog Outputs
        
        self.dc_input_conns = [] 
        self.dc_output_conns = []
        
        self._evaluating_prot_current = False
        self._evaluating_prot_voltage = False
        self._evaluating_dc = False

    def add_input(self, source_device, winding=1):
        if source_device not in self.inputs:
            self.inputs.append(source_device)
        self._input_windings[source_device.name] = winding
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
                winding = self._input_windings.get(src.name, 1)
                if winding == 2:
                    v_sys = getattr(src, "secondary2_voltage", None)
                else:
                    v_sys = getattr(src, "secondary_voltage", None)
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
        self._elem_prev_time = None
        self.elements = {e.bit_name: e for e in build_elements_from_settings(self.settings)}

    def get_logic_bits(self):
        if "logic_bits" in self._cache: return self._cache["logic_bits"]
        bits = {}
        i, v = self.current, self.voltage
        if not getattr(self, "is_sim", False):
            # Non-sim: step elements with dt=0 for live instantaneous values (50/59)
            for elem in self.elements.values():
                elem.step(i, v, 0.0)
        for elem in self.elements.values():
            bits[elem.bit_name] = elem.get_bit()
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

        dt_ms = 0.0 if self._elem_prev_time is None else min(sim_time_ms - self._elem_prev_time, 200.0)
        self._elem_prev_time = sim_time_ms

        i_sys, v_sys = self.current, self.voltage
        events = list(fault_events)
        for elem in self.elements.values():
            for e in elem.step(i_sys, v_sys, dt_ms):
                e["data"]["device_id"] = self.name
                events.append(e)

        logic_bits = self.get_logic_bits()
        for label, eq in self.logic.items():
            raw_state = self._evaluate_equation(eq, logic_bits)
            pickup_delay = float(self.settings.get(f"{label}_DELAY", 0.0))
            reset_delay  = float(self.settings.get(f"{label}_RESET_DELAY", 0.0))

            if pickup_delay <= 0 and reset_delay <= 0:
                self._sim_active_outputs[label] = raw_state
                continue

            if raw_state:
                if label in self._sim_dropout_timers:
                    del self._sim_dropout_timers[label]
                if pickup_delay > 0:
                    if label not in self._sim_pickup_timers:
                        self._sim_pickup_timers[label] = sim_time_ms
                    if sim_time_ms - self._sim_pickup_timers[label] >= pickup_delay and not self._sim_active_outputs.get(label):
                        self._sim_active_outputs[label] = True
                        events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {"device_id": self.name, "label": label}})
                elif not self._sim_active_outputs.get(label):
                    self._sim_active_outputs[label] = True
                    events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {"device_id": self.name, "label": label}})
            else:
                if label in self._sim_pickup_timers:
                    del self._sim_pickup_timers[label]
                if self._sim_active_outputs.get(label):
                    if reset_delay > 0:
                        if label not in self._sim_dropout_timers:
                            self._sim_dropout_timers[label] = sim_time_ms
                        if sim_time_ms - self._sim_dropout_timers[label] >= reset_delay:
                            del self._sim_dropout_timers[label]
                            self._sim_active_outputs[label] = False
                            events.append({"type": "RELAY_DROPOUT", "delay": 0, "data": {"device_id": self.name, "label": label}})
                    else:
                        self._sim_active_outputs[label] = False
                        events.append({"type": "RELAY_DROPOUT", "delay": 0, "data": {"device_id": self.name, "label": label}})

        self._process_ar(sim_time_ms, events)
        self._process_bf(sim_time_ms, i_sys, events)
        return events

    def _process_ar(self, sim_time_ms: float, events: list):
        """Auto-reclose state machine.

        Settings
        --------
        AR_SHOTS      : int   — number of reclose attempts (0 = disabled, default 0)
        AR_DELAY1_MS  : float — delay before shot 1 (ms, default 500)
        AR_DELAY2_MS  : float — delay before shot 2 (ms, default 5000)
        AR_DELAY{N}_MS: float — delay before shot N
        AR_HOLD_MS    : float — hold time to confirm successful reclose (ms, default 3000)

        States: IDLE → ARMED → RECLOSING → HOLDING → (IDLE | ARMED | LOCKOUT)
        """
        ar_shots = int(float(self.settings.get("AR_SHOTS", 0)))
        if ar_shots <= 0:
            return

        if not hasattr(self, "_ar_state"):
            self._ar_state     = "IDLE"
            self._ar_shot_count = 0
            self._ar_timer     = None
            self._ar_locked_out = False

        if self._ar_locked_out:
            return

        trip_active = self._sim_active_outputs.get("TRIP", False)

        if self._ar_state == "IDLE":
            if trip_active:
                self._ar_state = "ARMED"

        elif self._ar_state == "ARMED":
            if not trip_active:
                # TRIP dropped — CB has opened and fault current collapsed
                delay_key = f"AR_DELAY{self._ar_shot_count + 1}_MS"
                delay_ms  = float(self.settings.get(delay_key, self.settings.get("AR_DELAY1_MS", 500.0)))
                self._ar_timer = sim_time_ms + delay_ms
                self._ar_state = "RECLOSING"

        elif self._ar_state == "RECLOSING":
            if sim_time_ms >= self._ar_timer:
                self._ar_shot_count += 1
                hold_ms = float(self.settings.get("AR_HOLD_MS", 3000.0))
                self._ar_timer = sim_time_ms + hold_ms
                self._ar_state = "HOLDING"
                # Send CLOSE command to all connected switches / CBs
                for conn in self.dc_output_conns:
                    dev = conn["device"]
                    if hasattr(dev, "handle_close_signal"):
                        events.append({"type": "CLOSE", "delay": 0, "data": {"device_id": dev.name, "phase": "abc"}})
                events.append({"type": "AR_RECLOSE", "delay": 0, "data": {
                    "device_id": self.name,
                    "shot": self._ar_shot_count,
                    "of":   ar_shots,
                }})

        elif self._ar_state == "HOLDING":
            if trip_active:
                # Reclose failed — fault is persistent
                if self._ar_shot_count >= ar_shots:
                    self._ar_locked_out = True
                    self._ar_state = "LOCKOUT"
                    events.append({"type": "AR_LOCKOUT", "delay": 0, "data": {"device_id": self.name}})
                else:
                    # More shots available — wait for TRIP to drop again
                    self._ar_state = "ARMED"
            elif sim_time_ms >= self._ar_timer:
                # CB stayed closed through the hold window — successful reclose
                self._ar_state      = "IDLE"
                self._ar_shot_count = 0
                self._ar_timer      = None

        elif self._ar_state == "LOCKOUT":
            self._ar_locked_out = True

    def _process_bf(self, sim_time_ms: float, i_sys, events: list):
        """Breaker-failure (50BF) backup trip logic.

        Settings
        --------
        BF_DELAY_MS          : float — BF initiate timer in ms (0 = disabled, typical 150-250)
        BF_CURRENT_THRESHOLD : float — min secondary current confirming CB has not opened (A, default 0.1)

        When TRIP is asserted and current remains above threshold after BF_DELAY_MS,
        the BF output asserts.  Any switch/CB connected to this relay's BF dc_output_conn
        receives an imperative TRIP command via the event queue.
        """
        bf_delay = float(self.settings.get("BF_DELAY_MS", 0))
        if bf_delay <= 0:
            return

        trip_active = self._sim_active_outputs.get("TRIP", False)
        I = 0.0
        if i_sys and i_sys.is_energized():
            I = max(i_sys.a.magnitude, i_sys.b.magnitude, i_sys.c.magnitude)
        threshold = float(self.settings.get("BF_CURRENT_THRESHOLD", 0.1))

        if not hasattr(self, "_bf_timer"):
            self._bf_timer    = None
            self._bf_operated = False

        if trip_active and I >= threshold:
            if self._bf_timer is None:
                self._bf_timer = sim_time_ms
            if not self._bf_operated and (sim_time_ms - self._bf_timer) >= bf_delay:
                self._bf_operated = True
                self._sim_active_outputs["BF"] = True
                # Trip every switch/CB wired to this relay's BF output
                for conn in self.dc_output_conns:
                    if conn["from"] == "BF" and hasattr(conn["device"], "handle_trip_signal"):
                        events.append({"type": "TRIP", "delay": 0,
                                       "data": {"device_id": conn["device"].name, "phase": "abc"}})
                events.append({"type": "BF_TRIP", "delay": 0, "data": {"device_id": self.name}})
        else:
            self._bf_timer    = None
            self._bf_operated = False
            self._sim_active_outputs["BF"] = False

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

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Category"] = self.category
        stats["--- LOGIC ELEMENTS ---"] = "HEADER"
        for elem in self.elements.values():
            stats.update(elem.get_state())
        bits = self.get_logic_bits()
        for label in self.digital_inputs:
            stats[label] = "ASSERTED" if bits.get(label) else "0"
        stats["--- OUTPUTS ---"] = "HEADER"
        extra_outs = ["TRIP", "CLOSE"]
        if float(self.settings.get("BF_DELAY_MS", 0)) > 0:
            extra_outs.append("BF")
        for out in self.digital_outputs + [o for o in extra_outs if o not in self.digital_outputs]:
            res, man = self.get_terminal_state(out), " (MANUAL)" if self.output_manual_overrides.get(out) else ""
            stats[f"{out}{man}"] = "HIGH" if res else "0"
        if getattr(self, "is_sim", False) and float(self.settings.get("BF_DELAY_MS", 0)) > 0:
            bf_ms = float(self.settings.get("BF_DELAY_MS", 0))
            if getattr(self, "_bf_timer", None) and not getattr(self, "_bf_operated", False):
                elapsed = 0  # sim_time not available here; show configured delay
                stats["BF Timer"] = f"RUNNING ({bf_ms:.0f}ms delay)"
            elif getattr(self, "_bf_operated", False):
                stats["BF Timer"] = "OPERATED — backup trip sent"
            else:
                stats["BF Timer"] = f"Armed ({bf_ms:.0f}ms)"
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
            p = q = 0.0
            for ph in 'abc':
                s_ph = getattr(v, ph).to_complex() * getattr(i, ph).to_complex().conjugate()
                p += s_ph.real
                q += s_ph.imag
            s = math.sqrt(p * p + q * q)
            pf = abs(p / s) if s > 1e-9 else 0.0
            stats["Active Power (P)"]   = f"{p/1e6:.3f} MW"
            stats["Reactive Power (Q)"] = f"{q/1e6:.3f} MVAr"
            stats["Apparent Power (S)"] = f"{s/1e6:.3f} MVA"
            stats["Power Factor"]       = f"{pf:.3f} ({'lag' if q > 0 else 'lead'})"
        return stats

class Indicator(ProtectionDevice):
    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Status"] = "ON (Energized)" if self.dc_status else "OFF"
        return stats
