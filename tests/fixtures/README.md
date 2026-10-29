`daily_metrics.json` and `home_metrics.json` are public illustrative responses from
the official Ultrahuman documentation ([daily](https://vision.ultrahuman.com/developer-docs),
[Home](https://vision.ultrahuman.com/developer/docs?api=home)), retrieved on
2026-10-29. They contain the vendor's example values, not account data. The Home
MAC address is the placeholder AA:BB:CC:DD:EE:FF.

`daily_metrics_partial.json` and `home_metrics_units.json` are fully synthetic
regression fixtures. Their measurements, summaries, dates, timestamps, sleep
times, room metadata, and timezone were fabricated independently of any user's
records. They preserve only API field structures and cases such as missing
metrics, pending values, mixed units, and conflicting sleep representations.
No user-provided readings or device identifiers are retained.
