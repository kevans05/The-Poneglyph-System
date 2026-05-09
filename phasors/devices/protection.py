from ..wye_system import wye_currents, wye_voltages
from ..current_phasor import CurrentPhasor
from ..voltage_phasor import VoltagePhasor
from ..utilities.power_utilities import append_3phase_details
import cmath
import math

class ProtectionDevice:
    def __init__(self, name: str):
        self.name = name
        self.inputs = []
        self.secondary_connections = []
        self.dc_inputs = []
        self.dc_outputs = []
        self._evaluating = False

    def add_input(self, source_device):
        if source_device not in self.inputs:
            self.inputs.append(source_device)
        return self

    def connect(self, downstream_device, **kwargs):
        if downstream_device not in self.secondary_connections:
            self.secondary_connections.append(downstream_device)
            if hasattr(downstream_device, 'add_input'):
                downstream_device.add_input(self)
        return downstream_device

    def connect_secondary(self, downstream_device):
        return self.connect(downstream_device)

    def add_dc_input(self, source_device):
        if source_device not in self.dc_inputs:
            self.dc_inputs.append(source_device)
        return self

    def connect_dc(self, downstream_device):
        if downstream_device not in self.dc_outputs:
            self.dc_outputs.append(downstream_device)
            if hasattr(downstream_device, "add_dc_input"):
                downstream_device.add_dc_input(self)
        return downstream_device

    @property
    def dc_status(self) -> bool:
        """True if any DC input is active. Recurses through DC paths."""
        if getattr(self, '_evaluating_dc', False): return False
        self._evaluating_dc = True
        try:
            # Check dedicated DC inputs, outputs (bi-directional wire), and standard secondary inputs
            for src in (self.dc_inputs + self.dc_outputs + self.inputs):
                # Check for direct output states (Relays, etc)
                if getattr(src, "dc_output_state", False): return True
                # Recurse if the source is another protection device
                if hasattr(src, "dc_status") and src.dc_status: return True
            return False
        finally:
            self._evaluating_dc = False

    @property
    def current(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False
            for src in self.inputs:
                i_sys = getattr(src, 'secondary_current', None)
                if i_sys:
                    total_a += i_sys.a.to_complex()
                    total_b += i_sys.b.to_complex()
                    total_c += i_sys.c.to_complex()
                    found = True
            if not found: return None
            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return CurrentPhasor(mag, math.degrees(ang_rad))
            return wye_currents(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    @property
    def voltage(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False
            valid_inputs = 0
            for src in self.inputs:
                v_sys = getattr(src, 'secondary_voltage', None)
                if not v_sys:
                    v_sys = getattr(src, 'secondary2_voltage', None)
                if v_sys:
                    total_a += v_sys.a.to_complex()
                    total_b += v_sys.b.to_complex()
                    total_c += v_sys.c.to_complex()
                    found = True
                    valid_inputs += 1
            
            if not found: return None
            
            if valid_inputs > 1:
                total_a /= valid_inputs
                total_b /= valid_inputs
                total_c /= valid_inputs

            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return VoltagePhasor(mag, math.degrees(ang_rad))
            return wye_voltages(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    @property
    def secondary_current(self): return self.current
    
    @property
    def secondary_voltage(self): return self.voltage

    def get_summary_dict(self):
        stats = {"Type": self.__class__.__name__, "Inputs": len(self.inputs)}
        if not self.inputs: stats["Status"] = "No Input Sources"
        return append_3phase_details(stats, self.voltage, self.current)

class CTTB(ProtectionDevice):
    def __init__(self, name: str, mode: str = "SUM", input_polarities: dict = None):
        super().__init__(name)
        self.mode = mode.upper().strip()
        self.input_polarities = input_polarities or {}
        self.dc_output_state = False

    @property
    def current(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False

            for i, src in enumerate(self.inputs):
                i_sys = getattr(src, 'secondary_current', None)
                if i_sys:
                    sign = self.input_polarities.get(src.name, 1)
                    if self.mode == "DIFFERENTIAL" and i > 0 and src.name not in self.input_polarities:
                        sign = -1
                    total_a += sign * i_sys.a.to_complex()
                    total_b += sign * i_sys.b.to_complex()
                    total_c += sign * i_sys.c.to_complex()
                    found = True
            if not found: return None
            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return CurrentPhasor(mag, math.degrees(ang_rad))
            return wye_currents(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Mode"] = self.mode
        if self.input_polarities:
            for src in self.inputs:
                pol = self.input_polarities.get(src.name, 1)
                stats[f"  {src.name} polarity"] = "+" if pol == 1 else "−"
        return stats

class FTBlock(ProtectionDevice):
    pass

class IsoBlock(FTBlock):
    pass

class Relay(ProtectionDevice):
    def __init__(self, name: str, function: str = "Differential", input_polarities: dict = None, category: str = "Numerical"):
        super().__init__(name)
        self.function = function
        self.input_polarities = input_polarities or {}
        self.dc_output_state = False
        self.category = category
        self.target_dropped = False
        
        # SEL-style Programmable Logic
        self.digital_inputs = ["IN101", "IN102"] # List of labels
        self.digital_outputs = ["OUT101", "OUT102"] # List of labels
        self.settings = {
            "50P1P": 5.0,  # Phase Instantaneous Overcurrent Pickup (A)
            "59P1P": 120.0 # Phase Overvoltage Pickup (V)
        }
        self.logic = {
            "OUT101": "50P1 OR IN101",
            "OUT102": "59P1"
        }

    def get_logic_bits(self):
        """Calculates all internal bits (Elements, Inputs) for logic evaluation."""
        bits = {}
        
        # 1. Analog Elements
        i = self.current
        if i:
            max_i = max(i.a.magnitude, i.b.magnitude, i.c.magnitude)
            bits["50P1"] = max_i >= self.settings.get("50P1P", 5.0)
        else:
            bits["50P1"] = False

        v = self.voltage
        if v:
            max_v = max(v.a.magnitude, v.b.magnitude, v.c.magnitude)
            bits["59P1"] = max_v >= self.settings.get("59P1P", 120.0)
        else:
            bits["59P1"] = False

        # 2. Digital Inputs (check connected wires)
        for label in self.digital_inputs:
            # For now, we use a simple check: if any DC source connected to us is active
            # In a more complex model, we'd need a mapping of which wire goes to which terminal.
            # Simplified: IN101 is active if dc_status is true for now, 
            # or eventually we'd parse dc_connections for specific port mappings.
            bits[label] = self.dc_status 

        return bits

    @property
    def dc_output_state(self) -> bool:
        """The primary trip signal. Tripped if ANY logic output is high OR manually tripped."""
        if getattr(self, '_manual_trip', False): return True
        
        bits = self.get_logic_bits()
        for out_label, equation in self.logic.items():
            if self._evaluate_equation(equation, bits):
                return True
        return False

    @dc_output_state.setter
    def dc_output_state(self, value):
        self._manual_trip = value

    def _evaluate_equation(self, eq, bits):
        """Simple boolean expression evaluator (OR, AND, NOT)."""
        try:
            # Sanitize and convert to python boolean logic
            safe_eq = eq.replace("OR", " or ").replace("AND", " and ").replace("NOT", " not ")
            # Evaluate using bits as local variables
            return eval(safe_eq, {"__builtins__": None}, bits)
        except:
            return False

    def get_summary_dict(self):
        i_result = self.current
        v_result = self.voltage
        stats = {"Type": self.__class__.__name__, "Inputs": len(self.inputs)}
        if not self.inputs:
            stats["Status"] = "No Input Sources"
        stats = append_3phase_details(stats, v_result, i_result)
        stats["Function"] = self.function
        stats["Category"] = self.category
        
        bits = self.get_logic_bits()
        stats["--- LOGIC ELEMENTS ---"] = "HEADER"
        for b, val in bits.items():
            stats[b] = "ASSERTED" if val else "0"
            
        stats["--- OUTPUTS ---"] = "HEADER"
        for out, eq in self.logic.items():
            res = self._evaluate_equation(eq, bits)
            stats[f"{out} ({eq})"] = "HIGH" if res else "0"

        stats["DC Output"] = "HIGH (Tripped)" if self.dc_output_state else "LOW (Normal)"
        if self.category == "Electromechanical":
            stats["Target / Flag"] = "DROPPED" if self.target_dropped else "SET (Normal)" 

        return stats

class AuxiliaryTransformer(ProtectionDevice):
    def __init__(self, name: str, phase_shift_deg: float = 0.0, ratio: float = 1.0):
        super().__init__(name)
        self.phase_shift_deg = phase_shift_deg
        self.ratio = ratio

    def _apply_shift(self, system):
        if not system: return None
        rotation = cmath.rect(1, math.radians(self.phase_shift_deg))
        def process(p):
            new_c = (p.to_complex() * self.ratio) * rotation
            mag, ang = cmath.polar(new_c)
            if isinstance(p, VoltagePhasor): return VoltagePhasor(mag, math.degrees(ang))
            return CurrentPhasor(mag, math.degrees(ang))
        return type(system)(process(system.a), process(system.b), process(system.c))

    @property
    def current(self): return self._apply_shift(super().current)
    @property
    def voltage(self): return self._apply_shift(super().voltage)

class Meter(ProtectionDevice):
    def get_summary_dict(self):
        stats = super().get_summary_dict()
        v, i = self.voltage, self.current
        if v and i:
            def calc_pq(vp, ip):
                s_c = vp.to_complex() * ip.to_complex().conjugate()
                return s_c.real, s_c.imag
            p_total = sum(calc_pq(getattr(v, ph), getattr(i, ph))[0] for ph in 'abc')
            q_total = sum(calc_pq(getattr(v, ph), getattr(i, ph))[1] for ph in 'abc')
            s_total = math.sqrt(p_total**2 + q_total**2)
            stats["--- POWER METRICS ---"] = "HEADER"
            stats["Total Active Power"] = p_total
            stats["Total Apparent Power"] = s_total
            stats["System PF"] = f"{p_total/s_total:.3f}" if s_total > 0 else "1.000"
        return stats

class Indicator(ProtectionDevice):
    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Status"] = "ON (Energized)" if self.dc_status else "OFF (De-energized)"
        return stats
