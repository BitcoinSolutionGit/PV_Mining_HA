# Bitcoin PV-mining Add-on for Home Assistant

**Orchestrates Bitcoin miners, water heater (immersion heater), and cooling circuit based on PV surplus, electricity price, and mining profitability.**  
Runs as a Home Assistant add-on and talks to your existing HA entities (Scripts, Switches, Input Booleans & Sensors) via the Supervisor API.

## Features

- **PV Surplus Optimization:** Discrete start/stop of miners based on available PV share, grid price, and BTC revenue.
- **Live Profitability:** SAT/TH/h, post-tax revenue, incremental PV/Grid mix, break-even grid price.
- **Cooling Orchestration:** Auto/Manual, “Ready” state via `input_boolean`/`binary_sensor`, configurable ON/OFF actions and timeout.
- **Water Heater (Auto):** Target temperature, hysteresis, max power, optional **zero-export kick** (short impulse for zero feed-in inverters).
- **Priority Planner:** Custom order (House/Cooling/Miner/Heater…).
- **Home Assistant Native:** Uses your **Scripts**, **Switches**, **Input Numbers/Booleans**, **Sensors** via Supervisor proxy.
- **UI Configuration:** Map entities & edit variables in the frontend; persisted as YAML under `/config/pv_mining_addon`.

> 💡 **Free vs Premium:** The first miner is free. Additional miners require **Premium** (see below).

---

## How it works (TL;DR)

- The add-on ingests live signals (PV production, grid import/export, electricity price, BTC price/network hashrate) and computes an **incremental mix** for each start/stop step.
- **Miners** are discrete loads: if ≥95% of rated power is allocated, the add-on switches **ON** via your HA script/switch; otherwise **OFF**.
- **Cooling** can auto-start if a profitable miner requires it; a **Ready entity** confirms it’s actually running.
- **Heater** writes a percentage (0–100%) to an `input_number` as long as the target temperature is not reached.

---

## Requirements

- Home Assistant (Supervised/OS), add-on with Supervisor token.
- HA entities:
  - **Sensors**: PV production, grid consumption (import), feed-in (export).
  - **Scripts/Switches**: Power ON/OFF per miner, ON/OFF for cooling.
  - **Input Number**: Heater percent cache, water temperature cache (if used).
  - **Input Boolean / Binary Sensor**: Cooling “Ready” state.
- Optional: electricity price sensor and feed-in tariff; otherwise fixed values in settings.

---

## Installation

1. Add this repo as a **custom add-on repository** to Home Assistant (or build locally).
2. Install & start the add-on.
3. Open the add-on’s web UI.

> Persistence lives in `/config/pv_mining_addon`
> (`sensors.local.yaml`, `heater.local.yaml`, `pv_mining_local_config.yaml`, …)

---

## Initial setup

### 1) Map entities
- **Sensors** (PV / Grid / Feed-in) in Settings/Mapping.
- **Cooling**: Power **ON/OFF actions** (script/switch), **Ready entity** (e.g., `input_boolean.miner_cooling_toggle`) and timeout.
- **Heater**: `input_heizstab_cache` (0–100%), `input_warmwasser_cache` (°C).

### 2) Variables
- **Economics**: BTC price, network hashrate, block reward, tax % (for “post-tax”).
- **Electricity**: grid price (€/kWh), network fees up/down, PV cost policy  
  - `zero` ⇒ PV costs 0  
  - `feedin` ⇒ opportunity cost = feed-in tariff − upstream fee (fixed or from sensor)
- **Heater**: `enabled`, target temp, max power, unit, optional kickstart (power, cooldown).

### 3) Add miners
- Per miner: name, enabled, **mode (auto/manual)**, **power (on/off)**, hashrate/power, cooling required, HA actions for ON/OFF.

> **Save behavior:** settings are **only persisted on “Save”**; **manual switching** (Power on/off) is also executed **only on “Save”** — the UI updates afterwards.

---

## Example YAML

See [`docs/examples/homeassistant.yaml`](docs/examples/homeassistant.yaml).

---

## Premium

**What you get:** additional miners (from #2 upwards). The first miner stays free.

**Activation**
1. Open **Settings → Premium** (or “License”) in the add-on.
2. Paste your **license key** and save.  
   – Alternatively (advanced): put the key into `/config/pv_mining_addon/pv_mining_local_config.yaml` (e.g. `premium_license_key: "…"`) if your build expects that.
3. Reload the UI. Additional miners should be unlocked.

*(Put a link here where users can obtain a key.)*

---

## Tips & Troubleshooting

- **Scripts run manually but not via the add-on?**  
  Check logs, Supervisor API reachability, and **exact entity names** (including domain `script.` / `switch.`).  
  The add-on calls `POST /api/services/<domain>/<service>` at `http://supervisor/core` with the Supervisor token.
- **Cooling “Ready” never comes?**  
  Ensure the selected `input_boolean` / `binary_sensor` reflects ON/OFF reliably. Increase timeout if needed.
- **Heater stuck at manual %?**  
  Auto mode needs `enabled: true`, valid `input_heizstab_cache`, a temperature sensor, and `max_power_heater > 0`.
- **PV cost policy “feedin”**: mind units (ct/kWh vs €/kWh). The add-on normalizes typical sensor values (ct → €) and subtracts `network_fee_up`.
- **Logs**: consolidated plan & orchestrator logs at `/config/pv_mining_addon/planner.log` (and console).

---

## Safety

- This add-on switches **power loads**. Use proper relays/contactors and ensure electrical safety. You’re responsible for your installation.
- Only use “zero-export kick” if your inverter supports it.

---

## Contributing & Support

- Issues & PRs welcome!  
- Please include **logs**, **add-on version**, **HA version**, and relevant YAML when reporting issues.

---

## License

See [`LICENSE`](LICENSE). A “License” button is also shown in the add-on UI footer.

GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007 <https://www.gnu.org/licenses/>