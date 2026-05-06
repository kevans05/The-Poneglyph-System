/**
 * SCADA Pro Console - Utilities & Constants
 * Handles data formatting and unit mapping.
 */

// Distance between the 3 phase lines in pixels
const PHASE_GAP = 16;

// Snapping grid size for device placement
const GRID_SIZE = 20;

// Short display labels for each device type
const TYPE_ABBREV = {
  CircuitBreaker: "CB",
  VoltageSource: "VS",
  Disconnect: "DS",
  PowerTransformer: "TX",
  Load: "LD",
  Wire: "W",
  Bus: "BUS",
  CurrentTransformer: "CT",
  PowerLine: "PL",
  Relay: "RLY",
  CTTB: "CTTB",
  FTBlock: "FT",
  IsoBlock: "ISO",
  VoltageTransformer: "VT",
  DualWindingVT: "DVT",
};

/**
 * Maps telemetry keys to their engineering units.
 */
const unitsMap = {
  "Active Power": "W",
  "Reactive Power": "var",
  "Apparent Power": "VA",
  "Line Voltage (LL)": "V",
  "Phase Voltage (LN)": "V",
  Current: "A",
  "3-Phase Current": "A",
  "Phase A Voltage (LN)": "V",
  "Phase B Voltage (LN)": "V",
  "Phase C Voltage (LN)": "V",
  "Phase A-B Voltage": "V",
  "Phase B-C Voltage": "V",
  "Phase C-A Voltage": "V",
  "Phase A V-Angle": "deg",
  "Phase B V-Angle": "deg",
  "Phase C V-Angle": "deg",
  "Phase A-B V-Angle": "deg",
  "Phase B-C V-Angle": "deg",
  "Phase C-A V-Angle": "deg",
  "Phase AB V-Angle": "deg",
  "Phase BC V-Angle": "deg",
  "Phase CA V-Angle": "deg",
  "Phase A Current": "A",
  "Phase B Current": "A",
  "Phase C Current": "A",
  "Phase A I-Angle": "deg",
  "Phase B I-Angle": "deg",
  "Phase C I-Angle": "deg",
  "Phase A Active Power":   "W",
  "Phase B Active Power":   "W",
  "Phase C Active Power":   "W",
  "Phase A Reactive Power": "var",
  "Phase B Reactive Power": "var",
  "Phase C Reactive Power": "var",
  "Phase A Apparent Power": "VA",
  "Phase B Apparent Power": "VA",
  "Phase C Apparent Power": "VA",
  "Phase A Active Power (LL·I)":   "W",
  "Phase B Active Power (LL·I)":   "W",
  "Phase C Active Power (LL·I)":   "W",
  "Phase A Reactive Power (LL·I)": "var",
  "Phase B Reactive Power (LL·I)": "var",
  "Phase C Reactive Power (LL·I)": "var",
  "Phase A Apparent Power (LL·I)": "VA",
  "Phase B Apparent Power (LL·I)": "VA",
  "Phase C Apparent Power (LL·I)": "VA",
  "Pri Phase A Voltage": "V",
  "Pri Phase B Voltage": "V",
  "Pri Phase C Voltage": "V",
  "Pri Phase A Voltage (LN)": "V",
  "Pri Phase B Voltage (LN)": "V",
  "Pri Phase C Voltage (LN)": "V",
  "Pri Phase A Voltage (LL)": "V",
  "Pri Phase B Voltage (LL)": "V",
  "Pri Phase C Voltage (LL)": "V",
  "Pri Phase A V-Angle": "deg",
  "Pri Phase B V-Angle": "deg",
  "Pri Phase C V-Angle": "deg",
  "Pri Phase A Current": "A",
  "Pri Phase B Current": "A",
  "Pri Phase C Current": "A",
  "Pri Phase A I-Angle": "deg",
  "Pri Phase B I-Angle": "deg",
  "Pri Phase C I-Angle": "deg",
  "Sec Current Phase A": "A",
  "Sec Current Phase B": "A",
  "Sec Current Phase C": "A",
  "Sec Voltage Phase A": "V",
  "Sec Voltage Phase B": "V",
  "Sec Voltage Phase C": "V",
  "Sec Voltage Phase AB": "V",
  "Sec Voltage Phase BC": "V",
  "Sec Voltage Phase CA": "V",
  "Sec2 Voltage Phase A": "V",
  "Sec2 Voltage Phase B": "V",
  "Sec2 Voltage Phase C": "V",
  "Sec2 Voltage Phase AB": "V",
  "Sec2 Voltage Phase BC": "V",
  "Sec2 Voltage Phase CA": "V",
  "Phase A W2 V-Angle": "deg",
  "Phase B W2 V-Angle": "deg",
  "Phase C W2 V-Angle": "deg",
  "Phase AB W2 V-Angle": "deg",
  "Phase BC W2 V-Angle": "deg",
  "Phase CA W2 V-Angle": "deg",
  "Manual Phase A Voltage": "V",
  "Manual Phase B Voltage": "V",
  "Manual Phase C Voltage": "V",
  "Manual Phase A V-Angle": "deg",
  "Manual Phase B V-Angle": "deg",
  "Manual Phase C V-Angle": "deg",
  "Manual Phase A Current": "A",
  "Manual Phase B Current": "A",
  "Manual Phase C Current": "A",
  "Manual Phase A I-Angle": "deg",
  "Manual Phase B I-Angle": "deg",
  "Manual Phase C I-Angle": "deg",
};

/**
 * 360° lag-angle convention. When true, all angle displays are normalised to
 * [0, 360) — relays and protection engineers prefer this since negative angles
 * never appear. When false, raw signed values from the engine are shown.
 */
let _use360Lag = true;
function _lagAngle(deg) {
  return _use360Lag ? ((deg % 360) + 360) % 360 : deg;
}
function _fmtAngle(deg) {
  return _lagAngle(deg).toFixed(1) + "°";
}

/**
 * Formats numbers into human-readable SI notation (k, M, G, etc.)
 * @param {number} value - The raw number
 * @param {string} unit - The unit string (e.g., 'V', 'A')
 * @returns {string} Formatted string (e.g., "132.79 kV")
 */
function formatSI(value, unit) {
  if (unit === "deg") return _lagAngle(value).toFixed(1) + "°";
  if (value === 0 || value === undefined || isNaN(value))
    return "0.00 " + (unit || "");

  const absVal = Math.abs(value);
  // Find the power of 1000
  const exponent = Math.floor(Math.log10(absVal) / 3) * 3;

  const prefixes = {
    12: "T",
    9: "G",
    6: "M",
    3: "k",
    0: "",
    "-3": "m",
  };

  const prefix = prefixes[exponent.toString()] || "";
  const scaled = value / Math.pow(10, exponent);

  return `${scaled.toFixed(2)} ${prefix}${unit || ""}`;
}

/**
 * Snaps a coordinate to the predefined grid.
 */
function snapToGrid(coord) {
  return Math.round(coord / GRID_SIZE) * GRID_SIZE;
}
