import math
import socket


class PMM2Client:
    """
    Python wrapper for the PMM2 RTS Commands Interface.
    """

    # Voltage Ranges Map[cite: 1]
    VOLTAGE_RANGES = {1: "2V", 2: "10V", 3: "30V", 4: "150V", 5: "300V", 6: "1000V"}

    # Current Ranges Map (CH1-3)[cite: 1]
    CURRENT_RANGES_CH1_3 = {
        1: "1A",
        2: "3A",
        3: "10A",
        4: "30A",
        5: "100A",
        6: "100A",
        7: "CT INPUT",
    }

    # Current Ranges Map (CH4)[cite: 1]
    CURRENT_RANGES_CH4 = {
        1: "0.002A",
        2: "0.05A",
        3: "0.5A",
        4: "1.5A",
        5: "10A",
        6: "30A",
        7: "CT INPUT",
    }

    def __init__(self, ip_address, port=5025, timeout=5.0):
        """Initialize the connection to the PMM2."""
        self.ip_address = ip_address
        self.port = port
        self.timeout = timeout

    def _send_command(self, cmd: str, expect_response: bool = True) -> str:
        """Low-level function to send a command to the PMM2 and read the response."""
        # Ensure commands end with the required semicolon
        if not cmd.endswith(";"):
            cmd += ";"

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            s.connect((self.ip_address, self.port))
            s.sendall(cmd.encode("ascii"))

            if expect_response:
                response = ""
                while True:
                    chunk = s.recv(1)
                    if not chunk:
                        break
                    char = chunk.decode("ascii")
                    response += char
                    if char == ";":
                        break
                return response
        return ""

    # ==========================================
    # DEVICE ID & CONFIGURATION COMMANDS
    # ==========================================

    def query_configuration(self) -> str:
        """Returns the PMM2 configuration[cite: 1]."""
        return self._send_command("QC;")

    def query_ip(self) -> str:
        """Returns the PMM2 IP address[cite: 1]."""
        return self._send_command("QIP;")

    def query_mac(self) -> str:
        """Returns the MAC address of the DSP[cite: 1]."""
        return self._send_command("QMAC;")

    def set_device_id(
        self, family: str, serial_num: str, model: str, hw_rev: int, dsp_rev: int
    ) -> str:
        """Set PMM2 Device ID and save in Flash[cite: 1]."""
        cmd = f"DEVID{family}:{serial_num}:{model}:{hw_rev}:{dsp_rev};"
        return self._send_command(cmd)

    # ==========================================
    # RESET & SYSTEM COMMANDS
    # ==========================================

    def software_reset(self):
        """Executes a Software reset[cite: 1]."""
        return self._send_command("SU;")

    def unit_reset(self):
        """Reboots the DSP[cite: 1]."""
        # The document shows no return for unit reset[cite: 1]
        self._send_command("U;", expect_response=False)

    def switch_to_bootloader(self):
        """Reboots the DSP in Boot Loader mode[cite: 1]."""
        return self._send_command("SWI;")

    def kill(self):
        """Reboot the DSP to Boot Loader Mode permanently[cite: 1]."""
        return self._send_command("KILL;")

    # ==========================================
    # RANGE COMMANDS
    # ==========================================

    def set_auto_range(self, enable: bool) -> str:
        """Enable (1) or Disable (0) AUTO Range[cite: 1]."""
        flag = 1 if enable else 0
        return self._send_command(f"AUTORNG:{flag};")

    def set_range(self, channel: int, range_val: int, is_vpmm: bool) -> str:
        """Set the range for the specified channel. Flag: 1-VPMM | 0-IPMM[cite: 1]."""
        flag = 1 if is_vpmm else 0
        return self._send_command(f"RANGE{channel}:{range_val}:{flag};")

    def set_all_ranges(self, r1: int, r2: int, r3: int, r4: int, is_vpmm: bool) -> str:
        """Sets the ranges for all the channels of the VPMM or IPMM[cite: 1]."""
        flag = 1 if is_vpmm else 0
        return self._send_command(f"RANGES{r1}:{r2}:{r3}:{r4}:{flag};")

    def set_range_all_vpmm(self, range_val: int) -> str:
        """Set all VPMM Channels to the same range (IPMM not supported)[cite: 1]."""
        return self._send_command(f"RNGALL{range_val}:1;")

    def query_voltage_ranges(self) -> str:
        """Returns the Active Voltage Ranges[cite: 1]."""
        return self._send_command("QVR;")

    def query_current_ranges(self) -> str:
        """Returns the Active Current Ranges[cite: 1]."""
        return self._send_command("QIR;")

    # ==========================================
    # MEASUREMENT COMMANDS
    # ==========================================

    def query_all(self) -> str:
        """Returns information on all measurements[cite: 1]."""
        return self._send_command("QRYALL;")

    def get_harmonics(self, channel_range: int, is_vpmm: bool) -> str:
        """Get Harmonics' Amplitudes up to 50 multiples of base frequency[cite: 1]."""
        flag = 1 if is_vpmm else 0
        return self._send_command(f"GETHARM{channel_range}:{flag};")

    def query_time(self) -> str:
        """Returns the PMM2 Timer Time[cite: 1]."""
        return self._send_command("QT;")


