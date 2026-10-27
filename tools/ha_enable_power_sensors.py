#!/usr/bin/env python3
"""tools/ha_enable_power_sensors.py - Enables power/current/voltage sensors on Tuya outlets."""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

CONFIG_PATH = Path(__file__).resolve().parents[2] / "homeassistant" / "mcp_config.json"   # next to the checkout

TARGET_POWER_SENSORS = [
    "sensor.pc_power",
    "sensor.v13_charger_power",
    "sensor.printer_light_power",
    "sensor.v11_charger_power",
    "sensor.monitor_light_power",
    "sensor.a1_a_power",
    "sensor.a1_b_power",
]

TARGET_CURRENT_SENSORS = [
    "sensor.pc_current",
    "sensor.v13_charger_current",
    "sensor.printer_light_current",
    "sensor.v11_charger_current",
    "sensor.monitor_light_current",
    "sensor.a1_a_current",
    "sensor.a1_b_current",
]

TARGET_VOLTAGE_SENSORS = [
    "sensor.pc_voltage",
    "sensor.v13_charger_voltage",
    "sensor.printer_light_voltage",
    "sensor.v11_charger_voltage",
    "sensor.monitor_light_voltage",
    "sensor.a1_a_voltage",
    "sensor.a1_b_voltage",
]

TARGET_ENERGY_SENSORS = [
    "sensor.v13_charger_total_energy",
    "sensor.printer_light_total_energy",
    "sensor.monitor_light_total_energy",
    "sensor.a1_a_total_energy",
    "sensor.a1_b_total_energy",
]


async def main():
    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ws_url = cfg["url"].replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            # 1. Handshake & Auth
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": cfg["token"]})
            auth_resp = await ws.receive_json()
            if auth_resp.get("type") != "auth_ok":
                raise RuntimeError(f"WebSocket auth failed: {auth_resp}")
            print("Connected and authenticated with Home Assistant WebSocket API.")

            msg_id = 1

            async def call_ws(**kwargs):
                nonlocal msg_id
                msg_id += 1
                kwargs["id"] = msg_id
                await ws.send_json(kwargs)
                while True:
                    r = await ws.receive_json()
                    if r.get("id") == msg_id:
                        return r

            # 2. Enable power sensors & configure display unit conversion to kW
            print("\nEnabling Power sensors:")
            for eid in TARGET_POWER_SENSORS:
                resp = await call_ws(
                    type="config/entity_registry/update",
                    entity_id=eid,
                    disabled_by=None,
                    options_domain="sensor",
                    options={"unit_of_measurement": "kW", "suggested_display_precision": 3},
                )
                success = resp.get("success", False)
                err = resp.get("error", {}).get("message") if not success else ""
                print(f"  - {eid}: success={success} {err}")

            # 3. Enable current sensors
            print("\nEnabling Current sensors:")
            for eid in TARGET_CURRENT_SENSORS:
                resp = await call_ws(
                    type="config/entity_registry/update",
                    entity_id=eid,
                    disabled_by=None,
                )
                success = resp.get("success", False)
                err = resp.get("error", {}).get("message") if not success else ""
                print(f"  - {eid}: success={success} {err}")

            # 4. Enable voltage sensors
            print("\nEnabling Voltage sensors:")
            for eid in TARGET_VOLTAGE_SENSORS:
                resp = await call_ws(
                    type="config/entity_registry/update",
                    entity_id=eid,
                    disabled_by=None,
                )
                success = resp.get("success", False)
                err = resp.get("error", {}).get("message") if not success else ""
                print(f"  - {eid}: success={success} {err}")

            # 5. Update energy sensors with device_class energy & display precision
            print("\nUpdating Total Energy sensors:")
            for eid in TARGET_ENERGY_SENSORS:
                resp = await call_ws(
                    type="config/entity_registry/update",
                    entity_id=eid,
                    device_class="energy",
                    options_domain="sensor",
                    options={"unit_of_measurement": "kWh", "suggested_display_precision": 2},
                )
                success = resp.get("success", False)
                err = resp.get("error", {}).get("message") if not success else ""
                print(f"  - {eid}: success={success} {err}")


if __name__ == "__main__":
    asyncio.run(main())
