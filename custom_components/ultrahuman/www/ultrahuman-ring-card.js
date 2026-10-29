/**
 * Ultrahuman Cards v5 - Custom Lovelace Cards for Home Assistant
 * Compact dashboard design with HA theme integration and sparkline graphs
 * Includes: all-in-one card, 6 daily metric cards, and a Home environmental card
 */

const CARD_VERSION = "5.0.0";

/* ══════════════════════ SVG LOGO ══════════════════════ */
const UH_LOGO_SVG = `<svg viewBox="0 0 180 16" width="120" height="12" xmlns="http://www.w3.org/2000/svg">
  <text x="0" y="13" font-family="-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
    font-size="13" font-weight="800" letter-spacing="3" fill="currentColor">ULTRAHUMAN</text>
</svg>`;

/* ══════════════════════ UTILITY FUNCTIONS ══════════════════════ */

function uhGetState(hass, prefix, key) {
  const entityId = `${prefix}_${key}`;
  const entity = hass?.states?.[entityId];
  if (!entity || entity.state === "unknown" || entity.state === "unavailable") {
    return null;
  }
  return entity.state;
}

function uhGetNumericState(hass, prefix, key) {
  const val = uhGetState(hass, prefix, key);
  if (val === null || val === "None" || String(val).trim() === "") return null;
  const num = Number(val);
  return Number.isFinite(num) ? num : null;
}

function uhGetScoreColor(score) {
  if (score === null) return "var(--uh-muted)";
  if (score >= 80) return "var(--uh-green)";
  if (score >= 60) return "var(--uh-yellow)";
  if (score >= 40) return "var(--uh-orange)";
  return "var(--uh-red)";
}

function uhGetScoreColorRaw(score) {
  if (score === null) return "#46494D";
  if (score >= 80) return "#0EFF27";
  if (score >= 60) return "#FCDD00";
  if (score >= 40) return "#FD9400";
  return "#FF4500";
}

function uhGetScoreLabel(score) {
  if (score === null) return "";
  if (score >= 80) return "Optimal";
  if (score >= 60) return "Good";
  if (score >= 40) return "Needs attention";
  return "Low";
}

function uhEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

function uhGetAttributes(hass, prefix, key) {
  return hass?.states?.[`${prefix}_${key}`]?.attributes || {};
}

function uhGetUnit(hass, prefix, key, fallback = "") {
  return uhGetAttributes(hass, prefix, key).unit_of_measurement ?? fallback;
}

function uhFormatMinutesPlain(mins) {
  if (mins === null) return "--";
  const rounded = Math.round(mins);
  return `${Math.floor(rounded / 60)}h ${rounded % 60}m`;
}

function uhFormatDuration(hass, prefix, key) {
  const value = uhGetNumericState(hass, prefix, key);
  if (value === null) return "--";
  const unit = uhGetUnit(hass, prefix, key, "min");
  const factors = { s: 1 / 60, min: 1, h: 60, d: 1440 };
  return Object.hasOwn(factors, unit)
    ? uhFormatMinutesPlain(value * factors[unit])
    : `${value} ${unit}`;
}

const UH_DAILY_ADDITIONS = {
  glucose: { label: "LATEST GLUCOSE", unit: "mg/dL" },
  sleep_rhr: { label: "SLEEP RESTING HR", unit: "bpm" },
  avg_sleep_hrv: { label: "SLEEP HRV", unit: "ms" },
  active_minutes: { label: "ACTIVE MINUTES", unit: "min" },
  time_in_bed: { label: "TIME IN BED", duration: true },
  temperature_deviation: { label: "TEMPERATURE DEVIATION", unit: "°C" },
  hr_drop: { label: "HEART RATE DROP", unit: "bpm" },
  movements: { label: "MOVEMENTS", unit: "count" },
  morning_alertness: { label: "MORNING ALERTNESS", unit: "score" },
  full_sleep_cycles: { label: "COMPLETE SLEEP CYCLES", unit: "cycles" },
  tosses_and_turns: { label: "TOSSES AND TURNS", unit: "count" },
  average_body_temperature: { label: "AVERAGE BODY TEMPERATURE", unit: "°C" },
  inactive_time: { label: "INACTIVE TIME", unit: "" },
  weekly_active_minutes: { label: "WEEKLY ACTIVE MINUTES", unit: "min" },
  sleep_movements: { label: "SLEEP MOVEMENTS", unit: "count" },
  restorative_sleep_percentage: { label: "RESTORATIVE SLEEP", unit: "%" },
  hr_drop_time: { label: "HEART RATE DROP TIME", text: true },
  morning_alertness_minutes: { label: "MORNING ALERTNESS DURATION", duration: true },
};

const UH_HOME_METRICS = [
  ["aqi", "AIR QUALITY INDEX"], ["co2", "CARBON DIOXIDE"],
  ["pm25", "PM2.5"], ["pm10", "PM10"], ["pm1", "PM1"],
  ["voc", "VOLATILE ORGANIC COMPOUNDS"], ["hcho", "FORMALDEHYDE"],
  ["co", "CARBON MONOXIDE"], ["temp", "TEMPERATURE"],
  ["humidity", "HUMIDITY"], ["noise", "NOISE"],
  ["mic", "MICROPHONE ANALYSIS"], ["uva", "UVA"], ["uvb", "UVB"],
  ["uvc", "UVC"], ["red", "RED LIGHT"], ["green", "GREEN LIGHT"],
  ["blue", "BLUE LIGHT"], ["ir", "INFRARED"],
];
const UH_HOME_PRIMARY_COUNT = 11;

/* ══════════════════════ SPARKLINE HELPERS ══════════════════════ */

const UH_HISTORY_CACHE = new Map();
const UH_HISTORY_TTL = 5 * 60 * 1000;

async function uhFetchHistory(hass, entityId) {
  const now = Date.now();
  const cached = UH_HISTORY_CACHE.get(entityId);
  if (cached && (now - cached.ts) < UH_HISTORY_TTL) return cached.data;

  try {
    const result = await hass.callWS({
      type: "history/history_during_period",
      start_time: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
      end_time: new Date().toISOString(),
      entity_ids: [entityId],
      minimal_response: true,
      significant_changes_only: true,
    });
    const states = result?.[entityId] || [];
    const points = [];
    for (const s of states) {
      if (s.s == null || String(s.s).trim() === "") continue;
      const val = Number(s.s);
      if (Number.isFinite(val)) {
        points.push({ t: s.lu, v: val });
      }
    }
    UH_HISTORY_CACHE.set(entityId, { ts: now, data: points });
    return points;
  } catch {
    return [];
  }
}

