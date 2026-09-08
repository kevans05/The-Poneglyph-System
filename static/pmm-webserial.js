"use strict";

/**
 * PMM-1 driver — browser side, over the Web Serial API.
 *
 * Speaks the exact same RS-232 protocol the former Python driver used, so
 * nothing downstream of a reading changes — only the transport moves from the
 * server to the browser:
 *
 *   - 19200 baud, 8N1, no flow control
 *   - commands are terminated with ';'
 *   - responses are terminated with CRLF
 *   - a successful mode change echoes 'AOK!'
 *   - the instrument may need a command sent twice before it takes
 *   - single-phase query ("qr") reply: chan1,chan2,watts,vars,phase,freq
 *
 * Web Serial needs a secure context (https or http://localhost) and a
 * Chromium-based browser.  requestPort() must run inside a user gesture.
 */

const PMM1_BAUD = 19200;
const PMM1_RESPONSE_TIMEOUT_MS = 2500; // generous for slow instruments
const PMM1_INTER_CMD_DELAY_MS = 150;

function _pmmDelay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class PMM1WebSerialPort {
  constructor(port) {
    this.port = port; // a Web Serial SerialPort
    this._reader = null;
    this._writer = null;
    this._rxBuf = "";
    this._connected = false;
  }

  static isSupported() {
    return typeof navigator !== "undefined" && "serial" in navigator;
  }

  /** Prompt the user to choose a serial port. Must be called from a click/tap. */
  static async request() {
    if (!PMM1WebSerialPort.isSupported()) {
      throw new Error(
        "Web Serial API not available — open this page in Chrome or Edge over HTTPS or localhost",
      );
    }
    const port = await navigator.serial.requestPort();
    return new PMM1WebSerialPort(port);
  }

  get isConnected() {
    return this._connected;
  }

  /** Short human label for the chosen port (USB VID:PID when we can get it). */
  label() {
    try {
      const info = this.port.getInfo ? this.port.getInfo() : {};
      if (info && info.usbVendorId != null) {
        const vid = info.usbVendorId.toString(16).padStart(4, "0");
        const pid = (info.usbProductId || 0).toString(16).padStart(4, "0");
        return `USB ${vid}:${pid}`;
      }
    } catch (e) {
      /* ignore */
    }
    return "serial port";
  }

  // ── Low-level I/O ─────────────────────────────────────────────────────────

  async _openStreams() {
    await this.port.open({
      baudRate: PMM1_BAUD,
      dataBits: 8,
      parity: "none",
      stopBits: 1,
      flowControl: "none",
    });
    this._writer = this.port.writable.getWriter();
    this._reader = this.port.readable.getReader();
    this._rxBuf = "";
    this._pump(); // background read loop, not awaited
  }

  async _pump() {
    const dec = new TextDecoder();
    try {
      while (true) {
        const { value, done } = await this._reader.read();
        if (done) break;
        if (value) this._rxBuf += dec.decode(value, { stream: true });
      }
    } catch (e) {
      /* reader was cancelled on disconnect */
    }
  }

  async _readLine(timeoutMs = PMM1_RESPONSE_TIMEOUT_MS) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const idx = this._rxBuf.indexOf("\r\n");
      if (idx >= 0) {
        const line = this._rxBuf.slice(0, idx);
        this._rxBuf = this._rxBuf.slice(idx + 2);
        return line.trim();
      }
      await _pmmDelay(20);
    }
    const partial = this._rxBuf.trim(); // return whatever arrived
    this._rxBuf = "";
    return partial;
  }

  async _send(cmd) {
    if (!cmd.endsWith(";")) cmd += ";";
    this._rxBuf = ""; // discard stale input (reset_input_buffer equivalent)
    await this._writer.write(new TextEncoder().encode(cmd));
    return this._readLine();
  }

  async _cmd(cmd, expect = "AOK!", retries = 2) {
    let resp = "";
    for (let i = 0; i < retries; i++) {
      resp = await this._send(cmd);
      if (resp.includes(expect)) return resp;
      await _pmmDelay(PMM1_INTER_CMD_DELAY_MS);
    }
    return resp; // last response even if unexpected
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────

  async connect() {
    try {
      await this._openStreams();
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
    const resp = await this._cmd("m1", "AOK!");
    if (resp.includes("AOK!")) {
      this._connected = true;
      return { ok: true, response: resp };
    }
    await this.disconnect();
    return {
      ok: false,
      error: `PMM-1 did not acknowledge m1 command (got: ${JSON.stringify(resp)})`,
    };
  }

  async disconnect() {
    try {
      if (this._connected) await this._cmd("mpu", "AOK!", 1);
    } catch (e) {
      /* ignore */
    }
    try {
      if (this._reader) {
        await this._reader.cancel();
        this._reader.releaseLock();
      }
    } catch (e) {
      /* ignore */
    }
    try {
      if (this._writer) this._writer.releaseLock();
    } catch (e) {
      /* ignore */
    }
    try {
      await this.port.close();
    } catch (e) {
      /* ignore */
    }
    this._reader = null;
    this._writer = null;
    this._connected = false;
    return { ok: true };
  }

  // ── Configuration ────────────────────────────────────────────────────────
  //
  // chan1/chan2 integers per PMM manual:
  //   0=Van 1=Vbn 2=Vcn 3=Vab 4=Vbc 5=Vca 6=Ia 7=Ib 8=Ic

  async configureChannels(chan1, chan2) {
    if (!this._connected) return { ok: false, error: "Not connected" };
    let resp = await this._cmd(`slpcustomw,${chan1},${chan2}`, "AOK!");
    if (!resp.includes("AOK!")) {
      return { ok: false, error: `Channel write failed: ${JSON.stringify(resp)}` };
    }
    resp = await this._cmd("m1", "AOK!"); // re-enter mode so the change registers
    if (!resp.includes("AOK!")) {
      return { ok: false, error: `Mode re-entry failed: ${JSON.stringify(resp)}` };
    }
    return { ok: true };
  }

  // ── Measurement ──────────────────────────────────────────────────────────

  async query() {
    if (!this._connected) return { ok: false, error: "Not connected" };
    const resp = await this._send("qr");

    if (resp.toLowerCase().includes("not in this mode")) {
      return { ok: false, error: "PMM not in queryable mode — re-enter m1" };
    }

    const parts = resp.split(",").map((p) => p.trim());
    if (parts.length < 6) {
      return { ok: false, error: `Unexpected response: ${JSON.stringify(resp)}` };
    }

    const nums = parts.slice(0, 6).map(Number);
    if (nums.some((n) => Number.isNaN(n))) {
      return { ok: false, error: `Parse error — raw: ${JSON.stringify(resp)}` };
    }

    return {
      ok: true,
      chan1: nums[0],
      chan2: nums[1],
      watts: nums[2],
      vars: nums[3],
      phase: nums[4], // degrees, chan1 → chan2
      freq: nums[5],
      raw: resp,
    };
  }
}

// Shared handle for the connected PMM-1, used by the measurement wizard and the
// mobile remote.  `active` is a connected PMM1WebSerialPort or null.
window.PMM1 = { Port: PMM1WebSerialPort, active: null };
