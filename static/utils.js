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
  VoltageSource: "VS",
  CircuitBreaker: "CB",
  Disconnect: "DS",
  PowerTransformer: "TX",
  VoltageRegulator: "REG",
  Load: "LD",
  Wire: "W",
  Bus: "BUS",
  CurrentTransformer: "CT",
  VoltageTransformer: "VT",
  DualWindingVT: "DVT",
  PowerLine: "PL",
  Line: "L",
  Relay: "RLY",
  CTTB: "CTTB",
  FTBlock: "FT",
  IsoBlock: "ISO",
  AuxiliaryTransformer: "AUX",
  Meter: "MTR",
  Indicator: "IND",
  ShuntCapacitor: "CAP",
  ShuntReactor: "RCT",
  SurgeArrester: "SA",
  SeriesCapacitor: "SC",
  SeriesReactor: "SR",
  NeutralGroundingResistor: "NGR",
  SVC: "SVC",
  LineTrap: "LT",
};

// Full display names for each device type (used in selection panels, reports)
const TYPE_LABELS = {
  VoltageSource: "SOURCE",
  CircuitBreaker: "BREAKER",
  Disconnect: "DISCONNECT",
  PowerTransformer: "TRANSFORMER",
  VoltageRegulator: "VOLTAGE REGULATOR",
  CurrentTransformer: "CT",
  VoltageTransformer: "VT",
  DualWindingVT: "VT (DUAL)",
  Bus: "BUS",
  PowerLine: "LINE",
  Line: "LINE",
  Load: "LOAD",
  Relay: "RELAY",
  CTTB: "CTTB",
  FTBlock: "FT BLOCK",
  IsoBlock: "ISO BLOCK",
  AuxiliaryTransformer: "AUX TX",
  Meter: "POWER METER",
  Indicator: "INDICATOR LIGHT",
  ShuntCapacitor: "SHUNT CAP",
  ShuntReactor: "SHUNT RCT",
  SurgeArrester: "SURGE ARR",
  SeriesCapacitor: "SC",
  SeriesReactor: "SERIES RCT",
  NeutralGroundingResistor: "NGR",
  SVC: "SVC",
  LineTrap: "LINE TRAP",
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
 * Formats numbers into human-readable SI notation (k, M, G, etc.)
 * @param {number} value - The raw number
 * @param {string} unit - The unit string (e.g., 'V', 'A')
 * @returns {string} Formatted string (e.g., "132.79 kV")
 */
function formatSI(value, unit) {
  if (unit === "deg") return value.toFixed(1) + "°";
  if (value === 0 || value === undefined || isNaN(value))
    return "0.00 " + (unit || "");

  const absVal = Math.abs(value);
  
  // For extremely small values, just return 0
  if (absVal < 1e-15) return "0.00 " + (unit || "");

  // Find the power of 1000
  let exponent = Math.floor(Math.log10(absVal) / 3) * 3;

  const prefixes = {
    12: "T",
    9: "G",
    6: "M",
    3: "k",
    0: "",
    "-3": "m",
    "-6": "μ",
    "-9": "n",
    "-12": "p",
  };

  // If the exponent is not in our prefix list, fallback to scientific notation
  // or clamp to the nearest supported prefix if appropriate.
  if (!(exponent.toString() in prefixes)) {
    if (exponent > 12) exponent = 12;
    else if (exponent < -12) return value.toExponential(2) + " " + (unit || "");
    else exponent = 0; // Fallback to 0 if something is weird
  }

  const prefix = prefixes[exponent.toString()];
  const scaled = value / Math.pow(10, exponent);

  return `${scaled.toFixed(2)} ${prefix}${unit || ""}`;
}

/**
 * Snaps a coordinate to the predefined grid.
 */
function snapToGrid(coord) {
  return Math.round(coord / GRID_SIZE) * GRID_SIZE;
}