function uhRenderSparklineSVG(points, color) {
  if (!points || points.length < 2) return "";
  const vals = points.map(p => p.v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const w = 300, h = 50;
  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * w;
    const y = h - ((p.v - min) / range) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return `
  <svg viewBox="0 0 ${w} ${h}" class="sparkline" preserveAspectRatio="none">
    <polyline points="${coords}" fill="none" stroke="${color}" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
  </svg>
  `;
}

/* ══════════════════════ METRIC ROW BUILDER ══════════════════════ */

function uhMetricRow(label, value, unit, scoreColor, statusLabel, sparklineHtml) {
  const badge = statusLabel
    ? `<span class="status-badge" style="color:${scoreColor};background:${scoreColor}22">${uhEscape(statusLabel)}</span>`
    : "";
  return `
  <div class="metric-row">
    <div class="metric-header">
      <span class="metric-label">${uhEscape(label)}</span>
      <span class="metric-value">${uhEscape(value)}${unit ? `<span class="metric-unit"> ${uhEscape(unit)}</span>` : ""}${badge}</span>
    </div>
    ${sparklineHtml ? `<div class="metric-graph">${sparklineHtml}</div>` : ""}
  </div>
  `;
}

/* ══════════════════════ SNAPSHOT PILL ══════════════════════ */

function uhSnapshotPill(iconName, value, unit) {
  const icons = {
    "thermometer": `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M15 13V5c0-1.66-1.34-3-3-3S9 3.34 9 5v8c-1.21.91-2 2.37-2 4 0 2.76 2.24 5 5 5s5-2.24 5-5c0-1.63-.79-3.09-2-4m-4-8c0-.55.45-1 1-1s1 .45 1 1v3h-2V5z"/></svg>`,
    "oxygen": `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2m0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8m-1-6.5c0 .83-.67 1.5-1.5 1.5S8 14.33 8 13.5v-3C8 9.67 8.67 9 9.5 9s1.5.67 1.5 1.5v3m5.5 0c0 .83-.67 1.5-1.5 1.5s-1.5-.67-1.5-1.5v-3c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5v3z"/></svg>`,
    "shoe-print": `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2M9.8 8.9 7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3C14.8 12 16.8 13 19 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6l1.8-.7"/></svg>`,
    "heart-pulse": `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>`,
    "wave": `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M3 12h4l3-9 4 18 3-9h4"/><path fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" d="M3 12h4l3-9 4 18 3-9h4"/></svg>`,
  };
  return `
  <div class="snapshot-pill">
    <div class="pill-icon">${icons[iconName] || ""}</div>
    <div class="pill-value">${uhEscape(value)}</div>
    <div class="pill-unit">${uhEscape(unit)}</div>
  </div>
  `;
}

/* ══════════════════════ CSS ══════════════════════ */

function uhStyles() {
  return `
    :host {
      --uh-card-bg: var(--ha-card-background, var(--card-background-color, #1a1a1a));
      --uh-text: var(--primary-text-color, #fff);
      --uh-text-secondary: var(--secondary-text-color, #999);
      --uh-surface: var(--secondary-background-color, rgba(255,255,255,0.06));
      --uh-border: var(--divider-color, rgba(255,255,255,0.06));
      --uh-border-radius: var(--ha-card-border-radius, 12px);
      --uh-muted: #46494D;
      --uh-green: #0EFF27;
      --uh-yellow: #FCDD00;
      --uh-orange: #FD9400;
      --uh-red: #FF4500;
    }

    ha-card {
      background: var(--uh-card-bg);
      border-radius: var(--uh-border-radius);
      overflow: hidden;
      font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif);
      -webkit-font-smoothing: antialiased;
      color: var(--uh-text);
    }

    .uh-card { padding: 16px; }

    /* ── Header ── */
    .uh-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .uh-brand {
      line-height: 0;
      color: var(--uh-text-secondary);
    }
    .uh-refresh-btn {
      background: none;
      border: none;
      color: var(--uh-text-secondary);
      cursor: pointer;
      padding: 6px;
      border-radius: 50%;
      display: flex;
      transition: all 0.2s;
    }
    .uh-refresh-btn:hover { color: var(--uh-green); background: rgba(14,255,39,0.08); }
    .uh-refresh-btn.spinning svg { animation: uhSpin 1s linear infinite; }
    @keyframes uhSpin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }

    .refresh-error { color: var(--error-color, #db4437); font-size: 0.8em; margin-bottom: 8px; }
    .home-title { font-size: 1em; margin: 0 0 6px; }
    .reading-time { font-size: 0.75em; color: var(--uh-text-secondary); margin-bottom: 12px; }
    details > summary { cursor: pointer; font-size: 0.8em; color: var(--uh-text-secondary); margin: 12px 0 8px; }
    .uh-refresh-btn:disabled { cursor: wait; }

    /* ── Metric Row ── */
    .metric-row {
      background: var(--uh-surface);
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 8px;
    }
    .metric-row:last-child { margin-bottom: 0; }
    .metric-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .metric-label {
      font-size: 0.75em;
      color: var(--uh-text-secondary);
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .metric-value {
      font-size: 1em;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .metric-unit {
      font-size: 0.7em;
      font-weight: 400;
      opacity: 0.7;
    }
    .status-badge {
      font-size: 0.7em;
      font-weight: 500;
      margin-left: 6px;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .metric-graph {
      margin-top: 6px;
    }
    .sparkline {
      width: 100%;
      height: 40px;
      display: block;
    }

    /* ── Metric Grid (2-col) ── */
    .metric-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .metric-grid .metric-row {
      margin-bottom: 0;
    }
    .metric-grid .metric-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 2px;
    }
    .metric-grid .metric-value {
      font-size: 1.1em;
    }

    /* ── Section ── */
    .section-gap { margin-top: 12px; }

    /* ── Ring Hero ── */
    .uh-ring-hero {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 4px 0 12px 0;
    }
    .ring-svg { width: 130px; height: 130px; }
    .arc { transition: stroke-dasharray 0.8s ease-out; }
    .ring-legend {
      display: flex;
      gap: 14px;
      margin-top: 6px;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .legend-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .legend-label {
      font-size: 0.7em;
      color: var(--uh-text-secondary);
      font-weight: 500;
    }

    /* ── Snapshot ── */
    .uh-snapshot {
      margin-bottom: 12px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--uh-border);
    }
    .snapshot-title {
      font-size: 0.85em;
      font-weight: 600;
      color: var(--uh-text);
      margin-bottom: 8px;
    }
    .snapshot-row {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
      padding-bottom: 2px;
    }
    .snapshot-row::-webkit-scrollbar { display: none; }
    .snapshot-pill {
      flex: 0 0 auto;
      min-width: 62px;
      background: var(--uh-surface);
      border-radius: 12px;
      padding: 10px 10px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
    }
    .pill-icon {
      line-height: 0;
      color: var(--uh-text-secondary);
    }
    .pill-value {
      font-size: 0.9em;
      font-weight: 700;
      color: var(--uh-text);
      font-variant-numeric: tabular-nums;
    }
    .pill-unit {
      font-size: 0.65em;
      color: var(--uh-text-secondary);
      font-weight: 500;
    }

    /* ── Sleep Stage Bar ── */
    .sleep-bar {
      display: flex;
      height: 5px;
      border-radius: 3px;
      overflow: hidden;
      gap: 1px;
      margin-bottom: 6px;
    }
    .bar-seg { border-radius: 3px; min-width: 2px; }
    .bar-seg.deep { background: #4A6CF7; }
    .bar-seg.light { background: #0EFF27; }
    .bar-seg.rem { background: #00CFCF; }
    .bar-seg.awake { background: #555; }
    .sleep-stages {
      display: flex;
      flex-wrap: wrap;
      gap: 4px 10px;
      margin-bottom: 8px;
    }
    .stage {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 0.7em;
      color: var(--uh-text-secondary);
      font-weight: 500;
    }
    .stage-dot {
      width: 5px;
      height: 5px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .stage-dot.deep { background: #4A6CF7; }
    .stage-dot.light { background: #0EFF27; }
    .stage-dot.rem { background: #00CFCF; }
    .stage-dot.awake { background: #555; }

    /* ── Footer ── */
    .uh-footer {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 6px;
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid var(--uh-border);
    }
    .footer-icon {
      line-height: 0;
      color: var(--uh-text-secondary);
    }
    .footer-text {
      font-size: 0.6em;
      letter-spacing: 1.5px;
      color: var(--uh-text-secondary);
      text-transform: uppercase;
      font-weight: 500;
    }

    /* ── No Data ── */
    .no-data {
      font-size: 0.85em;
      color: var(--uh-text-secondary);
      text-align: center;
      padding: 16px 0;
    }

    /* ── Responsive ── */
    @media (max-width: 360px) {
      .metric-grid { grid-template-columns: 1fr; }
      .ring-legend {
        flex-direction: column;
        gap: 3px;
        align-items: center;
      }
    }
  `;
}

/* ══════════════════════ RENDER HELPERS ══════════════════════ */

function uhRenderRingSVG(hass, prefix) {
  const sleep = uhGetNumericState(hass, prefix, "sleep_score");
  const recovery = uhGetNumericState(hass, prefix, "recovery_index");
  const movement = uhGetNumericState(hass, prefix, "movement_index");

  const r1 = 86, r2 = 74, r3 = 62;
  const c1 = 2 * Math.PI * r1, c2 = 2 * Math.PI * r2, c3 = 2 * Math.PI * r3;
  const d1 = (sleep !== null ? sleep / 100 : 0) * c1;
  const d2 = (recovery !== null ? recovery / 100 : 0) * c2;
  const d3 = (movement !== null ? movement / 100 : 0) * c3;

  return `
  <svg viewBox="0 0 200 200" class="ring-svg" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="rg1" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#2A2D2B"/>
        <stop offset="50%" stop-color="#1A1C1B"/>
        <stop offset="100%" stop-color="#2E3230"/>
      </linearGradient>
      <filter id="rs"><feDropShadow dx="0" dy="3" stdDeviation="6" flood-color="#000" flood-opacity="0.4"/></filter>
      <filter id="ag"><feGaussianBlur stdDeviation="1.5" result="g"/><feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <circle cx="100" cy="100" r="80" fill="none" stroke="url(#rg1)" stroke-width="22" filter="url(#rs)" opacity="0.35"/>
    <circle cx="100" cy="100" r="${r1}" fill="none" stroke="#1A1C1B" stroke-width="6"/>
    <circle cx="100" cy="100" r="${r2}" fill="none" stroke="#1A1C1B" stroke-width="6"/>
    <circle cx="100" cy="100" r="${r3}" fill="none" stroke="#1A1C1B" stroke-width="6"/>
    <circle cx="100" cy="100" r="${r1}" fill="none"
      stroke="${uhGetScoreColorRaw(sleep)}" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="${d1} ${c1}" transform="rotate(-90 100 100)" filter="url(#ag)" class="arc"/>
    <circle cx="100" cy="100" r="${r2}" fill="none"
      stroke="${uhGetScoreColorRaw(recovery)}" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="${d2} ${c2}" transform="rotate(-90 100 100)" filter="url(#ag)" class="arc"/>
    <circle cx="100" cy="100" r="${r3}" fill="none"
      stroke="${uhGetScoreColorRaw(movement)}" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="${d3} ${c3}" transform="rotate(-90 100 100)" filter="url(#ag)" class="arc"/>
    <circle cx="100" cy="100" r="52" fill="#0A0A0A"/>
    <path d="M100 78 C108 78 114 84 114 92 L114 108 C114 116 108 122 100 122 C92 122 86 116 86 108 L86 92 C86 84 92 78 100 78Z" fill="none" stroke="#3A3A3A" stroke-width="1.5"/>
    <circle cx="100" cy="88" r="3" fill="#3A3A3A"/>
  </svg>
  <div class="ring-legend">
    <div class="legend-item"><span class="legend-dot" style="background:${uhGetScoreColorRaw(sleep)}"></span><span class="legend-label">Sleep ${sleep ?? "--"}</span></div>
    <div class="legend-item"><span class="legend-dot" style="background:${uhGetScoreColorRaw(recovery)}"></span><span class="legend-label">Recovery ${recovery ?? "--"}</span></div>
    <div class="legend-item"><span class="legend-dot" style="background:${uhGetScoreColorRaw(movement)}"></span><span class="legend-label">Movement ${movement ?? "--"}</span></div>
  </div>
  `;
}

function uhRenderSnapshot(hass, prefix) {
  const temp = uhGetNumericState(hass, prefix, "skin_temperature");
  const spo2 = uhGetNumericState(hass, prefix, "spo2");
  const steps = uhGetNumericState(hass, prefix, "steps");
  const hr = uhGetNumericState(hass, prefix, "heart_rate");
  const hrv = uhGetNumericState(hass, prefix, "hrv");

  return `
  <div class="snapshot-title">Snapshot</div>
  <div class="snapshot-row">
    ${uhSnapshotPill("thermometer", temp !== null ? temp.toFixed(1) : "--", uhGetUnit(hass, prefix, "skin_temperature", "°C"))}
    ${uhSnapshotPill("oxygen", spo2 ?? "--", "%")}
    ${uhSnapshotPill("shoe-print", steps !== null ? Math.round(steps).toLocaleString() : "--", "steps")}
    ${uhSnapshotPill("heart-pulse", hr ?? "--", "bpm")}
    ${uhSnapshotPill("wave", hrv ?? "--", "ms")}
  </div>
  `;
}

function uhRenderFooter() {
  return `
  <div class="uh-footer">
    <span class="footer-icon">
      <svg viewBox="0 0 24 24" width="14" height="14"><path d="M12 4C14.2 4 16 5.8 16 8L16 16C16 18.2 14.2 20 12 20C9.8 20 8 18.2 8 16L8 8C8 5.8 9.8 4 12 4Z" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="7" r="1.5" fill="currentColor"/></svg>
    </span>
    <span class="footer-text">Ultrahuman Ring AIR</span>
  </div>
  `;
}

/* ══════════════════════ BASE CARD CLASS ══════════════════════ */

class UltrahumanCardBase extends HTMLElement {
  static get properties() {
    return { hass: {}, config: {} };
  }

  constructor() {
    super();
    this._sparklines = {};
    this._sparklinesPending = false;
    this._historyGeneration = 0;
    this._refreshing = false;
    this._refreshError = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (this._initialized) {
      this._updateValues();
      this._loadSparklines();
    }
  }

  setConfig(config) {
    if (!config.entity_prefix) {
      throw new Error("Please define entity_prefix (e.g. 'sensor.ultrahuman_ring')");
    }
    this._config = config;
    this._historyGeneration++;
    this._sparklines = {};
    this._sparklinesPending = false;
    this._refreshing = false;
    this._refreshError = "";
    this._initialized = false;
    this._render();
    this._initialized = true;
    this._loadSparklines();
  }

  get _prefix() {
    return this._config.entity_prefix;
  }

  _renderHeader() {
    return `
    <div class="uh-header">
      <span class="uh-brand">${UH_LOGO_SVG}</span>
      <button class="uh-refresh-btn${this._refreshing ? " spinning" : ""}" id="refreshBtn" title="Refresh data" ${this._refreshing ? "disabled" : ""}>
        <svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M17.65 6.35A7.96 7.96 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
      </button>
    </div>
    <div id="refreshError" class="refresh-error" role="alert" ${this._refreshError ? "" : "hidden"}>${uhEscape(this._refreshError)}</div>
    `;
  }

  _attachRefreshHandler() {
    const btn = this.shadowRoot ? this.shadowRoot.getElementById("refreshBtn") : null;
    if (btn) {
      btn.addEventListener("click", () => { this._refreshData(); });
    }
  }

  _setRefreshError(message) {
    this._refreshError = message;
    const error = this.shadowRoot?.getElementById("refreshError");
    if (error) {
      error.textContent = message;
      error.hidden = !message;
    }
  }

  async _refreshData() {
    if (!this._hass || this._refreshing) return;
    const metrics = this._getRefreshMetrics();
    const prefix = this._prefix;
    let generation = this._historyGeneration;
    const foundEntityId = metrics.map(key => `${prefix}_${key}`)
      .find(entityId => this._hass.states[entityId]);
    this._setRefreshError("");
    if (!foundEntityId) {
      this._setRefreshError("No configured sensor is available to refresh.");
      return;
    }
    this._refreshing = true;
    const btn = this.shadowRoot?.getElementById("refreshBtn");
    if (btn) {
      btn.classList.add("spinning");
      btn.disabled = true;
    }
    try {
      await this._hass.callService("homeassistant", "update_entity", { entity_id: foundEntityId });
      // Coordinator failures mark entities unavailable without rejecting the service.
      if (generation === this._historyGeneration
          && this._hass.states[foundEntityId]?.state === "unavailable") {
        throw new Error("The integration could not update its readings");
      }
      for (const key of metrics) UH_HISTORY_CACHE.delete(`${prefix}_${key}`);
      if (generation === this._historyGeneration) {
        // Discard history requests started before this refresh completed.
        generation = ++this._historyGeneration;
        this._sparklinesPending = false;
        this._updateValues();
        await this._loadSparklines();
      }
    } catch {
      if (generation === this._historyGeneration) {
        this._setRefreshError("Unable to refresh data. Check the integration and try again.");
      }
    } finally {
      if (generation === this._historyGeneration) this._refreshing = false;
      if (btn) {
        btn.classList.remove("spinning");
        btn.disabled = false;
      }
    }
  }

  _getRefreshMetrics() {
    return [
      "sleep_score", "total_sleep", "sleep_efficiency", "deep_sleep",
      "rem_sleep", "light_sleep", "restorative_sleep", "spo2",
      "heart_rate", "resting_heart_rate", "hrv",
      "skin_temperature", "steps",
      "metabolic_score", "glucose_variability", "average_glucose",
      "hba1c", "time_in_target",
      "recovery_index", "movement_index", "vo2_max",
      ...Object.keys(UH_DAILY_ADDITIONS),
    ];
  }

  _getSparklineEntities() {
    return [];
  }

  async _loadSparklines() {
    if (!this._hass || this._sparklinesPending) return;
    const entities = this._getSparklineEntities()
      .filter(key => this._hass.states[`${this._prefix}_${key}`]);
    if (entities.length === 0) return;
    const generation = this._historyGeneration;
    this._sparklinesPending = true;
    try {
      const results = await Promise.all(
        entities.map(key => uhFetchHistory(this._hass, `${this._prefix}_${key}`))
      );
      if (generation !== this._historyGeneration) return;
      let changed = false;
      entities.forEach((key, i) => {
        const old = this._sparklines[key];
        const nw = results[i];
        if (!old || old.length !== nw.length || (nw.length > 0 && old[old.length-1]?.v !== nw[nw.length-1]?.v)) {
          this._sparklines[key] = nw;
          changed = true;
        }
      });
      if (changed) this._updateSparklines();
    } finally {
      if (generation === this._historyGeneration) this._sparklinesPending = false;
    }
  }

  _getSparklineHtml(key, color) {
    return uhRenderSparklineSVG(this._sparklines[key], color);
  }

  _renderAdditionalMetrics(keys) {
    return keys.map(key => {
      const metric = UH_DAILY_ADDITIONS[key];
      const value = metric.text
        ? uhGetState(this._hass, this._prefix, key)
        : uhGetNumericState(this._hass, this._prefix, key);
      if (value === null || (metric.text && (value === "None" || !String(value).trim()))) return "";
      return uhMetricRow(metric.label,
        metric.duration ? uhFormatDuration(this._hass, this._prefix, key) : value,
        metric.duration || metric.text ? "" : uhGetUnit(this._hass, this._prefix, key, metric.unit),
        "", "", "");
    }).join("");
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${uhStyles()}</style><ha-card><div class="uh-card">${this._renderHeader()}<div id="contentArea">${this._renderContent()}</div></div></ha-card>`;
    this._attachRefreshHandler();
  }

  _updateValues() {
    const content = this.shadowRoot?.getElementById("contentArea");
    if (content && this._hass) content.innerHTML = this._renderContent();
  }
  _updateSparklines() { this._updateValues(); }
}

/* ══════════════════════ ALL-IN-ONE CARD ══════════════════════ */

class UltrahumanRingCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 10; }

  _getSparklineEntities() {
    return ["sleep_score", "movement_index", "recovery_index", "heart_rate", "metabolic_score"];
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    container.id = "uhRoot";
    card.appendChild(container);
    root.appendChild(card);
    this._rebuildContent();
    this._attachRefreshHandler();
  }

  _rebuildContent() {
    const container = this.shadowRoot ? this.shadowRoot.getElementById("uhRoot") : null;
    if (!container) return;
    container.textContent = "";

    // Header
    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);

    // Ring hero
    const ringDiv = document.createElement("div");
    ringDiv.className = "uh-ring-hero";
    ringDiv.id = "ringHero";
    ringDiv.innerHTML = uhRenderRingSVG(this._hass, this._prefix);
    container.appendChild(ringDiv);

    // Snapshot
    const snapDiv = document.createElement("div");
    snapDiv.className = "uh-snapshot";
    snapDiv.id = "snapshot";
    snapDiv.innerHTML = uhRenderSnapshot(this._hass, this._prefix);
    container.appendChild(snapDiv);

    // Metrics
    const metricsDiv = document.createElement("div");
    metricsDiv.id = "metricsArea";
    metricsDiv.innerHTML = this._renderMetrics();
    container.appendChild(metricsDiv);

    // Footer
    const footerDiv = document.createElement("div");
    footerDiv.innerHTML = uhRenderFooter();
    while (footerDiv.firstChild) container.appendChild(footerDiv.firstChild);
  }

  _renderMetrics() {
    const h = this._hass, p = this._prefix;
    const sleep = uhGetNumericState(h, p, "sleep_score");
    const movement = uhGetNumericState(h, p, "movement_index");
    const recovery = uhGetNumericState(h, p, "recovery_index");
    const hr = uhGetNumericState(h, p, "heart_rate");
    const rhr = uhGetNumericState(h, p, "resting_heart_rate");
    const hrv = uhGetNumericState(h, p, "hrv");
    const spo2 = uhGetNumericState(h, p, "spo2");
    const metabolic = uhGetNumericState(h, p, "metabolic_score");

    const additions = this._renderAdditionalMetrics(Object.keys(UH_DAILY_ADDITIONS));
    const expanded = this.shadowRoot?.getElementById("dailyDetails")?.open;
    return [
      uhMetricRow("SLEEP SCORE", sleep ?? "--", "", uhGetScoreColorRaw(sleep), uhGetScoreLabel(sleep), this._getSparklineHtml("sleep_score", uhGetScoreColorRaw(sleep))),
      uhMetricRow("MOVEMENT", movement ?? "--", "", uhGetScoreColorRaw(movement), uhGetScoreLabel(movement), this._getSparklineHtml("movement_index", uhGetScoreColorRaw(movement))),
      uhMetricRow("RECOVERY", recovery ?? "--", "", uhGetScoreColorRaw(recovery), uhGetScoreLabel(recovery), this._getSparklineHtml("recovery_index", uhGetScoreColorRaw(recovery))),
      uhMetricRow("HEART RATE", hr ?? "--", "bpm", uhGetScoreColorRaw(null), "", this._getSparklineHtml("heart_rate", "var(--uh-text-secondary)")),
      `<div class="metric-grid">`,
      uhMetricRow("RESTING HR", rhr ?? "--", "bpm", "", "", ""),
      uhMetricRow("HRV", hrv ?? "--", "ms", "", "", ""),
      uhMetricRow("SpO2", spo2 ?? "--", "%", "", "", ""),
      uhMetricRow("METABOLIC", metabolic ?? "--", "", uhGetScoreColorRaw(metabolic), uhGetScoreLabel(metabolic), ""),
      `</div>`,
      additions ? `<details id="dailyDetails" ${expanded ? "open" : ""}><summary>More daily readings</summary><div class="metric-grid">${additions}</div></details>` : "",
    ].join("");
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const ring = this.shadowRoot.getElementById("ringHero");
    if (ring) ring.innerHTML = uhRenderRingSVG(this._hass, this._prefix);
    const snap = this.shadowRoot.getElementById("snapshot");
    if (snap) snap.innerHTML = uhRenderSnapshot(this._hass, this._prefix);
    const metrics = this.shadowRoot.getElementById("metricsArea");
    if (metrics) metrics.innerHTML = this._renderMetrics();
  }
}

/* ══════════════════════ OVERVIEW CARD ══════════════════════ */

class UltrahumanRingOverviewCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-overview-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 5; }

  _getRefreshMetrics() {
    return ["sleep_score", "recovery_index", "movement_index", "skin_temperature", "spo2", "steps", "heart_rate", "hrv"];
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    card.appendChild(container);

    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);

    const ringDiv = document.createElement("div");
    ringDiv.className = "uh-ring-hero";
    ringDiv.id = "ringHero";
    ringDiv.innerHTML = uhRenderRingSVG(this._hass, this._prefix);
    container.appendChild(ringDiv);

    const snapDiv = document.createElement("div");
    snapDiv.className = "uh-snapshot";
    snapDiv.id = "snapshot";
    snapDiv.innerHTML = uhRenderSnapshot(this._hass, this._prefix);
    container.appendChild(snapDiv);

    const footerDiv = document.createElement("div");
    footerDiv.innerHTML = uhRenderFooter();
    while (footerDiv.firstChild) container.appendChild(footerDiv.firstChild);

    root.appendChild(card);
    this._attachRefreshHandler();
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const ring = this.shadowRoot.getElementById("ringHero");
    if (ring) ring.innerHTML = uhRenderRingSVG(this._hass, this._prefix);
    const snap = this.shadowRoot.getElementById("snapshot");
    if (snap) snap.innerHTML = uhRenderSnapshot(this._hass, this._prefix);
  }
}

/* ══════════════════════ SLEEP CARD ══════════════════════ */

class UltrahumanRingSleepCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-sleep-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 5; }

  _getRefreshMetrics() {
    return ["sleep_score", "total_sleep", "sleep_efficiency", "deep_sleep", "rem_sleep", "light_sleep", "restorative_sleep", "resting_heart_rate", "time_in_bed", "temperature_deviation", "hr_drop", "hr_drop_time", "sleep_movements", "restorative_sleep_percentage", "morning_alertness", "morning_alertness_minutes", "full_sleep_cycles", "tosses_and_turns", "average_body_temperature"];
  }
  _getSparklineEntities() { return ["sleep_score", "total_sleep", "sleep_efficiency"]; }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    card.appendChild(container);

    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);

    const contentDiv = document.createElement("div");
    contentDiv.id = "contentArea";
    contentDiv.innerHTML = this._renderContent();
    container.appendChild(contentDiv);

    root.appendChild(card);
    this._attachRefreshHandler();
  }

  _renderContent() {
    const h = this._hass, p = this._prefix;
    const score = uhGetNumericState(h, p, "sleep_score");
    const efficiency = uhGetNumericState(h, p, "sleep_efficiency");
    const restorative = uhGetNumericState(h, p, "restorative_sleep");
    const rhr = uhGetNumericState(h, p, "resting_heart_rate");
    const validPercentage = value => typeof value === "number" && Number.isFinite(value)
      && value >= 0 && value <= 100;
    const stages = [["deep", "Deep"], ["light", "Light"], ["rem", "REM"]]
      .map(([key, label]) => ({
        key, label,
        attributes: uhGetAttributes(h, p, `${key}_sleep`),
        value: uhGetNumericState(h, p, `${key}_sleep`),
        duration: uhFormatDuration(h, p, `${key}_sleep`),
      }));
    // The complete stage breakdown can differ from the individual sleep summaries.
    // Use one reported percentage set consistently; never derive an Awake remainder.
    const percentageKey = stages.some(stage => validPercentage(stage.attributes.stage_percentage))
      ? "stage_percentage" : "percentage";
    for (const stage of stages) {
      const percentage = stage.attributes[percentageKey];
      stage.percentage = validPercentage(percentage) ? percentage : null;
    }
    const sleepAttributes = uhGetAttributes(h, p, "sleep_score");
    const awakePercentage = sleepAttributes.awake_percentage;
    const awakeMinutes = sleepAttributes.awake_minutes;
    const hasAwakeMinutes = typeof awakeMinutes === "number" && Number.isFinite(awakeMinutes) && awakeMinutes >= 0;
    if (validPercentage(awakePercentage) || hasAwakeMinutes) {
      stages.push({
        key: "awake", label: "Awake",
        percentage: validPercentage(awakePercentage) ? awakePercentage : null,
        value: hasAwakeMinutes ? awakeMinutes : null,
        duration: hasAwakeMinutes ? uhFormatMinutesPlain(awakeMinutes) : "--",
      });
    }
    const bar = stages.filter(stage => stage.percentage !== null)
      .map(stage => `<div class="bar-seg ${stage.key}" style="width:${stage.percentage}%"></div>`).join("");
    const legend = stages.filter(stage => stage.value !== null || stage.percentage !== null)
      .map(stage => `<span class="stage"><span class="stage-dot ${stage.key}"></span>${stage.label} ${stage.percentage !== null ? `${stage.percentage}%` : uhEscape(stage.duration)}</span>`).join("");
    return [
      uhMetricRow("SLEEP SCORE", score ?? "--", "", uhGetScoreColorRaw(score), uhGetScoreLabel(score), this._getSparklineHtml("sleep_score", uhGetScoreColorRaw(score))),
      bar ? `<div class="sleep-bar">${bar}</div>` : "",
      legend ? `<div class="sleep-stages">${legend}</div>` : "",
      `<div class="metric-grid">`,
      uhMetricRow("TOTAL SLEEP", uhFormatDuration(h, p, "total_sleep"), "", "", "", this._getSparklineHtml("total_sleep", "var(--uh-text-secondary)")),
      uhMetricRow("EFFICIENCY", efficiency ?? "--", uhGetUnit(h, p, "sleep_efficiency", "%"), "", "", this._getSparklineHtml("sleep_efficiency", "var(--uh-text-secondary)")),
      uhMetricRow("RESTORATIVE SCORE", restorative ?? "--", uhGetUnit(h, p, "restorative_sleep", "score"), uhGetScoreColorRaw(restorative), uhGetScoreLabel(restorative), ""),
      uhMetricRow("RESTING HR", rhr ?? "--", uhGetUnit(h, p, "resting_heart_rate", "bpm"), "", "", ""),
      this._renderAdditionalMetrics(["time_in_bed", "temperature_deviation", "hr_drop", "hr_drop_time", "sleep_movements", "restorative_sleep_percentage", "morning_alertness", "morning_alertness_minutes", "full_sleep_cycles", "tosses_and_turns", "average_body_temperature"]),
      `</div>`,
    ].join("");
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const el = this.shadowRoot.getElementById("contentArea");
    if (el) el.innerHTML = this._renderContent();
  }
}

/* ══════════════════════ MOVEMENT CARD ══════════════════════ */

class UltrahumanRingMovementCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-movement-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 3; }

  _getRefreshMetrics() { return ["movement_index", "steps", "vo2_max", "active_minutes", "weekly_active_minutes", "inactive_time"]; }
  _getSparklineEntities() { return ["movement_index", "steps"]; }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    card.appendChild(container);
    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);
    const contentDiv = document.createElement("div");
    contentDiv.id = "contentArea";
    contentDiv.innerHTML = this._renderContent();
    container.appendChild(contentDiv);
    root.appendChild(card);
    this._attachRefreshHandler();
  }

  _renderContent() {
    const h = this._hass, p = this._prefix;
    const score = uhGetNumericState(h, p, "movement_index");
    const steps = uhGetNumericState(h, p, "steps");
    const vo2 = uhGetNumericState(h, p, "vo2_max");
    return [
      uhMetricRow("MOVEMENT SCORE", score ?? "--", "", uhGetScoreColorRaw(score), uhGetScoreLabel(score), this._getSparklineHtml("movement_index", uhGetScoreColorRaw(score))),
      `<div class="metric-grid">`,
      uhMetricRow("STEPS", steps !== null ? Math.round(steps).toLocaleString() : "--", "", "", "", this._getSparklineHtml("steps", "var(--uh-text-secondary)")),
      uhMetricRow("VO2 MAX", vo2 ?? "--", "mL/kg/min", "", "", ""),
      `</div>`,
      this._renderAdditionalMetrics(["active_minutes", "weekly_active_minutes", "inactive_time"]),
    ].join("");
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const el = this.shadowRoot.getElementById("contentArea");
    if (el) el.innerHTML = this._renderContent();
  }
}

/* ══════════════════════ RECOVERY CARD ══════════════════════ */

class UltrahumanRingRecoveryCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-recovery-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 3; }

  _getRefreshMetrics() { return ["recovery_index", "hrv", "resting_heart_rate", "skin_temperature", "temperature_deviation", "average_body_temperature", "morning_alertness", "morning_alertness_minutes", "hr_drop_time", "restorative_sleep_percentage"]; }
  _getSparklineEntities() { return ["recovery_index", "hrv", "resting_heart_rate"]; }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    card.appendChild(container);
    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);
    const contentDiv = document.createElement("div");
    contentDiv.id = "contentArea";
    contentDiv.innerHTML = this._renderContent();
    container.appendChild(contentDiv);
    root.appendChild(card);
    this._attachRefreshHandler();
  }

  _renderContent() {
    const h = this._hass, p = this._prefix;
    const score = uhGetNumericState(h, p, "recovery_index");
    const hrv = uhGetNumericState(h, p, "hrv");
    const rhr = uhGetNumericState(h, p, "resting_heart_rate");
    const temp = uhGetNumericState(h, p, "skin_temperature");
    return [
      uhMetricRow("RECOVERY SCORE", score ?? "--", "", uhGetScoreColorRaw(score), uhGetScoreLabel(score), this._getSparklineHtml("recovery_index", uhGetScoreColorRaw(score))),
      uhMetricRow("HRV AVERAGE", hrv ?? "--", "ms", "", "", this._getSparklineHtml("hrv", "var(--uh-text-secondary)")),
      uhMetricRow("RESTING HEART RATE", rhr ?? "--", "bpm", "", "", this._getSparklineHtml("resting_heart_rate", "var(--uh-text-secondary)")),
      uhMetricRow("SKIN TEMPERATURE", temp !== null ? temp.toFixed(1) : "--", uhGetUnit(h, p, "skin_temperature", "°C"), "", "", ""),
      this._renderAdditionalMetrics(["temperature_deviation", "average_body_temperature", "morning_alertness", "morning_alertness_minutes", "hr_drop_time", "restorative_sleep_percentage"]),
    ].join("");
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const el = this.shadowRoot.getElementById("contentArea");
    if (el) el.innerHTML = this._renderContent();
  }
}

/* ══════════════════════ HEART CARD ══════════════════════ */

class UltrahumanRingHeartCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-heart-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 4; }

  _getRefreshMetrics() { return ["heart_rate", "resting_heart_rate", "hrv", "spo2", "sleep_rhr", "avg_sleep_hrv", "hr_drop"]; }
  _getSparklineEntities() { return ["heart_rate", "resting_heart_rate", "hrv", "spo2"]; }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    card.appendChild(container);
    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);
    const contentDiv = document.createElement("div");
    contentDiv.id = "contentArea";
    contentDiv.innerHTML = this._renderContent();
    container.appendChild(contentDiv);
    root.appendChild(card);
    this._attachRefreshHandler();
  }

  _renderContent() {
    const h = this._hass, p = this._prefix;
    const hr = uhGetNumericState(h, p, "heart_rate");
    const rhr = uhGetNumericState(h, p, "resting_heart_rate");
    const hrv = uhGetNumericState(h, p, "hrv");
    const spo2 = uhGetNumericState(h, p, "spo2");
    return [
      uhMetricRow("HEART RATE", hr ?? "--", "bpm", "", "", this._getSparklineHtml("heart_rate", "#FF4500")),
      uhMetricRow("RESTING HR", rhr ?? "--", "bpm", "", "", this._getSparklineHtml("resting_heart_rate", "var(--uh-text-secondary)")),
      uhMetricRow("HRV", hrv ?? "--", "ms", "", "", this._getSparklineHtml("hrv", "#0EFF27")),
      uhMetricRow("SpO2", spo2 ?? "--", "%", "", "", this._getSparklineHtml("spo2", "var(--uh-text-secondary)")),
      this._renderAdditionalMetrics(["sleep_rhr", "avg_sleep_hrv", "hr_drop"]),
    ].join("");
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const el = this.shadowRoot.getElementById("contentArea");
    if (el) el.innerHTML = this._renderContent();
  }
}

/* ══════════════════════ GLUCOSE CARD ══════════════════════ */

class UltrahumanRingGlucoseCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-ring-glucose-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_ring_your_email_com" }; }
  getCardSize() { return 3; }

  _getRefreshMetrics() { return ["glucose", "metabolic_score", "average_glucose", "glucose_variability", "hba1c", "time_in_target"]; }
  _getSparklineEntities() { return ["metabolic_score", "average_glucose"]; }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";
    const card = document.createElement("ha-card");
    const style = document.createElement("style");
    style.textContent = uhStyles();
    card.appendChild(style);
    const container = document.createElement("div");
    container.className = "uh-card";
    card.appendChild(container);
    const headerDiv = document.createElement("div");
    headerDiv.innerHTML = this._renderHeader();
    while (headerDiv.firstChild) container.appendChild(headerDiv.firstChild);
    const contentDiv = document.createElement("div");
    contentDiv.id = "contentArea";
    contentDiv.innerHTML = this._renderContent();
    container.appendChild(contentDiv);
    root.appendChild(card);
    this._attachRefreshHandler();
  }

  _renderContent() {
    const h = this._hass, p = this._prefix;
    const metabolic = uhGetNumericState(h, p, "metabolic_score");
    const avgGlucose = uhGetNumericState(h, p, "average_glucose");
    const variability = uhGetNumericState(h, p, "glucose_variability");
    const hba1c = uhGetNumericState(h, p, "hba1c");
    const timeInTarget = uhGetNumericState(h, p, "time_in_target");

    const glucose = uhGetNumericState(h, p, "glucose");
    const hasData = glucose != null || metabolic != null || avgGlucose != null || variability != null || hba1c != null || timeInTarget != null;
    if (!hasData) return `<div class="no-data">No glucose data available</div>`;

    const parts = [this._renderAdditionalMetrics(["glucose"])];
    if (metabolic !== null) parts.push(uhMetricRow("METABOLIC SCORE", metabolic, "", uhGetScoreColorRaw(metabolic), uhGetScoreLabel(metabolic), this._getSparklineHtml("metabolic_score", uhGetScoreColorRaw(metabolic))));
    if (avgGlucose !== null) parts.push(uhMetricRow("AVG GLUCOSE", avgGlucose, uhGetUnit(h, p, "average_glucose", "mg/dL"), "", "", this._getSparklineHtml("average_glucose", "var(--uh-text-secondary)")));

    const gridItems = [];
    if (variability !== null) gridItems.push(uhMetricRow("VARIABILITY", variability, "%", "", "", ""));
    if (hba1c !== null) gridItems.push(uhMetricRow("HbA1c", hba1c, "%", "", "", ""));
    if (timeInTarget !== null) gridItems.push(uhMetricRow("IN TARGET", timeInTarget, "%", "", "", ""));
    if (gridItems.length > 0) {
      parts.push(`<div class="metric-grid">${gridItems.join("")}</div>`);
    }
    return parts.join("");
  }

  _updateValues() {
    if (!this.shadowRoot || !this._hass) return;
    const el = this.shadowRoot.getElementById("contentArea");
    if (el) el.innerHTML = this._renderContent();
  }
}

/* ══════════════════════ HOME CARD ══════════════════════ */

class UltrahumanHomeCard extends UltrahumanCardBase {
  static getConfigElement() { return document.createElement("ultrahuman-home-card-editor"); }
  static getStubConfig() { return { entity_prefix: "sensor.ultrahuman_home_your_device", title: "Ultrahuman Home" }; }
  getCardSize() { return 6; }

  _getRefreshMetrics() { return UH_HOME_METRICS.map(([key]) => key); }
  _getSparklineEntities() { return UH_HOME_METRICS.slice(0, UH_HOME_PRIMARY_COUNT).map(([key]) => key); }

  _renderContent() {
    const h = this._hass, p = this._prefix;
    const renderRows = metrics => metrics.map(([key, label]) => {
      const value = uhGetNumericState(h, p, key);
      if (value === null) return "";
      return uhMetricRow(label, value, uhGetUnit(h, p, key), "", "",
        this._getSparklineHtml(key, "var(--uh-text-secondary)"));
    }).join("");
    const primary = renderRows(UH_HOME_METRICS.slice(0, UH_HOME_PRIMARY_COUNT));
    const details = renderRows(UH_HOME_METRICS.slice(UH_HOME_PRIMARY_COUNT));
    const expanded = this.shadowRoot?.getElementById("homeDetails")?.open;
    const timestamps = UH_HOME_METRICS.map(([key]) => {
      if (uhGetNumericState(h, p, key) === null) return NaN;
      return Date.parse(uhGetAttributes(h, p, key).reading_timestamp);
    }).filter(Number.isFinite);
    let readingTime = "";
    if (timestamps.length) {
      const date = new Date(Math.max(...timestamps));
      try {
        readingTime = date.toLocaleString(h?.locale?.language, { timeZone: h?.config?.time_zone });
      } catch {
        readingTime = date.toISOString();
      }
    }
    return [
      `<h3 class="home-title">${uhEscape(this._config.title || "Ultrahuman Home")}</h3>`,
      readingTime ? `<div class="reading-time">Latest reading: ${uhEscape(readingTime)}</div>` : "",
      primary ? `<div class="metric-grid">${primary}</div>` : "",
      details ? `<details id="homeDetails" ${expanded ? "open" : ""}><summary>More environmental readings</summary><div class="metric-grid">${details}</div></details>` : "",
      !primary && !details ? `<div class="no-data">No Home readings available</div>` : "",
    ].join("");
  }
}

/* ══════════════════════ EDITOR ══════════════════════ */

class UltrahumanEditorBase extends HTMLElement {
  get _prefixPlaceholder() { return "sensor.ultrahuman_ring_your_email_com"; }
  get _hasTitle() { return false; }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const root = this.shadowRoot;
    root.textContent = "";

    const style = document.createElement("style");
    style.textContent = `
      .editor { padding: 8px 0; }
      .row { margin-bottom: 16px; }
      label { display: block; margin-bottom: 4px; font-weight: 600; font-size: 14px; }
      input {
        width: 100%; padding: 10px 12px; border: 1px solid var(--divider-color, #ccc);
        border-radius: 8px; box-sizing: border-box; font-size: 14px;
        background: var(--card-background-color, #fff); color: var(--primary-text-color, #000);
      }
      .hint { font-size: 12px; color: var(--secondary-text-color, #888); margin-top: 6px; line-height: 1.4; }
    `;
    root.appendChild(style);

    const editor = document.createElement("div");
    editor.className = "editor";
    const row = document.createElement("div");
    row.className = "row";

    const label = document.createElement("label");
    label.textContent = "Entity Prefix";
    row.appendChild(label);

    const input = document.createElement("input");
    input.id = "prefix";
    input.type = "text";
    input.value = this._config.entity_prefix || "";
    input.placeholder = this._prefixPlaceholder;
    input.addEventListener("input", (e) => {
      this._config = { ...this._config, entity_prefix: e.target.value };
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    });
    row.appendChild(input);

    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = "The common prefix for your Ultrahuman sensor entities. Find it in Developer Tools \u2192 States by filtering for \"ultrahuman\".";
    row.appendChild(hint);

    editor.appendChild(row);
    if (this._hasTitle) {
      const titleRow = document.createElement("div");
      titleRow.className = "row";
      const titleLabel = document.createElement("label");
      titleLabel.textContent = "Title (optional)";
      const titleInput = document.createElement("input");
      titleInput.type = "text";
      titleInput.value = this._config.title || "";
      titleInput.placeholder = "Ultrahuman Home";
      titleInput.addEventListener("input", event => {
        this._config = { ...this._config, title: event.target.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      titleRow.appendChild(titleLabel);
      titleRow.appendChild(titleInput);
      editor.appendChild(titleRow);
    }
    root.appendChild(editor);
  }
}

class UltrahumanRingCardEditor extends UltrahumanEditorBase {}
class UltrahumanRingOverviewCardEditor extends UltrahumanEditorBase {}
class UltrahumanRingSleepCardEditor extends UltrahumanEditorBase {}
class UltrahumanRingMovementCardEditor extends UltrahumanEditorBase {}
class UltrahumanRingRecoveryCardEditor extends UltrahumanEditorBase {}
class UltrahumanRingHeartCardEditor extends UltrahumanEditorBase {}
class UltrahumanRingGlucoseCardEditor extends UltrahumanEditorBase {}
class UltrahumanHomeCardEditor extends UltrahumanEditorBase {
  get _prefixPlaceholder() { return "sensor.ultrahuman_home_your_device"; }
  get _hasTitle() { return true; }
}

/* ══════════════════════ REGISTER ══════════════════════ */

customElements.define("ultrahuman-ring-card", UltrahumanRingCard);
customElements.define("ultrahuman-ring-card-editor", UltrahumanRingCardEditor);
customElements.define("ultrahuman-ring-overview-card", UltrahumanRingOverviewCard);
customElements.define("ultrahuman-ring-overview-card-editor", UltrahumanRingOverviewCardEditor);
customElements.define("ultrahuman-ring-sleep-card", UltrahumanRingSleepCard);
customElements.define("ultrahuman-ring-sleep-card-editor", UltrahumanRingSleepCardEditor);
customElements.define("ultrahuman-ring-movement-card", UltrahumanRingMovementCard);
customElements.define("ultrahuman-ring-movement-card-editor", UltrahumanRingMovementCardEditor);
customElements.define("ultrahuman-ring-recovery-card", UltrahumanRingRecoveryCard);
customElements.define("ultrahuman-ring-recovery-card-editor", UltrahumanRingRecoveryCardEditor);
customElements.define("ultrahuman-ring-heart-card", UltrahumanRingHeartCard);
customElements.define("ultrahuman-ring-heart-card-editor", UltrahumanRingHeartCardEditor);
customElements.define("ultrahuman-ring-glucose-card", UltrahumanRingGlucoseCard);
customElements.define("ultrahuman-ring-glucose-card-editor", UltrahumanRingGlucoseCardEditor);

customElements.define("ultrahuman-home-card", UltrahumanHomeCard);
customElements.define("ultrahuman-home-card-editor", UltrahumanHomeCardEditor);

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "ultrahuman-home-card", name: "Ultrahuman Home", description: "Environmental readings, latest-reading time, and sparkline trends", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-card", name: "Ultrahuman Ring Card", description: "All-in-one compact dashboard with sparkline graphs", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-overview-card", name: "Ultrahuman Overview", description: "Ring SVG hero with score arcs and snapshot pills", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-sleep-card", name: "Ultrahuman Sleep", description: "Sleep score with stage bar, contributors, and sparklines", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-movement-card", name: "Ultrahuman Movement", description: "Movement score with steps, VO2 max, and sparklines", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-recovery-card", name: "Ultrahuman Recovery", description: "Recovery score with HRV, RHR, temp, and sparklines", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-heart-card", name: "Ultrahuman Heart", description: "Heart metrics with sparkline trends", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
  { type: "ultrahuman-ring-glucose-card", name: "Ultrahuman Glucose", description: "Metabolic score with glucose metrics and sparklines", preview: true, documentationURL: "https://github.com/tanujdargan/ultrahuman-ha" },
);

console.info(
  `%c ULTRAHUMAN RING %c v${CARD_VERSION} `,
  "background: #0EFF27; color: #000; font-weight: bold; padding: 2px 8px; border-radius: 4px 0 0 4px;",
  "background: #1A1A1A; color: #0EFF27; font-weight: bold; padding: 2px 8px; border-radius: 0 4px 4px 0;"
);
