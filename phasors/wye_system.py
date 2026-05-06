import cmath
import math

from .current_phasor import CurrentPhasor
from .voltage_phasor import VoltagePhasor

class wye_currents:
    def __init__(self, phase_a=CurrentPhasor(0, 0), phase_b=CurrentPhasor(0, 0),
                 phase_c=CurrentPhasor(0, 0), neutral=None):
        """
        Represents currents in a wye-connected system
        phase_a: Line current in phase A (same as phase current)
        phase_b: Line current in phase B
        phase_c: Line current in phase C
        neutral: Optional neutral current (if not provided, will be calculated)
        """
        self.a = phase_a
        self.b = phase_b
        self.c = phase_c
        self._neutral = neutral  # Store optional neutral value

    @property
    def neutral_current(self):
        """Get neutral current (calculate if not provided)"""
        if self._neutral is not None:
            return self._neutral
        return self.a + self.b + self.c

    @neutral_current.setter
    def neutral_current(self, value):
        """Set a specific neutral current value"""
        self._neutral = value

    def __add__(self, other):
        if not isinstance(other, wye_currents):
            raise TypeError("Unsupported operand type(s) for +")

        # Handle neutral current - if both have custom neutrals, add them
        new_neutral = None
        if self._neutral is not None and other._neutral is not None:
            new_neutral = self._neutral + other._neutral

        return wye_currents(
            self.a + other.a,
            self.b + other.b,
            self.c + other.c,
            neutral=new_neutral
        )

    def __sub__(self, other):
        if not isinstance(other, wye_currents):
            raise TypeError("Unsupported operand type(s) for -")

        # Handle neutral current
        new_neutral = None
        if self._neutral is not None and other._neutral is not None:
            new_neutral = self._neutral - other._neutral

        return wye_currents(
            self.a - other.a,
            self.b - other.b,
            self.c - other.c,
            neutral=new_neutral
        )

    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float)):
            raise TypeError("Scalar must be numeric")

        # Handle neutral current
        new_neutral = None
        if self._neutral is not None:
            new_neutral = self._neutral * scalar

        return wye_currents(
            self.a * scalar,
            self.b * scalar,
            self.c * scalar,
            neutral=new_neutral
        )

    def __truediv__(self, scalar):
        if not isinstance(scalar, (int, float)):
            raise TypeError("Scalar must be numeric")
        if scalar == 0:
            raise ZeroDivisionError("Division by zero not allowed")

        # Handle neutral current
        new_neutral = None
        if self._neutral is not None:
            new_neutral = self._neutral / scalar

        return wye_currents(
            self.a / scalar,
            self.b / scalar,
            self.c / scalar,
            neutral=new_neutral
        )

    def get_sequence_components(self):
        """Calculate symmetrical components (same as delta system)"""
        alpha = cmath.rect(1, 2 * cmath.pi / 3)  # 120 deg rotation
        I0 = (self.a + self.b + self.c) / 3
        I1 = (self.a + alpha * self.b + alpha ** 2 * self.c) / 3
        I2 = (self.a + alpha ** 2 * self.b + alpha * self.c) / 3
        return (I0, I1, I2)  # Complex phasors (zero, positive, negative)

    def is_balanced(self, tolerance=1e-5):
        """Check if currents form a balanced set"""
        I0, I1, I2 = self.get_sequence_components()
        return (abs(I0) < tolerance and abs(I2) < tolerance)
        
    def rotate(self, angle_deg):
        """Returns a new system rotated by angle_deg"""
        rotation_vector = cmath.rect(1, math.radians(angle_deg))
        
        def _rot(phasor):
            new_complex = phasor.to_complex() * rotation_vector
            mag, ang_rad = cmath.polar(new_complex)
            # This handles both VoltagePhasor and CurrentPhasor automatically
            return type(phasor)(mag, math.degrees(ang_rad))

        return type(self)(_rot(self.a), _rot(self.b), _rot(self.c))
    def __str__(self):
        source = "provided" if self._neutral is not None else "calculated"
        return (f"Y-I: A={self.a}, B={self.b}, C={self.c}, "
                f"Neutral({source})={self.neutral_current}")

    def __repr__(self):
        if self._neutral is not None:
            return (f"wye_currents(phase_a={repr(self.a)}, phase_b={repr(self.b)}, "
                    f"phase_c={repr(self.c)}, neutral={repr(self._neutral)})")
        return f"wye_currents(phase_a={repr(self.a)}, phase_b={repr(self.b)}, phase_c={repr(self.c)})"
        