class PMM2Driver:
    """
    Driver for Megger PMM-2 using the RTS Commands Interface (TCP/IP).
    """

    # Maps PMM_SOURCES index (0-8) → (type, pmm2_channel)
    # 0-5 = voltage (Van,Vbn,Vcn,Vab,Vbc,Vca) → VPMM ch 1-3 (mod 3)
    # 6-8 = current (Ia,Ib,Ic)                → IPMM ch 1-3
    _SRC_V_CH = [1, 2, 3, 1, 2, 3]  # VPMM channel for sources 0-5
    _SRC_I_CH = [1, 2, 3]            # IPMM channel for sources 6-8

    def __init__(self, ip_address: str, port: int = 5025):
        self.ip_address = ip_address
        self.port = port
        self.client = PMM2Client(ip_address, port)
        self._connected = False
        self._chan1 = 0  # PMM_SOURCES index for voltage reference
        self._chan2 = 6  # PMM_SOURCES index for measurement channel

    def connect(self) -> dict:
        try:
            # PMM2 is connectionless in the sense that it's TCP,
            # but we can try a simple query to verify connectivity.
            resp = self.client.query_configuration()
            if resp:
                self._connected = True
                return {"ok": True, "response": resp}
            return {"ok": False, "error": "No response from PMM2"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def port_name(self) -> str:
        return f"{self.ip_address}:{self.port}"

    def configure_channels(self, chan1: int, chan2: int) -> dict:
        """
        chan1, chan2 are PMM_SOURCES indices (0-8):
          0-5 → voltage (Van,Vbn,Vcn,Vab,Vbc,Vca)
          6-8 → current (Ia,Ib,Ic)
        Stores the selection and enables auto-range on the device.
        """
        self._chan1 = chan1
        self._chan2 = chan2
        try:
            self.client.set_auto_range(True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def query(self) -> dict:
        """
        Send QRYALL; and parse the 48-field response.

        QRYALL field layout (0-indexed):
          V1..V4 blocks (5 fields each): ACRms, DCRms, Freq, Ph, Gain
          4 bookkeeping fields (VSampleId, V_SPI_CRC, Vnotused, Vnotused1)
          I1..I4 blocks (5 fields each): ACRms, DCRms, Freq, Ph, Gain
          4 bookkeeping fields (ISampleId, I_SPI_CRC, Inotused, Inotused1)
        """
        try:
            raw = self.client.query_all()
            fields = [float(x) for x in raw.rstrip(";").split(",")]
            if len(fields) < 48:
                return {"ok": False, "error": f"QRYALL returned {len(fields)} fields, expected 48", "raw": raw}

            def v_block(pmm2_ch):
                base = (pmm2_ch - 1) * 5
                return fields[base], fields[base + 2], fields[base + 3]  # ACRms, Freq, Ph

            def i_block(pmm2_ch):
                base = 24 + (pmm2_ch - 1) * 5
                return fields[base], fields[base + 2], fields[base + 3]  # ACRms, Freq, Ph

            # Channel 1 is always the voltage reference
            v1_ch = self._SRC_V_CH[self._chan1]
            v1_mag, v1_freq, v1_ph = v_block(v1_ch)

            if self._chan2 < 6:
                v2_ch = self._SRC_V_CH[self._chan2]
                c2_mag, c2_freq, c2_ph = v_block(v2_ch)
            else:
                i_ch = self._SRC_I_CH[self._chan2 - 6]
                c2_mag, c2_freq, c2_ph = i_block(i_ch)

            phase_diff = v1_ph - c2_ph
            watts = v1_mag * c2_mag * math.cos(math.radians(phase_diff))
            vars_ = v1_mag * c2_mag * math.sin(math.radians(phase_diff))

            return {
                "ok": True,
                "raw": raw,
                "chan1": v1_mag,
                "chan2": c2_mag,
                "phase": phase_diff,
                "watts": watts,
                "vars": vars_,
                "freq": c2_freq,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
