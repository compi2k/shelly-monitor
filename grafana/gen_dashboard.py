#!/usr/bin/env python3
"""
Generates grafana/dashboards/shelly.json

Edit this file to add/remove panels, then run:
    python3 grafana/gen_dashboard.py && sudo bash install.sh
(You can also just edit the dashboard in Grafana's UI and "Save" — but then
re-running this script will overwrite it.)
"""
import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prom"}
F = 'plug=~"$plug"'
PRICE = "$price"

panels = []
_id = [0]
_y = [0]
_row = {"x": 0, "h": 0}


def nid():
    _id[0] += 1
    return _id[0]


def row(title, collapsed=False):
    _y[0] += _row["h"]
    _row.update(x=0, h=0)
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y[0]}, "panels": []})
    _y[0] += 1


def place(w, h):
    if _row["x"] + w > 24:
        _y[0] += _row["h"]
        _row.update(x=0, h=0)
    pos = {"h": h, "w": w, "x": _row["x"], "y": _y[0]}
    _row["x"] += w
    _row["h"] = max(_row["h"], h)
    return pos


def tgt(expr, legend="{{plug}}", ref="A", instant=False, interval=None, fmt="time_series"):
    t = {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref,
         "instant": instant, "range": not instant, "format": fmt}
    if interval:
        t["interval"] = interval
    return t


def panel(ptype, title, targets, w, h, unit=None, decimals=None, desc=None, options=None,
          custom=None, time_from=None, interval=None, thresholds=None, mappings=None,
          min_=None, max_=None, transformations=None, overrides=None, color=None):
    defaults = {"custom": custom or {}}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if min_ is not None:
        defaults["min"] = min_
    if max_ is not None:
        defaults["max"] = max_
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
    if mappings:
        defaults["mappings"] = mappings
    if color:
        defaults["color"] = color
    p = {"type": ptype, "title": title, "id": nid(), "datasource": DS,
         "gridPos": place(w, h), "targets": targets,
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if desc:
        p["description"] = desc
    if time_from:
        p["timeFrom"] = time_from
        p["hideTimeOverride"] = False
    if interval:
        p["interval"] = interval
    if transformations:
        p["transformations"] = transformations
    panels.append(p)
    return p


def stat(title, targets, w=4, h=4, unit=None, decimals=None, **kw):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": kw.pop("color_mode", "value"), "graphMode": kw.pop("graph_mode", "none"),
            "textMode": "auto", "justifyMode": "auto", "orientation": "auto"}
    return panel("stat", title, targets, w, h, unit=unit, decimals=decimals, options=opts, **kw)


def ts(title, targets, w=12, h=8, unit=None, bars=False, stack=False, fill=10, step=False, **kw):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 1,
              "fillOpacity": 80 if bars else fill, "showPoints": "never", "spanNulls": False,
              "lineInterpolation": "stepAfter" if step else "smooth",
              "stacking": {"mode": "normal" if stack else "none", "group": "A"},
              "axisSoftMin": 0 if kw.pop("soft_zero", True) else None}
    opts = {"legend": {"displayMode": "table", "placement": "bottom",
                       "calcs": kw.pop("calcs", ["mean", "max", "lastNotNull"])},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    return panel("timeseries", title, targets, w, h, unit=unit, custom=custom, options=opts, **kw)


def bargauge(title, targets, w=8, h=6, unit=None, **kw):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
            "namePlacement": "left"}
    return panel("bargauge", title, targets, w, h, unit=unit, options=opts, **kw)


def timeline(title, targets, w=24, h=None, mappings=None, **kw):
    opts = {"showValue": "never", "mergeValues": True, "alignValue": "left", "rowHeight": 0.8,
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "single"}}
    custom = {"fillOpacity": 80, "lineWidth": 0}
    return panel("state-timeline", title, targets, w, h or 5, options=opts, custom=custom,
                 mappings=mappings, **kw)


ONOFF = [{"type": "value", "options": {
    "0": {"text": "OFF", "color": "#5b5b66", "index": 0},
    "1": {"text": "ON", "color": "green", "index": 1}}}]
UPDOWN = [{"type": "value", "options": {
    "0": {"text": "OFFLINE", "color": "red", "index": 0},
    "1": {"text": "online", "color": "green", "index": 1}}}]
GREEN = [{"color": "green", "value": None}]

E = f"shelly_energy_wh_total{{{F}}}"
P = f"shelly_power_watts{{{F}}}"

# =========================================================================== #
row("⚡ Right now")
stat("Power now (all selected)", [tgt(f"sum({P})", "Total")], w=4, unit="watt", decimals=1,
     graph_mode="area", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1000},
                                    {"color": "red", "value": 2500}])
stat("Power now per plug", [tgt(P)], w=8, unit="watt", decimals=1, graph_mode="area",
     thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1000},
                 {"color": "red", "value": 2500}])
