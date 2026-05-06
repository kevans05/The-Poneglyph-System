import cmath
import math

from .voltage_phasor import VoltagePhasor
from .current_phasor import CurrentPhasor

class delta_currents:
    def __init__(self, phase_a=CurrentPhasor(0,0), phase_b=CurrentPhasor(0,0), phase_c=CurrentPhasor(0,0)):
        self.a = phase_a  # current phase a data
        self.b = phase_b  # current phase b data
        self.c = phase_c  # current phase c data

    def __add__(self, other):
        if not isinstance(other, delta_currents):
            raise TypeError("Unsupported operand type(s) for +")
        return delta_currents(self.a + other.a, self.b + other.b, self.c + other.c)

    def __sub__(self, other):
        if not isinstance(other, delta_currents):
            raise TypeError("Unsupported operand type(s) for -")
        return delta_currents(self.a - other.a, self.b - other.b, self.c - other.c)

    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float)):
            raise TypeError("Scalar must be numeric")
        return delta_currents(self.a * scalar, self.b * scalar, self.c * scalar)

    def __truediv__(self, scalar):
        if not isinstance(scalar, (int, float)):
            raise TypeError("Scalar must be numeric")
        return delta_currents(self.a / scalar, self.b / scalar, self.c / scalar)

    def get_sequence_components(self):
        alpha = cmath.rect(1, 2 * cmath.pi / 3)  # 120 deg rotation
        I0 = (self.a + self.b + self.c) / 3
        I1 = (self.a + alpha * self.b + alpha ** 2 * self.c) / 3
        I2 = (self.a + alpha ** 2 * self.b + alpha * self.c) / 3
        return (I0, I1, I2)  # Complex phasors (zero, positive, negative)

    def is_balanced(self, tolerance=1e-5):
        I0, I1, I2 = self.get_sequence_components()
        return (abs(I0) < tolerance and abs(I2) < tolerance)

    def __str__(self):
        return f"ΔI: A={self.a}, B={self.b}, C={self.c}"

    def __repr__(self):
        return f"delta_currents(phase_a={repr(self.a)}, phase_b={repr(self.b)}, phase_c={repr(self.c)})"
        
class delta_voltages:
    def __init__(self, phase_ab=VoltagePhasor(0, 0), phase_bc=VoltagePhasor(0, 0), phase_ca=VoltagePhasor(0, 0)):
        """
        Represents Line-to-Line voltages in a delta-connected system.
        phase_ab: Voltage phase A to B (Vab)
        phase_bc: Voltage phase B to C (Vbc)
        phase_ca: Voltage phase C to A (Vca)
        """
        # We store them internally as a, b, c so your phasor math tools 
        # (like voltage_current_multiplier) still work seamlessly!
        self.a = phase_ab
        self.b = phase_bc
        self.c = phase_ca

    def __add__(self, other):
        if not isinstance(other, delta_voltages):
            raise TypeError("Unsupported operand type(s) for +")
        return delta_voltages(self.a + other.a, self.b + other.b, self.c + other.c)

    def __sub__(self, other):
        if not isinstance(other, delta_voltages):
            raise TypeError("Unsupported operand type(s) for -")
        return delta_voltages(self.a - other.a, self.b - other.b, self.c - other.c)

    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float, complex)):
            raise TypeError("Scalar must be numeric")
        return delta_voltages(self.a * scalar, self.b * scalar, self.c * scalar)

    def __truediv__(self, scalar):
        if not isinstance(scalar, (int, float, complex)):
            raise TypeError("Scalar must be numeric")
        if scalar == 0:
            raise ZeroDivisionError("Division by zero")
        return delta_voltages(self.a / scalar, self.b / scalar, self.c / scalar)

    def get_sequence_components(self):
        """Calculate symmetrical components for Line-to-Line voltages (V0, V1, V2)"""
        alpha = cmath.rect(1, 2 * cmath.pi / 3)
        
        # In a perfectly closed Delta, V0 will always theoretically be 0 
        # because of Kirchhoff's Voltage Law (Vab + Vbc + Vca = 0)
        v0 = (self.a + self.b + self.c) / 3
        v1 = (self.a + alpha * self.b + (alpha ** 2) * self.c) / 3
        v2 = (self.a + (alpha ** 2) * self.b + alpha * self.c) / 3
        return (v0, v1, v2)

    def is_balanced(self, tolerance=1e-5):
        """Check if line voltages form a balanced set"""
        v0, v1, v2 = self.get_sequence_components()
        # Using .magnitude to safely check the tolerance
        return (abs(v0.magnitude) < tolerance and abs(v2.magnitude) < tolerance)

    def __str__(self):
        return f"Δ-V: AB={self.a}, BC={self.b}, CA={self.c}"

    def __repr__(self):
        return f"delta_voltages(phase_ab={repr(self.a)}, phase_bc={repr(self.b)}, phase_ca={repr(self.c)})"