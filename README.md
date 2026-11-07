# shelly-monitor

**Energy, cost, relay and device-health dashboard for Shelly smart plugs — on a Raspberry Pi, no cloud, no Docker.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%20OS-c51a4a)
![Shelly](https://img.shields.io/badge/Shelly-Gen2%20%7C%20Gen3%20%7C%20Gen4-0b75c2)

Built for the **Shelly Plug M Gen3**, works with any Shelly Gen2+ device that has a switch
(Plus Plug S, Plug S Gen3, 1PM, 2PM, Pro 4PM, …).

<!-- Add a screenshot: save it as docs/dashboard.png and uncomment the next line
![Dashboard](docs/dashboard.png)
-->

## Features

- **Cost tracking**: today, this week / month / year, per plug, per day, projected € per month and per year.
  Your tariff is a text box on the dashboard; changing it recalculates all history.
- **Energy**: per hour / day / week, share per plug, lifetime counter, returned energy.
- **Electrical values**: power (live, 5-min avg & peak), voltage, current, grid frequency,
  power factor, apparent power, internal temperature.
- **Relay statistics**: on/off timeline, number of switches, *who* switched it (button, app,
  http, schedule, power-up…), on-time, duty cycle, average load while on.
- **Device health**: uptime, reboots (marked on every graph), availability %, WiFi signal,
  free RAM and flash, firmware updates, cloud/MQTT connection, error flags.
- **Nothing to install on the plugs**: no Shelly scripts, works with stock firmware.
- **Catches every toggle**: a live connection to each plug means even a 1-second on/off is counted.
- **Runs headless** as three systemd services; view it from any browser on your network.
- **Add plugs** by adding three lines to a config file.
- **Keeps 5 years** of 10-second data by default.

65 panels in total. [Full list below](#dashboard).

## How it works

```
                   HTTP poll every 10 s
 Shelly plugs  ─────────────────────────────▶  shelly-collector  ──▶  Prometheus  ──▶  Grafana
               ◀─────────────────────────────    (Python, :9924)      (database)       (:3000)
                   live WebSocket events
```

- **shelly-collector** asks each plug for its full status every 10 s via the local
  [Shelly RPC API](https://shelly-api-docs.shelly.cloud/gen2/). It also keeps a WebSocket open,
  so the plug pushes every relay change the moment it happens. It works out what the plug
  doesn't store itself (switch counts, on-time, reboots) and saves those counters to disk.
- **Prometheus** stores everything.
- **Grafana** shows the dashboard. Viewing needs no login; editing needs the admin login.

Energy and cost figures come from the plug's own kWh counter, so they stay exact even if the
Pi is off for a while. If a plug's counter jumps back after a power cut, the collector
compensates so nothing is counted twice.

## Requirements

- Raspberry Pi with **Raspberry Pi OS Bookworm or newer, 64-bit recommended**
  (Grafana no longer supports the 32-bit ARMv6 boards: Pi 1 and Pi Zero).
  Any Debian-based Linux box works too.
- Internet access during installation (for apt and pip).
- One or more Shelly Gen2/Gen3/Gen4 devices on the same network.

## Quick start

**1. Prepare the plugs.** Nothing to set up in the Shelly app, but check two things:
- Give each plug a **fixed IP address** (DHCP reservation in your router, or static IP in the
  plug's WiFi settings).
- Leave **authentication off** (Settings → Authentication). Password-protected devices are
  not supported yet.

**2. Install on the Pi** (over SSH is fine):

```bash
git clone https://github.com/<your-user>/shelly-monitor.git
cd shelly-monitor
sudo bash install.sh
```

**3. Add your plugs:**

```bash
sudo nano /etc/shelly-monitor/config.yml
sudo systemctl restart shelly-collector
```

**4. Open the dashboard** at `http://<pi-hostname>:3000` from any device on your network.
The installer prints the address and a random admin password (also saved in
`/etc/shelly-monitor/grafana-admin-password`).

Set your electricity price in the **Price €/kWh** box at the top of the dashboard.

## Configuration

`/etc/shelly-monitor/config.yml`:

```yaml
price_per_kwh: 0.35        # reference only; the dashboard box is what counts
currency: EUR

defaults:
  poll_interval: 10        # seconds between full polls
  timeout: 5

plugs:
  - name: plug-1           # unique, no spaces – shown in the graphs
    host: 192.168.1.50
    room: Living room      # optional

  - name: washing-machine
    host: 192.168.1.52
    poll_interval: 5       # per-plug override
```

After editing: `sudo systemctl restart shelly-collector`. New plugs appear in the dashboard's
**Plug** dropdown automatically. For devices with several channels (2PM, Pro 4PM) each
channel becomes its own series.

### Install options

Pass these to `install.sh`. They are remembered for later runs (in `/etc/shelly-monitor/install.env`).

| Variable | Default | Meaning |
|---|---|---|
| `GRAFANA_PORT` | `3000` | Port for the dashboard |
| `RETENTION` | `5y` | How long to keep data |
| `RETENTION_SIZE` | `8GB` | Max database size (oldest data is dropped first) |

```bash
sudo GRAFANA_PORT=3001 RETENTION=2y bash install.sh
```

### Polling interval

Status is polled every 10 s and Prometheus stores a sample every 10 s; relay changes arrive
instantly regardless. To go faster, set `poll_interval` in `config.yml` **and**
`scrape_interval` in `/etc/prometheus/prometheus.yml`, then restart both services.
Going below 2–3 s gains little and grows the database faster.

## Dashboard

| Section | Panels |
|---|---|
| ⚡ Right now | Total and per-plug power, relay state, kWh and € today |
| 💶 Energy & cost | kWh and € for the selected range, this week / month / year, projected €/month and €/year, cost per plug, average and peak power, energy per hour / day / week, cost per day, energy share, lifetime counter, returned energy |
| 📈 Power | Live power, 5-minute average and peak, apparent power |
| 🔌 Electrical | Voltage, current, frequency, power factor, temperature, energy in last minute |
| 🔁 Relay | State timeline, switches (range / lifetime / per day), switches by source, ON vs OFF, on-time, duty cycle, on-hours per day, average load while on |
| 🩺 Device health | Online timeline, uptime, reboots, availability, WiFi signal, firmware update, RAM, flash, poll latency, collector errors, live-connection and cloud/MQTT status, device info, error flags, last command source |

Use the time picker to look at any range; the "range" panels follow it.
Daily bars are aligned to UTC midnight; "today / this month" totals use local time.

## Everyday commands

```bash
systemctl status shelly-collector prometheus grafana-server   # are all three running?
journalctl -u shelly-collector -f                              # live log, shows every toggle
curl localhost:9924                                            # which plugs are reachable
sudo bash install.sh                                              # update after git pull
```

## Troubleshooting

**Browser says "connection refused" on port 3000**
Grafana isn't running. Check `systemctl status grafana-server` and
`journalctl -u grafana-server -n 50 --no-pager`. The very first start on a Pi can take a
few minutes. If another program uses port 3000, reinstall with `sudo GRAFANA_PORT=3001 bash install.sh`
(the installer checks for this).

**A plug shows as DOWN / its panels are empty**
Run `curl localhost:9924` on the Pi. If the plug is DOWN, check its IP in `config.yml`, that the
Pi can reach it (`curl http://<plug-ip>/rpc/Shelly.GetDeviceInfo`), and that authentication is off.

**Some panels say "No data"**
Daily, weekly and lifetime panels need time to fill. Power factor only appears if the plug's
firmware reports it. Returned energy and error flags are empty when there is nothing to show.

**Relay switches made before installing are missing**
The plug doesn't keep a switch history; counting starts when the collector starts.

**"Firmware update" shows UPDATE**
Update the plug in its web UI or the Shelly app.

## Updating

```bash
cd shelly-monitor
git pull
sudo bash install.sh
```

Your config, recorded data, Grafana password and install options are kept.

## Uninstall

```bash
sudo bash uninstall.sh          # removes the collector; keeps data, Prometheus and Grafana
sudo bash uninstall.sh --purge  # removes everything, including all recorded data
```

## Metrics

All metrics carry `plug` and `room` labels; per-switch metrics also carry `channel`.

| Metric | Type | Description |
|---|---|---|
| `shelly_power_watts` | gauge | Active power |
| `shelly_voltage_volts` | gauge | Voltage |
| `shelly_current_amperes` | gauge | Current |
| `shelly_frequency_hertz` | gauge | Grid frequency |
| `shelly_power_factor` | gauge | Power factor (if reported) |
| `shelly_apparent_power_va` | gauge | Voltage × current |
| `shelly_temperature_celsius` | gauge | Internal temperature |
| `shelly_energy_wh_total` | counter | Consumed energy; never decreases, even if the plug's counter goes back after a power cut |
| `shelly_device_energy_wh` | gauge | Raw energy counter exactly as the device reports it |
| `shelly_returned_energy_wh_total` | counter | Returned energy |
| `shelly_energy_last_minute_wh` | gauge | Energy in the last complete minute |
| `shelly_relay_on` | gauge | Relay state (1 = on) |
| `shelly_relay_toggles_total` | counter | All relay changes |
| `shelly_relay_switches_total` | counter | Relay changes by `to` (on/off) and `source` |
| `shelly_relay_on_seconds_total` | counter | Time the relay was on |
| `shelly_relay_last_source_info` | gauge | Source of the last relay command |
| `shelly_relay_timer_seconds` | gauge | Active auto on/off timer |
| `shelly_uptime_seconds` | gauge | Device uptime |
| `shelly_reboots_total` | counter | Reboots detected |
| `shelly_ram_free_bytes` / `_min_free_` / `_size_` | gauge | RAM |
| `shelly_fs_free_bytes` / `shelly_fs_size_bytes` | gauge | Flash storage |
| `shelly_wifi_rssi_dbm` | gauge | WiFi signal |
| `shelly_wifi_info` | gauge | SSID, IP, status |
| `shelly_service_connected` | gauge | Cloud / MQTT / outbound-WS connection |
| `shelly_update_available` | gauge | Firmware update available |
| `shelly_update_version_info` | gauge | Available firmware version |
| `shelly_restart_required` | gauge | Device wants a restart |
| `shelly_config_revision` | gauge | Config revision |
| `shelly_device_info` | gauge | Model, firmware, MAC, ID |
| `shelly_error` | gauge | Active error flags |
| `shelly_up` | gauge | Last poll succeeded |
| `shelly_websocket_connected` | gauge | Live connection open |
| `shelly_last_seen_timestamp_seconds` | gauge | Last data received |
| `shelly_poll_duration_seconds` | gauge | Poll latency |
| `shelly_poll_errors_total` | counter | Failed polls |
| `shelly_websocket_reconnects_total` | counter | Live connection drops |
| `shelly_price_per_kwh` | gauge | Price from config |
| `shelly_collector_info` | gauge | Collector version |

You can use these in your own Grafana panels or alerts, or scrape `:9924/metrics` from an
existing Prometheus.

## Development

```
collector/            the Python collector (aiohttp + PyYAML)
config/               example configuration
grafana/              dashboard generator, generated dashboard, provisioning
prometheus/           scrape config and recording rules
systemd/              collector service unit
tools/                fake Shelly device and end-to-end test
install.sh            installer / updater
uninstall.sh
```

**Test without hardware.** `tools/fake_shelly.py` simulates a Plug M Gen3 (status API plus
a few relay toggles over WebSocket). The end-to-end test starts two fake plugs and an unreachable one,
runs the collector against them and checks the metrics:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r collector/requirements.txt prometheus_client
bash tools/test_collector.sh
```

**Change the dashboard.** The dashboard is generated by `grafana/gen_dashboard.py`; edit
it, then run:

```bash
python3 grafana/gen_dashboard.py     # writes grafana/dashboards/shelly.json
sudo bash install.sh                    # deploys it
```

Edits made in the Grafana UI are saved there, but the next `install.sh` overwrites them;
export the JSON or port your changes to the generator to keep them.

CI (GitHub Actions) runs shellcheck, checks the dashboard JSON matches the generator,
and runs the end-to-end test on every push.

## Contributing

Issues and pull requests are welcome, especially reports from Shelly models other than the
Plug M Gen3. Please run `bash tools/test_collector.sh` before opening a PR, and regenerate the
dashboard JSON if you changed the generator.

## License

[MIT](LICENSE)

Not affiliated with Shelly Group / Allterco. "Shelly" is a trademark of its owner.
