#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
shelly-monitor collector: Shelly Gen2/Gen3/Gen4 devices -> Prometheus metrics.

For every plug in config.yml it
  * polls  Shelly.GetStatus over HTTP every `poll_interval` seconds
  * keeps a WebSocket open to ws://<host>/rpc and listens for NotifyStatus /
    NotifyEvent, so every relay toggle is counted (even short on/off blips
    that happen between two polls) together with its source
    (button, app, schedule, http, ...)
  * derives extra stats the device doesn't keep itself:
      relay switch counts, relay on-time, reboots, reachability
  * persists those derived counters to a state file so they survive restarts

Metrics are served on http://0.0.0.0:<listen_port>/metrics
"""

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

import aiohttp
import yaml
from aiohttp import web

__version__ = "1.0.0"

log = logging.getLogger("shelly")

CONFIG_PATH = Path(os.environ.get("SHELLY_CONFIG", "/config/config.yml"))
STATE_PATH = Path(os.environ.get("SHELLY_STATE", "/data/state.json"))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels(d: dict) -> str:
    if not d:
        return ""
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in d.items()) + "}"


def num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


# --------------------------------------------------------------------------- #
# one plug
# --------------------------------------------------------------------------- #
class Plug:
    def __init__(self, cfg: dict, state: dict, defaults: dict):
        self.name = cfg["name"]
        self.host = cfg["host"]
        self.poll_interval = float(cfg.get("poll_interval", defaults.get("poll_interval", 10)))
        self.timeout = float(cfg.get("timeout", defaults.get("timeout", 5)))
        self.room = cfg.get("room", "")

        # live data
        self.status: dict = {}
        self.info: dict = {}
        self.up = False
        self.ws_connected = False
        self.last_seen = 0.0
        self.poll_duration = 0.0

        # derived / persisted
        s = state.setdefault(self.name, {})
        s.setdefault("switches", {})          # "cid|to|source" -> count
        s.setdefault("on_seconds", {})        # cid -> seconds
        s.setdefault("reboots", 0)
        s.setdefault("poll_errors", 0)
        s.setdefault("ws_reconnects", 0)
        s.setdefault("last_uptime", None)
        s.setdefault("last_output", {})       # cid -> bool
        self.s = s
        self._on_since: dict = {}             # cid -> monotonic ts while on

    # -- identity labels ---------------------------------------------------
    def base_labels(self) -> dict:
        return {"plug": self.name, "room": self.room}

    # -- state tracking ----------------------------------------------------
    def _apply_switch(self, cid: str, sw: dict, source_hint: str | None = None):
        if "output" not in sw:
            return
        out = bool(sw["output"])
        prev = self.s["last_output"].get(cid)
        now = time.monotonic()

        # on-time accumulation
        if prev:
            since = self._on_since.get(cid, now)
            self.s["on_seconds"][cid] = self.s["on_seconds"].get(cid, 0.0) + (now - since)
        self._on_since[cid] = now

        if prev is not None and prev != out:
            src = sw.get("source") or source_hint or "unknown"
            key = f"{cid}|{'on' if out else 'off'}|{src}"
            self.s["switches"][key] = self.s["switches"].get(key, 0) + 1
            log.info("%s %s switched %s (source=%s)", self.name, cid, "ON" if out else "OFF", src)
        self.s["last_output"][cid] = out

    def tick_on_time(self):
        """Called periodically so on-time grows smoothly while the relay is on."""
        now = time.monotonic()
        for cid, out in self.s["last_output"].items():
            if out and self.up:
                since = self._on_since.get(cid, now)
                self.s["on_seconds"][cid] = self.s["on_seconds"].get(cid, 0.0) + (now - since)
            self._on_since[cid] = now

    def merge_status(self, partial: dict, full: bool = False):
        """Merge a full GetStatus or a partial NotifyStatus into self.status."""
        if full:
            new = partial
        else:
            new = dict(self.status)
            for comp, val in partial.items():
                if isinstance(val, dict) and isinstance(new.get(comp), dict):
                    merged = dict(new[comp])
                    merged.update(val)
                    new[comp] = merged
                else:
                    new[comp] = val

        for comp, val in partial.items():
            if comp.startswith("switch:") and isinstance(val, dict):
                self._apply_switch(comp, val)

        sysd = new.get("sys", {})
        up = sysd.get("uptime")
        if isinstance(up, (int, float)):
            last = self.s.get("last_uptime")
            if last is not None and up + 30 < last:
                self.s["reboots"] += 1
                log.warning("%s rebooted (uptime %s -> %s)", self.name, last, up)
            self.s["last_uptime"] = up

        self.status = new
        self.last_seen = time.time()

    # -- network -----------------------------------------------------------
    async def rpc(self, session: aiohttp.ClientSession, method: str, params=None):
        url = f"http://{self.host}/rpc"
        body = {"id": 1, "method": method}
        if params:
            body["params"] = params
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=self.timeout)) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result", data)

    async def poll_loop(self, session: aiohttp.ClientSession):
        while True:
            t0 = time.monotonic()
            try:
                if not self.info:
                    self.info = await self.rpc(session, "Shelly.GetDeviceInfo")
                    log.info("%s: %s %s fw %s", self.name, self.info.get("model"),
                             self.info.get("id"), self.info.get("ver"))
                st = await self.rpc(session, "Shelly.GetStatus")
                self.merge_status(st, full=True)
                self.up = True
            except Exception as e:  # noqa: BLE001
                if self.up:
                    log.warning("%s: poll failed: %s", self.name, e)
                self.up = False
                self.s["poll_errors"] += 1
                self.info = {}
            self.poll_duration = time.monotonic() - t0
            self.tick_on_time()
            await asyncio.sleep(max(0.5, self.poll_interval - self.poll_duration))

    async def ws_loop(self, session: aiohttp.ClientSession):
        backoff = 2
        while True:
            try:
                async with session.ws_connect(f"ws://{self.host}/rpc", heartbeat=30,
                                              timeout=aiohttp.ClientWSTimeout(ws_close=self.timeout)) as ws:
                    # Gen2+ only pushes notifications to a client that sent a request with "src"
                    await ws.send_json({"id": 1, "src": f"shelly-monitor-{self.name}",
                                        "method": "Shelly.GetStatus"})
                    self.ws_connected = True
                    backoff = 2
                    log.info("%s: websocket connected", self.name)
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        m = data.get("method")
                        if m == "NotifyStatus" or m == "NotifyFullStatus":
                            p = dict(data.get("params", {}))
                            p.pop("ts", None)
                            self.merge_status(p, full=(m == "NotifyFullStatus"))
                            self.up = True
                        elif m == "NotifyEvent":
                            for ev in data.get("params", {}).get("events", []):
                                log.debug("%s event: %s", self.name, ev)
                        elif "result" in data and data.get("id") == 1:
                            self.merge_status(data["result"], full=True)
                            self.up = True
            except Exception as e:  # noqa: BLE001
                log.debug("%s: websocket error: %s", self.name, e)
            if self.ws_connected:
                self.s["ws_reconnects"] += 1
            self.ws_connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    # -- metrics -----------------------------------------------------------
    def metrics(self, out: "Metrics"):
        L = self.base_labels()
        out.add("shelly_up", "1 if the plug answered the last poll", "gauge", L, 1 if self.up else 0)
        out.add("shelly_websocket_connected", "1 if the live event websocket is open", "gauge", L,
                1 if self.ws_connected else 0)
        out.add("shelly_last_seen_timestamp_seconds", "Unix time of last data from the plug", "gauge", L,
                self.last_seen)
        out.add("shelly_poll_duration_seconds", "Duration of last HTTP poll", "gauge", L, self.poll_duration)
        out.add("shelly_poll_errors_total", "Failed polls (collector side)", "counter", L, self.s["poll_errors"])
        out.add("shelly_websocket_reconnects_total", "Websocket reconnects", "counter", L, self.s["ws_reconnects"])
        out.add("shelly_reboots_total", "Device reboots detected via uptime reset", "counter", L,
                self.s["reboots"])

        if self.info:
            out.add("shelly_device_info", "Static device info", "gauge", {
                **L, "id": self.info.get("id", ""), "model": self.info.get("model", ""),
                "app": self.info.get("app", ""), "gen": self.info.get("gen", ""),
                "fw": self.info.get("ver", ""), "mac": self.info.get("mac", ""), "host": self.host}, 1)

        st = self.status
        sysd = st.get("sys", {})
        for key, metric, help_ in [
            ("uptime", "shelly_uptime_seconds", "Device uptime"),
            ("ram_free", "shelly_ram_free_bytes", "Free RAM"),
            ("ram_size", "shelly_ram_size_bytes", "Total RAM"),
            ("ram_min_free", "shelly_ram_min_free_bytes", "Lowest free RAM since boot"),
            ("fs_free", "shelly_fs_free_bytes", "Free flash filesystem"),
            ("fs_size", "shelly_fs_size_bytes", "Flash filesystem size"),
            ("cfg_rev", "shelly_config_revision", "Config revision number"),
            ("unixtime", "shelly_device_time_seconds", "Device clock"),
        ]:
            v = num(sysd.get(key))
            if v is not None:
                out.add(metric, help_, "gauge", L, v)
        if "restart_required" in sysd:
            out.add("shelly_restart_required", "Device wants a restart", "gauge", L,
                    num(sysd["restart_required"]))
        upd = sysd.get("available_updates") or {}
        out.add("shelly_update_available", "Firmware update available", "gauge", L, 1 if upd else 0)
        for chan, d in upd.items():
            out.add("shelly_update_version_info", "Available firmware versions", "gauge",
                    {**L, "channel": chan, "version": (d or {}).get("version", "")}, 1)

        wifi = st.get("wifi", {})
        if num(wifi.get("rssi")) is not None:
            out.add("shelly_wifi_rssi_dbm", "WiFi signal strength", "gauge", L, num(wifi["rssi"]))
        if wifi:
            out.add("shelly_wifi_info", "WiFi info", "gauge", {
                **L, "ssid": wifi.get("ssid") or "", "ip": wifi.get("sta_ip") or "",
                "status": wifi.get("status") or ""}, 1)
        for comp in ("cloud", "mqtt", "ws"):
            if isinstance(st.get(comp), dict) and "connected" in st[comp]:
                out.add("shelly_service_connected", "Cloud/MQTT/outbound-WS connection", "gauge",
                        {**L, "service": comp}, num(st[comp]["connected"]))

        # every switch component (Plug M has one: switch:0) ----------------
        for comp, sw in st.items():
            if not comp.startswith("switch:") or not isinstance(sw, dict):
                continue
            CL = {**L, "channel": comp.split(":")[1]}
            if "output" in sw:
                out.add("shelly_relay_on", "Relay state (1=on)", "gauge", CL, num(sw["output"]))
            for key, metric, help_ in [
                ("apower", "shelly_power_watts", "Active power"),
                ("voltage", "shelly_voltage_volts", "Voltage"),
                ("current", "shelly_current_amperes", "Current"),
                ("freq", "shelly_frequency_hertz", "Grid frequency"),
                ("pf", "shelly_power_factor", "Power factor"),
            ]:
                v = num(sw.get(key))
                if v is not None:
                    out.add(metric, help_, "gauge", CL, v)
            # apparent power if we have V and A
            if num(sw.get("voltage")) is not None and num(sw.get("current")) is not None:
                out.add("shelly_apparent_power_va", "Apparent power (V*A)", "gauge", CL,
                        sw["voltage"] * sw["current"])
            ae = sw.get("aenergy") or {}
            if num(ae.get("total")) is not None:
                out.add("shelly_energy_wh_total", "Consumed active energy (device counter)", "counter",
                        CL, ae["total"])
            if isinstance(ae.get("by_minute"), list) and ae["by_minute"]:
                # by_minute is in milliwatt-hours; [0] = current (partial) minute, [1] = last full minute
                if len(ae["by_minute"]) > 1:
                    out.add("shelly_energy_last_minute_wh", "Energy in last complete minute", "gauge", CL,
                            ae["by_minute"][1] / 1000.0)
            rae = sw.get("ret_aenergy") or {}
            if num(rae.get("total")) is not None:
                out.add("shelly_returned_energy_wh_total", "Returned active energy", "counter", CL,
                        rae["total"])
            temp = sw.get("temperature") or {}
            if num(temp.get("tC")) is not None:
                out.add("shelly_temperature_celsius", "Internal temperature", "gauge", CL, temp["tC"])
            for err in sw.get("errors", []) or []:
                out.add("shelly_error", "Active device error flags", "gauge", {**CL, "error": err}, 1)
            if "source" in sw:
                out.add("shelly_relay_last_source_info", "Source of the last relay command", "gauge",
                        {**CL, "source": sw["source"]}, 1)
            if num(sw.get("timer_duration")) is not None:
                out.add("shelly_relay_timer_seconds", "Active auto on/off timer duration", "gauge", CL,
                        sw["timer_duration"])

        for cid, secs in self.s["on_seconds"].items():
            out.add("shelly_relay_on_seconds_total", "Total time relay was on (collector observed)",
                    "counter", {**L, "channel": cid.split(":")[1]}, secs)
        totals: dict = {}
        for cid in self.s["last_output"]:
            totals[cid] = 0
        for key, cnt in self.s["switches"].items():
            totals[key.split("|", 1)[0]] = totals.get(key.split("|", 1)[0], 0) + cnt
        for cid, cnt in totals.items():
            out.add("shelly_relay_toggles_total", "All relay state changes (any source)", "counter",
                    {**L, "channel": cid.split(":")[1]}, cnt)
        for key, cnt in self.s["switches"].items():
            cid, to, src = key.split("|", 2)
            out.add("shelly_relay_switches_total", "Relay state changes", "counter",
                    {**L, "channel": cid.split(":")[1], "to": to, "source": src}, cnt)


# --------------------------------------------------------------------------- #
# metrics text builder
# --------------------------------------------------------------------------- #
class Metrics:
    def __init__(self):
        self.meta: dict = {}
        self.rows: dict = {}

    def add(self, name, help_, typ, lbl, value):
        if value is None:
            return
        self.meta.setdefault(name, (help_, typ))
        self.rows.setdefault(name, []).append(f"{name}{labels(lbl)} {float(value)!r}")

    def render(self) -> str:
        out = []
        for name, (help_, typ) in self.meta.items():
            out.append(f"# HELP {name} {help_}")
            out.append(f"# TYPE {name} {typ}")
            out.extend(self.rows[name])
        return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE_PATH)


async def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    logging.basicConfig(level=cfg.get("log_level", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    state = load_state()
    defaults = cfg.get("defaults", {}) or {}
    plugs = [Plug(p, state, defaults) for p in cfg.get("plugs", [])]
    if not plugs:
        log.error("No plugs configured in %s", CONFIG_PATH)
    price = cfg.get("price_per_kwh")

    async def handle_metrics(_req):
        m = Metrics()
        for p in plugs:
            p.tick_on_time()
            p.metrics(m)
        if price is not None:
            m.add("shelly_price_per_kwh", "Configured energy price per kWh", "gauge",
                  {"currency": cfg.get("currency", "EUR")}, price)
        m.add("shelly_collector_plugs", "Configured plugs", "gauge", {}, len(plugs))
        m.add("shelly_collector_info", "Collector version", "gauge", {"version": __version__}, 1)
        return web.Response(text=m.render(), content_type="text/plain", charset="utf-8")

    async def handle_root(_req):
        rows = "".join(f"<li>{p.name} ({p.host}) - {'up' if p.up else 'DOWN'}, "
                       f"ws {'on' if p.ws_connected else 'off'}</li>" for p in plugs)
        return web.Response(text=f"<h3>shelly-monitor collector {__version__}</h3><ul>{rows}</ul><a href=/metrics>/metrics</a>",
                            content_type="text/html")

    app = web.Application()
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get("/", handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(cfg.get("listen_port", 9924))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("shelly-monitor %s serving metrics on :%d for %d plug(s)", __version__, port, len(plugs))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async def saver():
        while True:
            await asyncio.sleep(60)
            save_state(state)

    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(saver())]
        for p in plugs:
            tasks.append(asyncio.create_task(p.poll_loop(session)))
            tasks.append(asyncio.create_task(p.ws_loop(session)))
        await stop.wait()
        for t in tasks:
            t.cancel()
    for p in plugs:
        p.tick_on_time()
    save_state(state)
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
