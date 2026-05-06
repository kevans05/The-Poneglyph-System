import math

class SIPrefix:
    # Standard SI prefixes for power systems
    PREFIXES = {
        3: 'k',   # kilo
        6: 'M',   # Mega
        9: 'G',   # Giga
        12: 'T',  # Tera
        0: '',    # Base unit
        -3: 'm',  # milli
    }

    @staticmethod
    def format_value(value, unit):
        """
        Converts a raw value (like 1500) and unit (like 'W') 
        into a string (like '1.50 kW')
        """
        if value == 0:
            return f"0.00 {unit}"
        
        abs_val = abs(value)
        # Determine the exponent in multiples of 3
        exponent = int(math.floor(math.log10(abs_val) / 3) * 3)
        
        # Pull prefix, default to scientific notation if outside k/M/G range
        prefix = SIPrefix.PREFIXES.get(exponent, f"e{exponent}")
        
        scaled_val = value / (10**exponent)
        
        return f"{scaled_val:.2f} {prefix}{unit}"

# mapping of power types to their specific SI units
POWER_UNITS = {
    "active": "W",
    "reactive": "var",
    "apparent": "VA",
    "complex": "VA",
    "voltage": "V",
    "current": "A"
}