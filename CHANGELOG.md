# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] – 2026-11-07

First public release.

### Added
- Python collector for Shelly Gen2/Gen3/Gen4 switch devices: HTTP polling plus a
  live WebSocket connection, so every relay change is counted with its source.
- Derived, persisted counters: relay switches (by source and direction), relay
  on-time, device reboots, poll errors, websocket reconnects.
- Prometheus configuration with 5-year default retention and recording rules.
- Grafana dashboard with 65 panels (energy, cost, power, electrical values, relay,
  device health), generated from `grafana/gen_dashboard.py`.
- `install.sh` / `uninstall.sh` for native systemd setup on Raspberry Pi OS,
  with configurable Grafana port and retention.
- Fake Shelly device and end-to-end test script; GitHub Actions CI.