stat("Relay", [tgt(f"shelly_relay_on{{{F}}}")], w=4, mappings=ONOFF, color_mode="background")
stat("Energy today", [tgt(f"sum(increase({E}[$__range]))/1000", "kWh")], w=4, unit="kwatth",
     decimals=3, time_from="now/d", thresholds=GREEN)
stat("Cost today", [tgt(f"sum(increase({E}[$__range]))/1000*{PRICE}", "€")], w=4, unit="currencyEUR",
     decimals=2, time_from="now/d", thresholds=GREEN)

# =========================================================================== #
row("💶 Energy & cost")
stat("kWh – selected range", [tgt(f"sum(increase({E}[$__range]))/1000", "kWh", instant=True)],
     w=4, unit="kwatth", decimals=3, thresholds=GREEN)
stat("Cost – selected range", [tgt(f"sum(increase({E}[$__range]))/1000*{PRICE}", "€", instant=True)],
     w=4, unit="currencyEUR", decimals=2, thresholds=GREEN)
stat("Cost this week", [tgt(f"sum(increase({E}[$__range]))/1000*{PRICE}", "€")], w=4,
     unit="currencyEUR", decimals=2, time_from="now/w", thresholds=GREEN)
stat("Cost this month", [tgt(f"sum(increase({E}[$__range]))/1000*{PRICE}", "€")], w=4,
     unit="currencyEUR", decimals=2, time_from="now/M", thresholds=GREEN)
stat("Cost this year", [tgt(f"sum(increase({E}[$__range]))/1000*{PRICE}", "€")], w=4,
     unit="currencyEUR", decimals=2, time_from="now/y", thresholds=GREEN)
stat("Projected per year", [tgt(f"sum(avg_over_time({P}[7d]))*8760/1000*{PRICE}", "€/yr")], w=4,
     unit="currencyEUR", decimals=0, desc="Average power of the last 7 days extrapolated to 365 days.",
     thresholds=GREEN)

stat("Projected per month", [tgt(f"sum(avg_over_time({P}[7d]))*730/1000*{PRICE}", "€/mo")], w=4,
     unit="currencyEUR", decimals=2, desc="Average power of the last 7 days × 730 h.", thresholds=GREEN)
stat("Cost per plug – range", [tgt(f"sum by (plug)(increase({E}[$__range]))/1000*{PRICE}", instant=True)],
     w=8, unit="currencyEUR", decimals=2, thresholds=GREEN)
stat("Avg power – range", [tgt(f"avg_over_time({P}[$__range])", instant=True)], w=6, unit="watt",
     decimals=1, thresholds=GREEN)
stat("Peak power – range", [tgt(f"max_over_time({P}[$__range])", instant=True)], w=6, unit="watt",
     decimals=0, thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1500},
                             {"color": "red", "value": 3000}])

ts("Energy per hour", [tgt(f"sum by (plug)(increase({E}[1h]))", interval="1h")], w=12, h=8,
   unit="watth", bars=True, stack=True, calcs=["sum", "mean", "max"])
ts("Energy per day", [tgt(f"sum by (plug)(increase({E}[1d]))/1000", interval="1d")], w=12, h=8,
   unit="kwatth", bars=True, stack=True, calcs=["sum", "mean", "max"],
   desc="Buckets are aligned to UTC midnight (01:00/02:00 local).")
ts("Cost per day", [tgt(f"sum by (plug)(increase({E}[1d]))/1000*{PRICE}", interval="1d")], w=12, h=8,
   unit="currencyEUR", bars=True, stack=True, calcs=["sum", "mean", "max"])
panel("piechart", "Energy share – range",
      [tgt(f"sum by (plug)(increase({E}[$__range]))/1000", instant=True)], 6, 8, unit="kwatth", decimals=2,
      options={"pieType": "donut", "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
               "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]},
               "displayLabels": ["percent"]})
ts("Device energy counter (lifetime)", [tgt(f"{E}/1000")], w=6, h=8, unit="kwatth",
   calcs=["lastNotNull"], soft_zero=False)
ts("Energy per week", [tgt(f"sum by (plug)(increase({E}[1w]))/1000", interval="1w")], w=12, h=8,
   unit="kwatth", bars=True, stack=True, calcs=["sum", "mean", "max"])
ts("Returned energy (if any)", [tgt(f"shelly_returned_energy_wh_total{{{F}}}")], w=12, h=8,
   unit="watth", calcs=["lastNotNull"],
   desc="Energy flowing back through the plug (e.g. balcony solar). Usually 0.")

# =========================================================================== #
row("📈 Power")
ts("Active power", [tgt(P)], w=24, h=10, unit="watt", fill=15)
ts("Active power (5-min average & peak)", [
    tgt(f"avg_over_time({P}[5m])", "{{plug}} avg"),
    tgt(f"max_over_time({P}[5m])", "{{plug}} peak", ref="B")], w=12, h=8, unit="watt")
