import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../custom_components/ultrahuman/www/ultrahuman-ring-card.js", import.meta.url), "utf8");

function loadCards() {
  const registered = new Map();
  const context = vm.createContext({
    HTMLElement: class {},
    customElements: { define: (name, constructor) => registered.set(name, constructor) },
    window: {},
    console: { info() {} },
    document: { createElement: () => ({}) },
    Date,
  });
  vm.runInContext(`${source}\nglobalThis.helpers = { uhGetNumericState, uhRenderSnapshot, UH_HISTORY_CACHE };`, context);
  return { registered, context };
}

function cardFor(name, states = {}, config = {}) {
  const loaded = loadCards();
  const card = new (loaded.registered.get(name))();
  card._config = { entity_prefix: "sensor.device", ...config };
  card._hass = { states, locale: { language: "en-US" }, config: { time_zone: "UTC" } };
  return { ...loaded, card };
}

function state(value, attributes = {}) {
  return { state: String(value), attributes };
}

function refreshElements(card) {
  const classes = new Set();
  const button = { classList: { add: name => classes.add(name), remove: name => classes.delete(name) }, disabled: false };
  const error = { hidden: true, textContent: "" };
  card.shadowRoot = { getElementById: id => ({ refreshBtn: button, refreshError: error }[id]) };
  return { button, error, classes };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test("Home card and editor are registered in the card catalog", () => {
  const { registered, context } = loadCards();
  assert.ok(registered.has("ultrahuman-home-card-editor"));
  assert.ok(context.window.customCards.some(card => card.type === "ultrahuman-home-card"));
});

test("Home readings preserve zeroes and HA units and escape external text", () => {
  const { card } = cardFor("ultrahuman-home-card", {
    "sensor.device_co": state(0, { unit_of_measurement: "ppm" }),
    "sensor.device_temp": state(72, { unit_of_measurement: "°F", reading_timestamp: "2024-02-12T02:00:00+00:00" }),
    "sensor.device_voc": state(5, { unit_of_measurement: "<img onerror='unsafe'>" }),
  }, { title: "<script>unsafe</script>" });
  const html = card._renderContent();
  assert.match(html, /metric-value">0<span/);
  assert.match(html, /72<span class="metric-unit"> °F/);
  assert.match(html, /Latest reading:/);
  assert.match(html, /&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|<img|status-badge|More environmental readings/);
});

test("Home low-level values appear only when enabled readings exist", () => {
  const { card } = cardFor("ultrahuman-home-card", {
    "sensor.device_uva": state(0, { unit_of_measurement: "raw" }),
    "sensor.device_mic": state("unavailable"),
    "sensor.other_co2": state(800),
  });
  const html = card._renderContent();
  assert.match(html, /<details id="homeDetails"/);
  assert.match(html, /UVA/);
  assert.doesNotMatch(html, /MICROPHONE ANALYSIS|CARBON DIOXIDE|800/);
});

test("Home card renders valid empty responses without fabricating readings", () => {
  const { card } = cardFor("ultrahuman-home-card", { "sensor.device_co2": state("unknown") });
  assert.match(card._renderContent(), /No Home readings available/);
});

test("sleep uses documented stage percentages and restorative score units", () => {
  const { card } = cardFor("ultrahuman-ring-sleep-card", {
    "sensor.device_deep_sleep": state(60, { percentage: 13.2 }),
    "sensor.device_light_sleep": state(300, { percentage: 60.4 }),
    "sensor.device_rem_sleep": state(90, { percentage: 26.4 }),
    "sensor.device_restorative_sleep": state(78, { unit_of_measurement: "score" }),
    "sensor.device_time_in_bed": state(8, { unit_of_measurement: "h" }),
  });
  const html = card._renderContent();
  assert.match(html, /Deep 13.2%/);
  assert.match(html, /Light 60.4%/);
  assert.match(html, /REM 26.4%/);
  assert.match(html, /78<span class="metric-unit"> score/);
  assert.match(html, /8h 0m/);
  assert.doesNotMatch(html, /Awake|78%/);
});

test("sleep without percentages labels durations rather than a made-up Awake stage", () => {
  const { card } = cardFor("ultrahuman-ring-sleep-card", {
    "sensor.device_deep_sleep": state(60),
    "sensor.device_light_sleep": state(300),
    "sensor.device_rem_sleep": state(90),
  });
  const html = card._renderContent();
  assert.match(html, /Deep 1h 0m/);
  assert.match(html, /Light 5h 0m/);
  assert.match(html, /REM 1h 30m/);
  assert.doesNotMatch(html, /Awake|class="sleep-bar"/);
});

test("all-in-one card makes every new daily metric available", () => {
  const keys = ["glucose", "sleep_rhr", "avg_sleep_hrv", "active_minutes", "time_in_bed", "temperature_deviation", "hr_drop", "movements", "morning_alertness", "full_sleep_cycles", "tosses_and_turns", "average_body_temperature"];
  const states = Object.fromEntries(keys.map((key, index) => [`sensor.device_${key}`, state(index)]));
  const { card } = cardFor("ultrahuman-ring-card", states);
  const html = card._renderMetrics();
  for (const label of ["LATEST GLUCOSE", "SLEEP RESTING HR", "SLEEP HRV", "ACTIVE MINUTES", "TIME IN BED", "TEMPERATURE DEVIATION", "HEART RATE DROP", "MOVEMENTS", "MORNING ALERTNESS", "COMPLETE SLEEP CYCLES", "TOSSES AND TURNS", "AVERAGE BODY TEMPERATURE"]) {
    assert.ok(html.includes(label), label);
  }
});

test("glucose-only readings show on the glucose card", () => {
  const { card } = cardFor("ultrahuman-ring-glucose-card", {
    "sensor.device_glucose": state(0, { unit_of_measurement: "mmol/L" }),
  });
  const html = card._renderContent();
  assert.match(html, /LATEST GLUCOSE/);
  assert.match(html, /mmol\/L/);
  assert.doesNotMatch(html, /No glucose data/);
});

test("snapshot uses configured temperature unit", () => {
  const { card, context } = cardFor("ultrahuman-ring-card", {
    "sensor.device_skin_temperature": state(97.7, { unit_of_measurement: "°F" }),
  });
  const html = context.helpers.uhRenderSnapshot(card._hass, card._prefix);
  assert.match(html, /°F/);
  assert.doesNotMatch(html, /°C/);
});

test("Home refresh waits for completion, then clears only its history and stops spinner", async () => {
  const { card, context } = cardFor("ultrahuman-home-card", {
    "sensor.device_co2": state(800),
    "sensor.device_sleep_score": state(85),
  });
  const { button, classes } = refreshElements(card);
  const calls = [];
  let finish;
  card._hass.callService = (...args) => { calls.push(args); return new Promise(resolve => { finish = resolve; }); };
  card._hass.callWS = async () => ({});
  context.helpers.UH_HISTORY_CACHE.set("sensor.device_co2", { ts: Date.now(), data: [{ t: 0, v: 999 }] });
  context.helpers.UH_HISTORY_CACHE.set("sensor.other_co2", { ts: Date.now(), data: [] });
  const pending = card._refreshData();
  assert.equal(button.disabled, true);
  assert.equal(classes.has("spinning"), true);
  assert.equal(context.helpers.UH_HISTORY_CACHE.has("sensor.device_co2"), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][2].entity_id, "sensor.device_co2");
  finish();
  await pending;
  assert.equal(button.disabled, false);
  assert.equal(classes.has("spinning"), false);
  assert.equal(context.helpers.UH_HISTORY_CACHE.has("sensor.other_co2"), true);
  assert.equal(card._sparklines.co2.length, 0);
});

test("failed refresh reports an error and always releases spinner", async () => {
  const { card } = cardFor("ultrahuman-home-card", { "sensor.device_co2": state("unavailable") });
  const { button, classes, error } = refreshElements(card);
  card._hass.callService = async () => { throw new Error("network failure"); };
  await card._refreshData();
  assert.equal(button.disabled, false);
  assert.equal(classes.has("spinning"), false);
  assert.equal(error.hidden, false);
  assert.match(error.textContent, /Unable to refresh/);
});

test("changing card configuration discards history from the previous device", async () => {
  const { card } = cardFor("ultrahuman-home-card", {
    "sensor.old_co2": state(100), "sensor.new_co2": state(200),
  });
  const finish = {};
  card._render = () => {};
  card._hass.callWS = request => new Promise(resolve => { finish[request.entity_ids[0]] = resolve; });
  card.setConfig({ entity_prefix: "sensor.old" });
  card.setConfig({ entity_prefix: "sensor.new" });
  finish["sensor.new_co2"]({ "sensor.new_co2": [{ s: "200", lu: 1 }] });
  await settle();
  finish["sensor.old_co2"]({ "sensor.old_co2": [{ s: "100", lu: 1 }] });
  await settle();
  assert.equal(card._sparklines.co2[0].v, 200);
  assert.equal(card._sparklinesPending, false);
});


test("numeric state parsing keeps zero and rejects missing or invalid values", () => {
  const { context } = loadCards();
  for (const value of ["", " ", "None", "Infinity", "20junk", "unknown", "unavailable"]) {
    assert.equal(context.helpers.uhGetNumericState({ states: { "sensor.device_value": state(value) } }, "sensor.device", "value"), null);
  }
  assert.equal(context.helpers.uhGetNumericState({ states: { "sensor.device_value": state(0) } }, "sensor.device", "value"), 0);
});


test("each detailed daily card renders missing and populated data", () => {
  for (const name of ["ultrahuman-ring-sleep-card", "ultrahuman-ring-movement-card", "ultrahuman-ring-recovery-card", "ultrahuman-ring-heart-card", "ultrahuman-ring-glucose-card"]) {
    const { card } = cardFor(name);
    assert.doesNotThrow(() => card._renderContent(), name);
    card._hass.states["sensor.device_skin_temperature"] = state(97.7, { unit_of_measurement: "°F" });
    assert.doesNotThrow(() => card._renderContent(), name);
  }
});


test("coordinator failures are reported even when the update service resolves", async () => {
  const { card } = cardFor("ultrahuman-home-card", { "sensor.device_co2": state(450) });
  const { error, button } = refreshElements(card);
  card._hass.callService = async () => {
    card._hass.states["sensor.device_co2"] = state("unavailable");
  };
  await card._refreshData();
  assert.equal(error.hidden, false);
  assert.match(error.textContent, /Unable to refresh/);
  assert.equal(button.disabled, false);
});

test("valid empty refreshes remain successful when the entity becomes unknown", async () => {
  const { card } = cardFor("ultrahuman-home-card", { "sensor.device_co2": state(450) });
  const { error, button } = refreshElements(card);
  card._hass.callService = async () => {
    card._hass.states["sensor.device_co2"] = state("unknown");
  };
  card._hass.callWS = async () => ({});
  await card._refreshData();
  assert.equal(error.hidden, true);
  assert.equal(button.disabled, false);
});


function metricValue(html, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return html.match(new RegExp(`<span class="metric-label">${escaped}</span>\\s*<span class="metric-value">(.*?)</span>`, "s"))?.[1];
}

test("flattened sleep readings use the coherent reported stages and actual Awake", () => {
  const states = {
    "sensor.device_sleep_score": state(87, { awake_percentage: 7, awake_minutes: 30 }),
    "sensor.device_total_sleep": state(420, { unit_of_measurement: "min" }),
    "sensor.device_deep_sleep": state(90, { stage_percentage: 20, percentage: 20 }),
    "sensor.device_rem_sleep": state(110, { stage_percentage: 24, percentage: 26.2 }),
    "sensor.device_light_sleep": state(220, { stage_percentage: 49, percentage: 52 }),
    "sensor.device_movements": state(3, { unit_of_measurement: "count" }),
    "sensor.device_sleep_movements": state(11, { unit_of_measurement: "count" }),
    "sensor.device_restorative_sleep_percentage": state(64, { unit_of_measurement: "%" }),
    "sensor.device_hr_drop_time": state("5:20 AM"),
    "sensor.device_morning_alertness_minutes": state("unknown", { unit_of_measurement: "min" }),
  };
  const { card } = cardFor("ultrahuman-ring-sleep-card", states);
  const html = card._renderContent();
  assert.match(html, /Deep 20%/);
  assert.match(html, /REM 24%/);
  assert.match(html, /Light 49%/);
  assert.match(html, /Awake 7%/);
  assert.match(html, /bar-seg awake" style="width:7%/);
  assert.doesNotMatch(html, /26.2%|Light 52%/);
  assert.equal(metricValue(html, "TOTAL SLEEP"), "7h 0m");
  assert.equal(metricValue(html, "SLEEP MOVEMENTS"), '11<span class="metric-unit"> count');
  assert.equal(metricValue(html, "RESTORATIVE SLEEP"), '64<span class="metric-unit"> %');
  assert.equal(metricValue(html, "HEART RATE DROP TIME"), "5:20 AM");
  assert.doesNotMatch(html, /MORNING ALERTNESS DURATION/);

  const { card: all } = cardFor("ultrahuman-ring-card", states);
  assert.equal(metricValue(all._renderMetrics(), "MOVEMENTS"), '3<span class="metric-unit"> count');
  assert.equal(metricValue(all._renderMetrics(), "SLEEP MOVEMENTS"), '11<span class="metric-unit"> count');
});

test("movement keeps reported zero activity and does not guess inactive-time units", () => {
  const { card } = cardFor("ultrahuman-ring-movement-card", {
    "sensor.device_active_minutes": state(0, { unit_of_measurement: "min" }),
    "sensor.device_weekly_active_minutes": state(210, { unit_of_measurement: "min" }),
    "sensor.device_inactive_time": state(83.25),
  });
  const html = card._renderContent();
  assert.equal(metricValue(html, "ACTIVE MINUTES"), '0<span class="metric-unit"> min');
  assert.equal(metricValue(html, "WEEKLY ACTIVE MINUTES"), '210<span class="metric-unit"> min');
  assert.equal(metricValue(html, "INACTIVE TIME"), "83.25");
});

test("drop-time text is escaped and never labelled as a BPM reading", () => {
  const { card } = cardFor("ultrahuman-ring-sleep-card", {
    "sensor.device_hr_drop_time": state("5:20 AM <img src=x>"),
  });
  const value = metricValue(card._renderContent(), "HEART RATE DROP TIME");
  assert.equal(value, "5:20 AM &lt;img src=x&gt;");
  card._hass.states["sensor.device_hr_drop_time"] = state("unknown");
  assert.doesNotMatch(card._renderContent(), /HEART RATE DROP TIME/);
});

test("a partial reported stage set is not mixed with separate summary percentages", () => {
  const { card } = cardFor("ultrahuman-ring-sleep-card", {
    "sensor.device_deep_sleep": state(90, { stage_percentage: 20, percentage: 21 }),
    "sensor.device_light_sleep": state(220, { percentage: 52 }),
    "sensor.device_rem_sleep": state(110, { percentage: 26.2 }),
  });
  const html = card._renderContent();
  assert.match(html, /Deep 20%/);
  assert.match(html, /Light 3h 40m/);
  assert.match(html, /REM 1h 50m/);
  assert.doesNotMatch(html, /26.2%|Light 52%|Awake/);
});
