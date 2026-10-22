---
title: "Home Assistant Entity Area Script"
type: artifact
description: "Script that lists an HA entity's area and its device's area and moves the entity to another area over the WebSocket API"
status: active
tags: [homeassistant, script, area, websocket]
created: 2026-10-22
updated: 2026-10-22
last_verified: 2026-10-22
---

# Home Assistant Entity Area Script

## Summary

This script moved `light.work_table_light` from Office to Living Room on 2026-10-22. It is generalized here: it lists every
entity whose id contains a search text, with the entity's area, its device and the device's area, and with `--move`
sets one entity's own area (`config/entity_registry/update`). An entity's own area overrides its device's area. A
`light.switch` YAML wrapper has no device, so its own area is the only one it has.

The token is read from `/mnt/data/homeassistant/mcp_config.json` (mode 600, keys `url` and `token`) and never printed.
It needs `aiohttp`, which the Home Assistant venv has, so run it with that Python:

```bash
/mnt/data/homeassistant/venv/bin/python ha_area.py work_table lantern
/mnt/data/homeassistant/venv/bin/python ha_area.py work_table --move light.work_table_light living_room
```

```python
"""ha_area.py - list entities' areas (own and device's); --move ENTITY AREA_ID sets an entity's own area."""
import argparse, asyncio, json

import aiohttp

cfg = json.load(open("/mnt/data/homeassistant/mcp_config.json"))


async def main(a):
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(cfg["url"].replace("http", "ws") + "/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": cfg["token"]})
            assert (await ws.receive_json())["type"] == "auth_ok"
            n = 0

            async def call(**msg):
                nonlocal n
                n += 1
                msg["id"] = n
                await ws.send_json(msg)
                while True:
                    r = await ws.receive_json()
                    if r.get("id") == n:
                        return r

            if a.move:
                r = await call(type="config/entity_registry/update", entity_id=a.move[0], area_id=a.move[1])
                print("update:", r["success"], r.get("result", {}).get("entity_entry", {}).get("area_id"), r.get("error"))
            ents = (await call(type="config/entity_registry/list"))["result"]
            devs = {d["id"]: d for d in (await call(type="config/device_registry/list"))["result"]}
            for e in ents:
                if any(t in e["entity_id"] for t in a.match):
                    d = devs.get(e.get("device_id")) or {}
                    print(e["entity_id"], "area=", e.get("area_id"), "device=", d.get("name"), "device_area=", d.get("area_id"))


ap = argparse.ArgumentParser()
ap.add_argument("match", nargs="+", help="text in the entity ids to list")
ap.add_argument("--move", nargs=2, metavar=("ENTITY", "AREA_ID"))
asyncio.run(main(ap.parse_args()))
```

Output on 2026-10-22, after the move:

```
switch.lantern_socket area= None device= Lantern device_area= office
light.work_table_light area= living_room device= None device_area= None
```

## Related

- [Home Assistant Core Deployment and Strata MCP Integration](../decisions/home-assistant-strata-mcp.md)

## Sources

1. Claude Code, session of 2026-10-22 (Ray rename; work table light moved to the Living Room).
