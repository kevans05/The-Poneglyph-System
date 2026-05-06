import random

class SimulationDriver:
    """Mock driver that generates realistic-looking power measurements."""
    def __init__(self, model_name="PMM Simulation"):
        self.model_name = model_name
        self._connected = False
        self.port = "SIMULATOR"

    def connect(self) -> dict:
        self._connected = True
        return {"ok": True, "response": f"Connected to {self.model_name}"}

    def disconnect(self):
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def port_name(self) -> str:
        return self.port

    def configure_channels(self, chan1: int, chan2: int) -> dict:
        return {"ok": True}

    def query(self) -> dict:
        """Generate random but stable-ish 60Hz power data."""
        return {
            "ok": True,
            "chan1": 67.0 + random.uniform(-0.1, 0.1),
            "chan2": 5.0 + random.uniform(-0.02, 0.02),
            "watts": 300.0 + random.uniform(-5, 5),
            "vars": 50.0 + random.uniform(-2, 2),
            "phase": random.choice([0.0, 120.0, 240.0]) + random.uniform(-0.5, 0.5),
            "freq": 60.0 + random.uniform(-0.01, 0.01),
            "raw": "SIMULATED_DATA",
        }
