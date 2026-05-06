import cmath
import math

from .utilities.formatter import SIPrefix


class VoltagePhasor:
    """Represents a voltage phasor in polar form (magnitude and phase angle)"""
    def __init__(self, magnitude=0, angle_degrees=0):
        if magnitude < 0:
            raise ValueError("Voltage magnitude cannot be negative")
        self.magnitude = magnitude
        self.angle_degrees = angle_degrees

    def to_complex(self):
        return cmath.rect(self.magnitude, math.radians(self.angle_degrees))

    def __add__(self, other):
        if not isinstance(other, VoltagePhasor):
            raise TypeError("Can only add VoltagePhasor to other VoltagePhasor")
        total = self.to_complex() + other.to_complex()
        return self._from_complex(total)

    def __sub__(self, other):
        if not isinstance(other, VoltagePhasor):
            raise TypeError("Can only subtract VoltagePhasor from VoltagePhasor")
        diff = self.to_complex() - other.to_complex()
        return self._from_complex(diff)

    def __mul__(self, other):
        # Supports scalar (scaling) or complex (rotation like alpha)
        if not isinstance(other, (int, float, complex)):
            return NotImplemented
        result = self.to_complex() * other
        return self._from_complex(result)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, scalar):
        if not isinstance(scalar, (int, float, complex)):
            raise TypeError("Division requires a numeric type")
        result = self.to_complex() / scalar
        return self._from_complex(result)

    def _from_complex(self, c_val):
        mag, ang_rad = cmath.polar(c_val)
        return VoltagePhasor(mag, math.degrees(ang_rad))

    def __repr__(self):
        return f"VoltagePhasor({self.magnitude:.2f} V ∠ {self.angle_degrees:.2f} deg)"
        
    def __str__(self):
        v = SIPrefix.format_value(self.magnitude, "V")
        return f"{v} ∠ {self.angle_degrees:.2f} deg"