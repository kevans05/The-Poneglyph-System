"""
PMM (Power MultiMeter) serial communication driver.

Supports:
  PMM1 (Megger) — RS-232, 19200 8N1, semicolon-terminated commands
  PMM2           — placeholder (protocol TBD from Megger)

Cross-platform: works on Windows (COMx) and Linux/Raspberry Pi (/dev/ttyUSBx,
/dev/ttyAMAx, etc.).  Port enumeration is done via pyserial so the caller
never needs to hard-code platform-specific paths.

Thread safety: a module-level lock (_lock) guards the single active driver
instance (_active).  All API-level helpers acquire the lock.
"""

import threading
import time

try:
    import serial
    import serial.tools.list_ports
    _SERIAL_IMPORT_ERROR: Exception | None = None
except ImportError as _e:
    serial = None  # type: ignore[assignment]
    _SERIAL_IMPORT_ERROR = _e

# ── Module-level connection state ─────────────────────────────────────────────



# ── Port enumeration ──────────────────────────────────────────────────────────

def list_ports():
    """Return a list of available serial ports suitable for display in a UI.

    Each entry: {"device": "/dev/ttyUSB0", "description": "USB Serial Device"}

    On Linux, kernel-stub UARTs (/dev/ttySx) that have no real hardware
    attached (hwid == "n/a") are excluded to keep the list clean.
    On Windows, all COMx ports are included.
    On Raspberry Pi, /dev/ttyAMA* and /dev/ttyUSB* are always included.

    If pyserial is not installed, returns an empty list (PMM2 over TCP and
    the simulator driver remain available).
    """
    if serial is None:
        return []
    ports = []
    for p in serial.tools.list_ports.comports():
        hwid = p.hwid or ""
        dev = p.device

        # Filter out unconnected Linux kernel UART stubs
        import re
        if re.match(r"^/dev/ttyS\d+$", dev) and hwid.upper() in ("N/A", ""):
            continue

        ports.append({
            "device": dev,
            "description": p.description if p.description and p.description.lower() not in ("n/a", "") else dev,
            "hwid": hwid,
        })

    # Sort: Windows COMx by number, then Linux /dev/* alphabetically
    def _sort_key(entry):
        d = entry["device"]
        if d.upper().startswith("COM"):
            try:
                return (0, int(d[3:]))
            except ValueError:
                return (0, 999)
        # Prefer USB and AMA (Pi built-in) over generic
        if "USB" in d or "AMA" in d or "ACM" in d:
            return (1, d)
        return (2, d)

    return sorted(ports, key=_sort_key)


# ── PMM1 driver ───────────────────────────────────────────────────────────────

class PMM1Driver:
    """
    Serial driver for the Megger PMM-1 Power MultiMeter.

    Protocol per manual:
      - 19200 baud, 8N1, no flow control
      - All commands end with ';'
      - Successful mode changes → 'AOK!' response
      - Invalid commands → 'what?' response
      - Commands may require double entry before being accepted (per manual)
      - Single-phase query response: chan1,chan2,watts,vars,phase,freq
    """

    BAUD = 19200
    RESPONSE_TIMEOUT = 2.5   # seconds — generous for slow instruments
    INTER_CMD_DELAY = 0.15   # seconds between retries

    def __init__(self, port: str):
        if serial is None:
            raise RuntimeError(
                "pyserial is not installed — install it with `pip install pyserial` "
                "to use the PMM1 driver."
            )
        self.port = port
        self._ser: "serial.Serial | None" = None

    # ── Low-level I/O ─────────────────────────────────────────────────────────

    def _open(self):
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.RESPONSE_TIMEOUT,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def _send(self, cmd: str) -> str:
        """Send one command and return the stripped ASCII response."""
        if not cmd.endswith(";"):
            cmd += ";"
        self._ser.reset_input_buffer()
        self._ser.write(cmd.encode("ascii"))
        resp = self._ser.read_until(b"\r\n")
        return resp.decode("ascii", errors="replace").strip()

    def _cmd(self, cmd: str, expect: str = "AOK!", retries: int = 2) -> str:
        """Send a command up to `retries` times, returning as soon as `expect`
        appears in the response.  Per manual, PMM-1 may need a command sent
        twice before accepting it.
        """
        resp = ""
        for _ in range(retries):
            resp = self._send(cmd)
            if expect in resp:
                return resp
            time.sleep(self.INTER_CMD_DELAY)
        return resp  # return last response even if not expected

    # ── Connection lifecycle ───────────────────────────────────────────────────

    def connect(self) -> dict:
        """Open the serial port and enter single-phase mode.

        Returns {"ok": True} or {"ok": False, "error": "…"}.
        """
        try:
            self._open()
        except serial.SerialException as e:
            return {"ok": False, "error": str(e)}

        resp = self._cmd("m1", "AOK!")
        if "AOK!" in resp:
            return {"ok": True, "response": resp}
        return {"ok": False, "error": f"PMM-1 did not acknowledge m1 command (got: {resp!r})"}

    def disconnect(self):
        """Return PMM to power-up menu and close port."""
        if self._ser and self._ser.is_open:
            try:
                self._cmd("mpu", "AOK!", retries=1)
            except Exception:
                pass
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ── Configuration ─────────────────────────────────────────────────────────

    def configure_channels(self, chan1: int, chan2: int) -> dict:
        """Write single-phase channel selection and re-enter m1 mode.

        chan1/chan2 integers per PMM manual:
          0=Van  1=Vbn  2=Vcn  3=Vab  4=Vbc  5=Vca  6=Ia  7=Ib  8=Ic
        """
        resp = self._cmd(f"slpcustomw,{chan1},{chan2}", "AOK!")
        if "AOK!" not in resp:
            return {"ok": False, "error": f"Channel write failed: {resp!r}"}
        # Re-enter mode so the change is recognised
        resp2 = self._cmd("m1", "AOK!")
        if "AOK!" not in resp2:
            return {"ok": False, "error": f"Mode re-entry failed: {resp2!r}"}
        return {"ok": True}

    def read_channel_config(self) -> dict:
        """Read current channel 1/2 selection."""
        resp = self._send("slpcustomr")
        return {"ok": True, "raw": resp}

    # ── Measurement ───────────────────────────────────────────────────────────

    def query(self) -> dict:
        """Query current single-phase reading.

        PMM-1 single-phase response format (comma-delimited):
          chan1, chan2, watts, vars, phase(chan1→chan2), freq

        Returns a dict with float fields plus the raw string.
        """
        resp = self._send("qr")

        if "not in this mode" in resp.lower():
            return {"ok": False, "error": "PMM not in queryable mode — re-enter m1"}

        parts = [p.strip() for p in resp.split(",")]
        if len(parts) < 6:
            return {"ok": False, "error": f"Unexpected response: {resp!r}"}

        try:
            return {
                "ok": True,
                "chan1":  float(parts[0]),
                "chan2":  float(parts[1]),
                "watts":  float(parts[2]),
                "vars":   float(parts[3]),
                "phase":  float(parts[4]),   # degrees, chan1 → chan2
                "freq":   float(parts[5]),
                "raw":    resp,
            }
        except ValueError as e:
            return {"ok": False, "error": f"Parse error: {e} — raw: {resp!r}"}