ts("Apparent power (V·A)", [tgt(f"shelly_apparent_power_va{{{F}}}")], w=12, h=8, unit="voltamp")

# =========================================================================== #
row("🔌 Electrical")
ts("Voltage", [tgt(f"shelly_voltage_volts{{{F}}}")], w=8, h=8, unit="volt", soft_zero=False,
   calcs=["min", "mean", "max"])
ts("Current", [tgt(f"shelly_current_amperes{{{F}}}")], w=8, h=8, unit="amp", calcs=["mean", "max"])
ts("Grid frequency", [tgt(f"shelly_frequency_hertz{{{F}}}")], w=8, h=8, unit="hertz", soft_zero=False,
   calcs=["min", "mean", "max"])
ts("Power factor", [tgt(f"shelly_power_factor{{{F}}}")], w=8, h=8, unit="none", soft_zero=False,
   desc="Only shown if the plug's firmware reports pf.")
ts("Internal temperature", [tgt(f"shelly_temperature_celsius{{{F}}}")], w=8, h=8, unit="celsius",
   soft_zero=False, calcs=["min", "mean", "max"])
ts("Energy in last full minute", [tgt(f"shelly_energy_last_minute_wh{{{F}}}")], w=8, h=8,
   unit="watth")

# =========================================================================== #
row("🔁 Relay")
timeline("Relay state", [tgt(f"shelly_relay_on{{{F}}}")], mappings=ONOFF, h=5)
stat("Switches – range", [tgt(f"sum by (plug)(round(increase(shelly_relay_toggles_total{{{F}}}[$__range])))",
                              instant=True)], w=6, unit="none", decimals=0, thresholds=GREEN)
stat("Switches – lifetime (since monitoring)",
     [tgt(f"sum by (plug)(shelly_relay_toggles_total{{{F}}})", instant=True)], w=6, unit="none",
     decimals=0, thresholds=GREEN)
stat("On-time – range", [tgt(f"increase(shelly_relay_on_seconds_total{{{F}}}[$__range])", instant=True)],
     w=6, unit="s", thresholds=GREEN)
stat("Duty cycle – range",
     [tgt(f"increase(shelly_relay_on_seconds_total{{{F}}}[$__range]) / $__range_s * 100", instant=True)],
     w=6, unit="percent", decimals=1, min_=0, max_=100, thresholds=GREEN)
bargauge("Switches by source – range",
         [tgt(f"sum by (plug, source)(round(increase(shelly_relay_switches_total{{{F}}}[$__range])))",
              "{{plug}} · {{source}}", instant=True)], w=8, h=8, unit="none",
         desc="button, app/cloud, http, schedule, timer, init (power-up), WS_in (local), …")
bargauge("ON vs OFF – range",
         [tgt(f"sum by (plug, to)(round(increase(shelly_relay_switches_total{{{F}}}[$__range])))",
              "{{plug}} → {{to}}", instant=True)], w=8, h=8, unit="none")
ts("Switches per day", [tgt(f"sum by (plug)(round(increase(shelly_relay_toggles_total{{{F}}}[1d])))",
                            interval="1d")], w=8, h=8, unit="none", bars=True, stack=True,
   calcs=["sum", "max"])
ts("On-time per day", [tgt(f"increase(shelly_relay_on_seconds_total{{{F}}}[1d])/3600", interval="1d")],
   w=12, h=8, unit="h", bars=True, calcs=["sum", "mean"])
ts("Energy while ON per hour of on-time (avg load when on)",
   [tgt(f"increase({E}[1d]) / (increase(shelly_relay_on_seconds_total{{{F}}}[1d])/3600)", interval="1d")],
   w=12, h=8, unit="watt", bars=True, desc="Average power draw during the time the relay was on.")

# =========================================================================== #
row("🩺 Device health")
timeline("Online", [tgt(f"shelly_up{{{F}}}")], mappings=UPDOWN, h=5)
stat("Uptime", [tgt(f"shelly_uptime_seconds{{{F}}}")], w=6, unit="dtdurations", thresholds=GREEN)
stat("Reboots – range", [tgt(f"round(increase(shelly_reboots_total{{{F}}}[$__range]))", instant=True)],
     w=3, decimals=0, thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}])
stat("Reboots – total", [tgt(f"shelly_reboots_total{{{F}}}", instant=True)], w=3, decimals=0,
     thresholds=GREEN)
stat("Availability – range", [tgt(f"avg_over_time(shelly_up{{{F}}}[$__range])*100", instant=True)],
     w=4, unit="percent", decimals=2,
     thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 95},
                 {"color": "green", "value": 99.5}])
