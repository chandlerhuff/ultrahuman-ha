# Ultrahuman — Home Assistant Integration

A custom Home Assistant integration for Ultrahuman daily health data and Ultrahuman Home environmental devices, using personal API tokens from [Ultrahuman Vision](https://vision.ultrahuman.com/developer).

## Sensors

Daily health accounts expose **39 sensors**. A sensor is unknown when the account has no reading for that metric. Missing fields and explicitly pending readings are accepted, including on a newly set up Ring; they do not prevent the other sensors from updating.

| Group | Readings |
| --- | --- |
| Sleep | Sleep score, total sleep, time in bed, efficiency, deep/REM/light sleep, restorative sleep score and percentage, SpO₂, temperature deviation, heart-rate drop and its reported time, sleep movements, morning alertness score and duration, complete sleep cycles, tosses and turns, average body temperature |
| Heart | Latest heart rate, resting heart rate, daily HRV, sleep resting heart rate, average sleep HRV |
| Body and activity | Skin temperature, daily steps, active minutes, weekly active minutes, inactive time, movements, recovery index, movement index, VO₂ max |
| Glucose | Latest glucose, metabolic score, glucose variability, average glucose, estimated HbA1c, time in target |

Sleep durations are displayed in minutes. The API reports restorative sleep as a score in some responses and a percentage in others; these use separate sensors. Heart-rate-drop time and morning-alertness duration are also kept separate from numeric heart-rate drop and alertness score. A time string is never interpreted as a BPM reading.

Daily movements and sleep movements are separate readings. Inactive time is exposed as the raw numeric API value because the supplied response does not identify its unit. Pending morning alertness remains unknown and carries its API status as an attribute. Stage percentages, bedtime boundaries, and the account's last sync time are available as small attributes; graphs and narrative insights are not stored in entity attributes. The daily HRV/resting-heart-rate values and their separate sleep readings come from distinct API metrics.

Each Home device exposes **19 sensor types**:

- Enabled by default: formaldehyde, carbon monoxide, carbon dioxide, PM1, PM10, PM2.5, volatile organic compounds, temperature, humidity, noise, and air quality index.
- Disabled by default: microphone analysis, UVA/UVB/UVC, red/green/blue light channels, and infrared. Enable them in **Settings → Devices & services → Entities**, including disabled entities in the filter. These expose numeric API measurements; there is no audio recording or streaming.

Home sensor states use the latest timestamped reading in a rolling 24-hour window, not the window average. Reading timestamps and returned summary values are available as attributes. Confirmed light-channel measurements in lux use illuminance sensors. UV measurements in mW/cm² are converted to W/m², including their averages and limits, for Home Assistant irradiance sensors. Unrecognized units remain generic and are not reinterpreted. Equivalent temperature and mass-concentration unit changes are converted to the sensor's existing native unit. Incompatible unit changes make the affected reading unknown rather than mixing units in its statistics. Summary attributes include `summary_unit`; `source_unit` records the API unit. Home Assistant can display temperature in a different preferred unit from the native summary values.

## Installation

### HACS

1. In HACS, open **Custom repositories**.
2. Add `https://github.com/tanujdargan/ultrahuman-ha` with category **Integration**.
3. Download the integration and restart Home Assistant.

### Manual

Copy `custom_components/ultrahuman` into your Home Assistant `custom_components` directory and restart Home Assistant.

## Configuration

Get your API key from the [Ultrahuman Vision developer portal](https://vision.ultrahuman.com/developer):

1. Open the developer portal and sign in with your Ultrahuman account.
2. Under **Personal API Tokens**, generate and copy a personal API token. This token is the API key used by this integration.

Then open **Settings → Devices & services → Add integration → Ultrahuman** and choose:

- **Daily health metrics:** enter the token and the email address of the Ultrahuman account.
- **Home environmental metrics:** enter the token and the device MAC address. Leave email blank for your own device, or provide the email of a shared account.

Shared accounts must authorize the token owner's Partner ID in the Ultrahuman app. MAC addresses accept colon, hyphen, or unseparated hexadecimal formatting. Device discovery is not available through the documented API, so MAC addresses must be entered manually.

Add the integration again for another daily account or Home device. Home devices work without a Ring account entry. Each entry has its own update coordinator, so an error on one device does not interrupt the others. When a token expires or is revoked, Home Assistant prompts you to replace it.

## Updates and history

- Daily health metrics refresh **hourly**, using the account timezone returned by the API. Before that timezone is known, the integration uses Home Assistant's timezone.
- Home devices refresh **every five minutes** by default. Open the device's integration entry settings to choose **1–60 minutes**. Changes apply immediately without removing the device.
- Use a card's refresh button or the `homeassistant.update_entity` action on one sensor to refresh its entry manually.

The integration fetches current readings and keeps a snapshot in memory. Home Assistant's recorder stores entity history according to your recorder settings, and the cards use that history for sparklines. No API history backfill is performed. Missing daily readings are cleared on date rollover rather than carrying yesterday's data forward. Home readings include their source timestamps, so a successful cloud request does not imply the device just took a new sample.

## Dashboard cards

The integration registers `/ultrahuman/ultrahuman-ring-card.js` as a JavaScript module resource. If automatic registration is unavailable, add that resource in your dashboard settings.

Available cards:

- `custom:ultrahuman-ring-card` — daily health overview with metric details.
- `custom:ultrahuman-ring-overview-card` — compact daily snapshot.
- `custom:ultrahuman-ring-sleep-card`
- `custom:ultrahuman-ring-movement-card`
- `custom:ultrahuman-ring-recovery-card`
- `custom:ultrahuman-ring-heart-card`
- `custom:ultrahuman-ring-glucose-card`
- `custom:ultrahuman-home-card` — one Home device's environmental readings and optional low-level details.

Each card uses the common entity prefix for its account or device. Find the prefix under **Developer Tools → States** by filtering for `ultrahuman`; remove the final metric suffix from an entity ID. For example, `sensor.ultrahuman_home_living_aabbccddeeff_pm25` has prefix `sensor.ultrahuman_home_living_aabbccddeeff`. Generated prefixes include the Home MAC address or daily entry ID so accounts and devices with the same display name stay separate. Keep the suffixes when renaming entities if you use the bundled cards.

```yaml
type: custom:ultrahuman-home-card
entity_prefix: sensor.ultrahuman_home_living_aabbccddeeff
title: Living Room
```

```yaml
type: custom:ultrahuman-ring-card
entity_prefix: sensor.ultrahuman_ring_your_account
```

See [examples/dashboard.yaml](examples/dashboard.yaml) for a combined dashboard. Cards follow Home Assistant's theme and entity units, display unknown/unavailable readings gracefully, and work without recorder history (without sparklines).

## API coverage and limitations

The integration targets the current [Daily Metrics API](https://vision.ultrahuman.com/developer-docs) and [Home Metrics API](https://vision.ultrahuman.com/developer/docs?api=home), not the legacy metrics endpoint. OAuth, historical imports, PPG, and blood-test APIs are outside this integration's current scope.

The daily overview lists `motion` and `recovery` but does not define their response structures. They are intentionally pending a confirmed response contract; the separate `movement_index` and `recovery_index` metrics are supported. Both flattened and nested sleep objects are supported. Standalone values take precedence over matching aggregate measurements, including explicitly pending or null values. Reported sleep-stage chart percentages are kept distinct from per-stage contributor percentages; the cards do not recalculate sleep totals or invent an awake percentage.

Parsing is covered by public documentation examples and fully synthetic regression fixtures. The synthetic cases cover 18 Home metrics, mixed units, flattened sleep fields, partial daily data, and pending values. No user-provided readings, device identifiers, or personal timestamps are stored in the tests. Additional device response variations remain unverified. Tests currently run against **Home Assistant 2026.10.4**; older releases are unverified.

## Development

Use Python 3.14 for the pinned Home Assistant test environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests
node --test tests/test_cards.mjs
node --check custom_components/ultrahuman/www/ultrahuman-ring-card.js
```

Tests are offline and use documentation fixtures and mocked API requests. See [fixture provenance](tests/fixtures/README.md).

## License

[MIT](LICENSE).
