#!/usr/bin/env python3
"""
Fake Shelly Gen3 plug for development and CI – no real hardware needed.

    python3 tools/fake_shelly.py 18081

Serves Shelly.GetDeviceInfo / Shelly.GetStatus on POST /rpc and a websocket on
GET /rpc that toggles the relay a few times (button, app, http, button) and
then simulates a power cut (energy counter comes back slightly lower)
and stays quiet. Point a config entry at host "127.0.0.1:18081".
"""
import asyncio
import json
import sys
import time

from aiohttp import web

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18081
T0 = time.time()
state = {"out": False, "src": "init", "energy": 1234.5}


def status():
    now = int(time.time())
    return {
        "sys": {"uptime": int(time.time() - T0), "ram_free": 30000, "ram_size": 260000,
                "ram_min_free": 25000, "fs_free": 180000, "fs_size": 458752,
                "restart_required": False, "available_updates": {"stable": {"version": "9.9.9"}},
                "cfg_rev": 12, "unixtime": now},
        "wifi": {"sta_ip": "127.0.0.1", "status": "got ip", "ssid": "Home", "rssi": -61},
        "cloud": {"connected": True},
        "mqtt": {"connected": False},
        "switch:0": {
            "id": 0, "source": state["src"], "output": state["out"],
            "apower": 42.3 if state["out"] else 0.0, "voltage": 231.2, "current": 0.19,
            "freq": 50.01, "pf": 0.92,
            "aenergy": {"total": state["energy"], "by_minute": [100, 700, 650], "minute_ts": now},
            "ret_aenergy": {"total": 0, "by_minute": [0, 0, 0], "minute_ts": now},
            "temperature": {"tC": 38.1, "tF": 100.6},
        },
    }


async def rpc(req):
    body = await req.json()
    if body["method"] == "Shelly.GetDeviceInfo":
        result = {"id": f"shellyplugmg3-fake{PORT}", "mac": "AABBCCDDEEFF", "model": "S3PL-20112EU",
                  "gen": 3, "ver": "1.6.2", "app": "PlugMG3"}
    else:
        result = status()
    return web.json_response({"id": body.get("id"), "src": "fake", "result": result})


async def ws(req):
    sock = web.WebSocketResponse()
    await sock.prepare(req)
    first = json.loads((await sock.receive()).data)
    await sock.send_json({"id": first["id"], "src": "fake", "dst": first["src"], "result": status()})
    for src in ("button", "app", "http", "button"):
        await asyncio.sleep(0.5)
        state.update(out=not state["out"], src=src, energy=state["energy"] + 5)
        await sock.send_json({"src": "fake", "dst": first["src"], "method": "NotifyStatus",
                              "params": {"ts": time.time(),
                                         "switch:0": {"id": 0, "output": state["out"], "source": src,
                                                      "aenergy": {"total": state["energy"]}}}})
    # simulate a power cut: the plug comes back with its energy counter a bit
    # lower (restored from its last save), then keeps counting (+2 Wh)
    for energy in (state["energy"] - 4.5, state["energy"] - 2.5):
        await asyncio.sleep(0.5)
        state["energy"] = energy
        await sock.send_json({"src": "fake", "dst": first["src"], "method": "NotifyStatus",
                              "params": {"ts": time.time(),
                                         "switch:0": {"id": 0, "aenergy": {"total": energy}}}})
    async for _ in sock:
        pass
    return sock


app = web.Application()
app.router.add_post("/rpc", rpc)
app.router.add_get("/rpc", ws)
web.run_app(app, port=PORT, print=None)
