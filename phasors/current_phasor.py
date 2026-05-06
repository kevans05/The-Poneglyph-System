import cmath
import math

class CurrentPhasor:
    """Represents a current phasor in polar form (magnitude and phase angle)"""
    def __init__(self, magnitude=0, angle_degrees=0):
        if magnitude < 0:
            raise ValueError("Current magnitude cannot be negative")
        self.magnitude = magnitude
        self.angle_degrees = angle_degrees

    def to_complex(self):
        return cmath.rect(self.magnitude, math.radians(self.angle_degrees))

    def __add__(self, other):
        if not isinstance(other, CurrentPhasor):
            raise TypeError("Can only add CurrentPhasor to other CurrentPhasor")
        total = self.to_complex() + other.to_complex()
        return self._from_complex(total)

    def __sub__(self, other):
        if not isinstance(other, CurrentPhasor):
            raise TypeError("Can only subtract CurrentPhasor from CurrentPhasor")
        diff = self.to_complex() - other.to_complex()
        return self._from_complex(diff)

    def __mul__(self, other):
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
        return CurrentPhasor(mag, math.degrees(ang_rad))

    def __repr__(self):
        return f"CurrentPhasor({self.magnitude:.2f} A ∠ {self.angle_degrees:.2f} deg)"