stat("WiFi signal", [tgt(f"shelly_wifi_rssi_dbm{{{F}}}")], w=4, unit="dBm",
     thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": -75},
                 {"color": "green", "value": -65}])
stat("Firmware update", [tgt(f"shelly_update_available{{{F}}}")], w=4,
     mappings=[{"type": "value", "options": {"0": {"text": "up to date", "color": "green"},
                                             "1": {"text": "UPDATE", "color": "orange"}}}],
     color_mode="background")

ts("Uptime", [tgt(f"shelly_uptime_seconds{{{F}}}/86400")], w=8, h=8, unit="d",
   desc="Saw-tooth drops = reboots / power loss.", calcs=["lastNotNull", "max"])
ts("WiFi RSSI", [tgt(f"shelly_wifi_rssi_dbm{{{F}}}")], w=8, h=8, unit="dBm", soft_zero=False,
   calcs=["min", "mean", "max"])
ts("Free RAM", [tgt(f"shelly_ram_free_bytes{{{F}}}", "{{plug}} free"),
                tgt(f"shelly_ram_min_free_bytes{{{F}}}", "{{plug}} min since boot", ref="B")],
   w=8, h=8, unit="bytes", calcs=["min", "lastNotNull"])
ts("Free flash", [tgt(f"shelly_fs_free_bytes{{{F}}}")], w=8, h=8, unit="bytes",
   calcs=["min", "lastNotNull"])
ts("Poll latency", [tgt(f"shelly_poll_duration_seconds{{{F}}}")], w=8, h=8, unit="s",
   calcs=["mean", "max"])
ts("Collector errors / reconnects per hour", [
    tgt(f"increase(shelly_poll_errors_total{{{F}}}[1h])", "{{plug}} poll errors"),
    tgt(f"increase(shelly_websocket_reconnects_total{{{F}}}[1h])", "{{plug}} ws reconnects", ref="B")],
   w=8, h=8, unit="none", calcs=["sum", "max"])
timeline("Live event channel (websocket)", [tgt(f"shelly_websocket_connected{{{F}}}")], h=4,
         mappings=[{"type": "value", "options": {"0": {"text": "disconnected", "color": "orange"},
                                                 "1": {"text": "connected", "color": "green"}}}])
timeline("Cloud / MQTT connection", [tgt(f"shelly_service_connected{{{F}}}", "{{plug}} {{service}}")],
         h=5, mappings=[{"type": "value", "options": {"0": {"text": "no", "color": "#5b5b66"},
                                                      "1": {"text": "yes", "color": "green"}}}])

panel("table", "Devices", [tgt(f"shelly_device_info{{{F}}}", instant=True, fmt="table")], 24, 5,
      transformations=[{"id": "organize", "options": {"excludeByName": {
          "Time": True, "Value": True, "__name__": True, "job": True, "instance": True}}}])
panel("table", "Active device error flags",
      [tgt(f"shelly_error{{{F}}}", instant=True, fmt="table")], 12, 5,
      transformations=[{"id": "organize", "options": {"excludeByName": {
          "Time": True, "Value": True, "__name__": True, "job": True, "instance": True}}}],
      desc="Empty = good. Examples: overtemp, overpower, overvoltage.")
panel("table", "Last relay command source",
      [tgt(f"shelly_relay_last_source_info{{{F}}}", instant=True, fmt="table")], 12, 5,
      transformations=[{"id": "organize", "options": {"excludeByName": {
          "Time": True, "Value": True, "__name__": True, "job": True, "instance": True}}}])

# =========================================================================== #
dashboard = {
    "uid": "shelly",
    "title": "Shelly Plugs",
    "tags": ["shelly", "energy"],
    "timezone": "browser",
    "editable": True,
    "graphTooltip": 1,
    "refresh": "10s",
    "schemaVersion": 39,
    "time": {"from": "now-24h", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m", "15m"]},
    "templating": {"list": [
        {"name": "plug", "label": "Plug", "type": "query", "datasource": DS,
         "query": {"query": "label_values(shelly_up, plug)", "refId": "plug"},
         "definition": "label_values(shelly_up, plug)", "refresh": 2, "multi": True,
         "includeAll": True, "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
         "sort": 1},
        {"name": "price", "label": "Price €/kWh", "type": "textbox", "query": "0.35",
         "current": {"text": "0.35", "value": "0.35"}},
    ]},
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
         "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts",
         "type": "dashboard"},
        {"name": "Reboots", "datasource": DS, "enable": True, "iconColor": "red",
         "expr": f"changes(shelly_reboots_total{{{F}}}[1m]) > 0", "step": "60s",
         "titleFormat": "Reboot", "textFormat": "{{plug}} rebooted"},
    ]},
    "panels": panels,
}

out = Path(__file__).parent / "dashboards" / "shelly.json"
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
print(f"wrote {out} ({len(panels)} panels)")