class wye_voltages:
    def __init__(self, phase_a=VoltagePhasor(0, 0), phase_b=VoltagePhasor(0, 0),
                 phase_c=VoltagePhasor(0, 0), neutral_offset=None):
        """
        Represents Line-to-Neutral voltages in a wye-connected system.
        phase_a: Voltage phase A to Neutral (Van)
        phase_b: Voltage phase B to Neutral (Vbn)
        phase_c: Voltage phase C to Neutral (Vcn)
        neutral_offset: Optional displacement of neutral point from ground
        """
        self.a = phase_a
        self.b = phase_b
        self.c = phase_c
        self._neutral_offset = neutral_offset

    @property
    def line_to_line(self):
        """
        Calculates Line-to-Line voltages: (Vab, Vbc, Vca)
        Vab = Van - Vbn
        """
        v_ab = self.a - self.b
        v_bc = self.b - self.c
        v_ca = self.c - self.a
        return (v_ab, v_bc, v_ca)

    @property
    def neutral_displacement(self):
        """Get neutral voltage displacement (Vn)"""
        if self._neutral_offset is not None:
            return self._neutral_offset
        # For a balanced source, the average of phasors is the displacement
        return (self.a + self.b + self.c) / 3

    def rotate(self, angle_deg):
        """Returns a new system rotated by angle_deg"""
        rotation_vector = cmath.rect(1, math.radians(angle_deg))
        
        def _rot(phasor):
            new_complex = phasor.to_complex() * rotation_vector
            mag, ang_rad = cmath.polar(new_complex)
            # This handles both VoltagePhasor and CurrentPhasor automatically
            return type(phasor)(mag, math.degrees(ang_rad))

        return type(self)(_rot(self.a), _rot(self.b), _rot(self.c))
        
    def __add__(self, other):
        if not isinstance(other, wye_voltages):
            raise TypeError("Unsupported operand type(s) for +")

        new_offset = None
        if self._neutral_offset is not None and other._neutral_offset is not None:
            new_offset = self._neutral_offset + other._neutral_offset

        return wye_voltages(
            self.a + other.a,
            self.b + other.b,
            self.c + other.c,
            neutral_offset=new_offset
        )

    def __sub__(self, other):
        if not isinstance(other, wye_voltages):
            raise TypeError("Unsupported operand type(s) for -")

        new_offset = None
        if self._neutral_offset is not None and other._neutral_offset is not None:
            new_offset = self._neutral_offset - other._neutral_offset

        return wye_voltages(
            self.a - other.a,
            self.b - other.b,
            self.c - other.c,
            neutral_offset=new_offset
        )

    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float)):
            raise TypeError("Scalar must be numeric")

        new_offset = None
        if self._neutral_offset is not None:
            new_offset = self._neutral_offset * scalar

        return wye_voltages(
            self.a * scalar,
            self.b * scalar,
            self.c * scalar,
            neutral_offset=new_offset
        )

    def __truediv__(self, scalar):
        if not isinstance(scalar, (int, float)):
            raise TypeError("Scalar must be numeric")
        if scalar == 0:
            raise ZeroDivisionError("Division by zero")

        new_offset = None
        if self._neutral_offset is not None:
            new_offset = self._neutral_offset / scalar

        return wye_voltages(
            self.a / scalar,
            self.b / scalar,
            self.c / scalar,
            neutral_offset=new_offset
        )

    def get_sequence_components(self):
        """Calculate symmetrical components (V0, V1, V2)"""
        alpha = cmath.rect(1, 2 * cmath.pi / 3)
        v0 = (self.a + self.b + self.c) / 3
        v1 = (self.a + alpha * self.b + (alpha ** 2) * self.c) / 3
        v2 = (self.a + (alpha ** 2) * self.b + alpha * self.c) / 3
        return (v0, v1, v2)

    def is_balanced(self, tolerance=1e-5):
        """Check if phase voltages are balanced"""
        v0, v1, v2 = self.get_sequence_components()
        return (abs(v0) < tolerance and abs(v2) < tolerance)

    def __str__(self):
        v_type = "Offset" if self._neutral_offset is not None else "Ideal"
        return (f"Y-V: AN={self.a}, BN={self.b}, CN={self.c}, "
                f"Neutral({v_type})={self.neutral_displacement}")

    def __repr__(self):
        if self._neutral_offset is not None:
            return (f"wye_voltages(phase_a={repr(self.a)}, phase_b={repr(self.b)}, "
                    f"phase_c={repr(self.c)}, neutral_offset={repr(self._neutral_offset)})")
        return f"wye_voltages(phase_a={repr(self.a)}, phase_b={repr(self.b)}, phase_c={repr(self.c)})"