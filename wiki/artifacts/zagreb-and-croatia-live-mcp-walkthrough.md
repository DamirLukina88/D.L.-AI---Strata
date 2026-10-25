---
title: "Workstation Expansion: Zagreb and Croatia Live MCP Suites"
type: artifact
description: "Report for zagreb (ZET, 24/7 pharmacies, waste schedules, live AQI) and croatia_live (HAK traffic, DHMZ weather, fuel, METAR) MCP servers."
status: active
tags: [mcp, zagreb, croatia, hak, dhmz, zet, live-data, ray]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Workstation Expansion: Zagreb and Croatia Live MCP Suites

## Summary

This update completes the creation and deployment of two specialized on-demand MCP servers providing live data and civic utilities for Zagreb and the Republic of Croatia, bringing the total number of specialized MCP servers in Ray's catalog to **36**.

### Newly Implemented Suites
1. **`zagreb` ([`tools/zagreb_mcp.py`](file:///home/damirl/Desktop/Strata/tools/zagreb_mcp.py)):**
   - **ZET Tram & Public Transit (`zet_transit`):** Complete route catalog for daytime lines (1–17) and night lines (31–34 with operational hours 23:30–04:30), terminals, and live service disruption notices fetched from **`zet.skoljka.org/news`**.
   - **BAJS Zagreb Live Bike Rentals (`zagreb_bajs_bikes`):** Real-time bicycle and free rack availability across all 200 BAJS / Nextbike stations in Zagreb fetched directly from Nextbike's official GBFS feed (`api.nextbike.net/maps/nextbike-live.json?city=1172`). *(Note: `zagreb-insights-explorer.lovable.app` was audited and found to be a static Lovable mock with frozen December 2025 data; the official Nextbike GBFS API was integrated instead for genuine live telemetry).*
   - **24/7 On-Duty Pharmacies (`zagreb_pharmacies`):** Exact locations, addresses, and contact numbers for open 24-hour pharmacies in Zagreb (Centar Trg bana Jelačića, Črnomerec Ilica, Dubrava Grižanska, Siget Av. V. Holjevca, Trešnjevka Ozaljska) plus OHBP emergency hospital hotlines.
   - **Specialized 24/7 Emergency Services (`zagreb_emergency`):** Poison Control Center (Centar za kontrolu otrovanja CKO: `+385 1 2348 342`), emergency pediatric clinics (Klaićeva, Rebro), 24/7 emergency veterinary hospital (Veterinarski fakultet Heinzelova 55: `+385 1 2390 111`), and night emergency dentist (Runjaninova 4).
   - **Čistoća Waste Collection Schedule (`cistoca_waste_schedule`):** District pickup schedules (Donji Grad, Trešnjevka, Maksimir, Novi Zagreb, Dubrava, Črnomerec), ZG vrećice guidelines, bio-waste rules, and free bulky waste (*glomazni otpad*) quotas.
   - **Live Air Quality (`zagreb_air_quality`):** Real-time European AQI, PM2.5, PM10, $O_3$, and $NO_2$ metrics from official measuring stations via Open-Meteo Air Quality API with health guidance.

2. **`croatia_live` ([`tools/croatia_live_mcp.py`](file:///home/damirl/Desktop/Strata/tools/croatia_live_mcp.py)):**
   - **HAK Live Traffic & Borders (`hak_traffic_status`):** Real-time road incidents, roadwork bottlenecks on highways (A1, A3, Zagreb bypass, Lučko toll gate), and border crossing delays (Bregana, Macelj, Bajakovo) fetched directly from HAK mobile alerts.
   - **Official DHMZ Weather Observations (`dhmz_observations`):** Real-time meteorological readings from DHMZ official XML observations (`vrijeme.hr/hrvatska1_n.xml`) for Zagreb (Maksimir, Grič, Pleso) and regional centers (Split, Rijeka, Osijek, Zadar, Dubrovnik, Pula, Varaždin).
   - **HNB Official Exchange Rates (`hnb_exchange_rates`):** Real-time official currency rates and conversions from Croatian National Bank API (`api.hnb.hr`) for EUR against USD, BAM, CHF, GBP, RSD, AUD, CAD, and major world currencies.
   - **State Holidays & Non-Working Sundays (`croatia_holidays_and_sundays`):** Croatian public holidays (*državni praznici*), retail law rules (*Zakon o trgovini* 16 working Sundays rule), and shopping center Sunday schedules in Zagreb.
   - **Regulated Fuel & Aviation METAR (`croatia_fuel_and_aviation`):** Bi-weekly Croatian government-regulated fuel price caps (Eurosuper 95, Eurodizel, Plavi dizel) and live decoded aviation METAR for Zagreb Franjo Tuđman Airport (`LDZA`) and Lučko Airfield (`LDZL`).

3. **`photovideo` Audio Engineering Expansion ([`tools/photovideo_mcp.py`](file:///home/damirl/Desktop/Strata/tools/photovideo_mcp.py)):**
   - **Audio Engineering & Loudness (`audio_engineering_guide`):** Platform loudness standards (YouTube -14 LUFS, European Broadcast EBU R128 -23 LUFS, Podcasts -16 LUFS, True Peak -1.0 dBFS), microphone polar patterns (shotgun/lobar, omni lavalier, cardioid), 32-bit float audio, and wind protection techniques.

---

## Sources

- User requests: 2026-10-25.
- Central catalog: `~/.config/dl-ai/mcp.json`.
- Live feeds: ZET live news (`zet.skoljka.org/news`), Nextbike live API (`api.nextbike.net`), Croatian National Bank (`api.hnb.hr`), Hrvatski autoklub (HAK), Državni hidrometeorološki zavod (DHMZ), Open-Meteo Air Quality, NOAA Aviation Weather.
- Local tools: `tools/zagreb_mcp.py`, `tools/croatia_live_mcp.py`, `tools/photovideo_mcp.py`.
