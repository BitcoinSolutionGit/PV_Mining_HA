# Bitcoin PV-Mining Add-on für Home Assistant

**Orchestriert Bitcoin-Miner, Warmwasser-Heizstab (Immersion Heater) und Kühlkreislauf anhand von PV-Überschuss, Strompreis und Mining-Profitabilität.**  
Läuft als Home-Assistant-Add-on und spricht über die Supervisor-API mit deinen vorhandenen HA-Entities (Scripts, Switches, Input Booleans & Sensors).

## Features

- **PV-Überschuss-Optimierung:** Diskretes Start/Stop von Minern basierend auf PV-Anteil, Netzpreis und BTC-Erlös.
- **Live-Profitabilität:** SAT/TH/h, Nettoumsatz nach Steuern, inkrementeller PV/Grid-Mix, Break-even-Netzpreis.
- **Kühl-Orchestrierung:** Auto/Manuell, „Ready“-Status über `input_boolean`/`binary_sensor`, konfigurierbare ON/OFF-Aktionen und Timeout.
- **Warmwasser (Auto):** Solltemperatur, Hysterese, Max-Leistung, optionaler **Zero-Export-Kick** (kurzer Impuls für Null-Einspeise-Wechselrichter).
- **Priority Planner:** Eigene Reihenfolge (House/Cooling/Miner/Heater …).
- **Home-Assistant-Native:** Nutzt deine **Scripts**, **Switches**, **Input Numbers/Booleans**, **Sensors** via Supervisor-Proxy.
- **UI-Konfiguration:** Entities zuordnen & Variablen im Frontend bearbeiten; Persistenz als YAML unter `/config/pv_mining_addon`.

> 💡 **Free vs Premium:** Der erste Miner ist gratis. Weitere Miner erfordern **Premium** (siehe unten).

---

## Funktionsweise (TL;DR)

- Das Add-on liest Live-Signale (PV-Erzeugung, Netzbezug/-einspeisung, Strompreis, BTC-Preis/Netz-Hashrate) und berechnet für jeden Start/Stop-Schritt den **inkrementellen Mix**.
- **Miner** sind diskrete Lasten: Wenn ≥95 % der Nennleistung zugeteilt werden, schaltet das Add-on **EIN** (per Script/Switch), sonst **AUS**.
- **Cooling** kann automatisch starten, wenn ein profitabler Miner es benötigt; eine **Ready-Entity** bestätigt den tatsächlichen Lauf.
- **Heater** schreibt einen Prozentwert (0–100 %) in ein `input_number`, solange die Solltemperatur nicht erreicht ist.

---

## Voraussetzungen

- Home Assistant (Supervised/OS), Add-on mit Supervisor-Token.
- HA-Entities:
  - **Sensors**: PV-Erzeugung, Netzverbrauch (Import), Einspeisung (Export).
  - **Scripts/Switches**: Power ON/OFF je Miner, ON/OFF für Cooling.
  - **Input Number**: Heater-Prozent-Cache, Warmwasser-Temperatur-Cache (falls genutzt).
  - **Input Boolean / Binary Sensor**: Cooling-„Ready“-Status.
- Optional: Strompreissensor und Einspeisetarif; alternativ feste Werte in den Settings.

---

## Installation

1. Dieses Repo als **Custom Add-on Repository** in Home Assistant hinzufügen (oder lokal bauen).
2. Add-on installieren & starten.
3. Web-UI des Add-ons öffnen.

> Persistenz liegt unter `/config/pv_mining_addon`
> (`sensors.local.yaml`, `heater.local.yaml`, `pv_mining_local_config.yaml`, …)

---

## Ersteinrichtung

### 1) Entities zuordnen
- **Sensors** (PV / Grid / Feed-in) in Settings/Mapping.
- **Cooling**: Power-**ON/OFF-Aktionen** (Script/Switch), **Ready-Entity** (z. B. `input_boolean.miner_cooling_toggle`) und Timeout.
- **Heater**: `input_heizstab_cache` (0–100 %), `input_warmwasser_cache` (°C).

### 2) Variablen
- **Ökonomie**: BTC-Preis, Netzwerk-Hashrate, Block-Reward, Steuer-% (für „nach Steuern“).
- **Strom**: Netzpreis (€/kWh), Netzentgelte up/down, PV-Kostenpolitik  
  - `zero` ⇒ PV kostet 0  
  - `feedin` ⇒ Opportunitätskosten = Einspeisetarif − Upstream-Fee (fix oder Sensorsignal)
- **Heater**: `enabled`, Solltemperatur, Max-Leistung, Einheit, optional Kickstart (Leistung, Cooldown).

### 3) Miner hinzufügen
- Pro Miner: Name, aktiviert, **Modus (auto/manuell)**, **Power (on/off)**, Hashrate/Leistung, Cooling-Pflicht, HA-Aktionen für ON/OFF.

> **Speicher-/Schalt-Verhalten:** Einstellungen werden **erst beim „Save“** gespeichert; **manuelles Schalten** (Power on/off) wird ebenfalls **nur beim „Save“** ausgeführt — die UI aktualisiert danach.

---

## Beispiel-YAML

Siehe:

- [`docs/examples/configuration.yaml`](bitcoin_pv_mining/docs/examples/configuration.yaml)
- [`docs/examples/automations.yaml`](bitcoin_pv_mining/docs/examples/automations.yaml)
- [`docs/examples/scripts.yaml`](bitcoin_pv_mining/docs/examples/scripts.yaml)
- [`docs/examples/battery_negative_price_package.yaml`](bitcoin_pv_mining/docs/examples/battery_negative_price_package.yaml)
- [`docs/examples/battery_negative_price_setup.md`](bitcoin_pv_mining/docs/examples/battery_negative_price_setup.md)

---

## Premium

**Leistung:** zusätzliche Miner (ab #2). Der erste Miner bleibt gratis.

**Aktivierung**
1. **Settings → Premium** (oder „License“) im Add-on öffnen.
2. **License Key** einfügen und speichern.  
   – Alternativ (fortgeschritten): Key in `/config/pv_mining_addon/pv_mining_local_config.yaml` hinterlegen (z. B. `premium_license_key: "…"`), falls dein Build das so erwartet.
3. UI neu laden. Zusätzliche Miner sollten freigeschaltet sein.

*(Hier einen Link einfügen, wo Nutzer einen Key erhalten.)*

---

## Tipps & Troubleshooting

- **Scripts laufen manuell, aber nicht über das Add-on?**  
  Logs prüfen, Supervisor-API-Erreichbarkeit und **exakte Entity-Namen** (inkl. Domain `script.` / `switch.`).  
  Das Add-on ruft `POST /api/services/<domain>/<service>` auf `http://supervisor/core` mit Supervisor-Token auf.
- **Cooling-„Ready“ kommt nie?**  
  Prüfe, ob das gewählte `input_boolean` / `binary_sensor` zuverlässig ON/OFF spiegelt. Timeout ggf. erhöhen.
- **Heater hängt in manuellem % fest?**  
  Auto-Modus benötigt `enabled: true`, gültiges `input_heizstab_cache`, einen Temperatursensor und `max_power_heater > 0`.
- **PV-Kostenpolitik „feedin“:** Einheiten beachten (ct/kWh vs €/kWh). Das Add-on normalisiert typische Sensorwerte (ct → €) und zieht `network_fee_up` ab.
- **Logs:** Konsolidierter Plan & Orchestrator-Logs unter `/config/pv_mining_addon/planner.log` (und Konsole).

---

## Sicherheit

- Dieses Add-on schaltet **Leistungs-Lasten**. Benutze geeignete Relais/Schütze und stelle elektrische Sicherheit sicher. Verantwortung liegt bei dir.
- „Zero-Export-Kick“ nur verwenden, wenn der Wechselrichter das unterstützt.

---

## Beitrag & Support

- Issues & PRs willkommen!  
- Bitte bei Fehlermeldungen **Logs**, **Add-on-Version**, **HA-Version** und relevante YAML-Snippets beilegen.

---

## Lizenz

Siehe [`LICENSE`](LICENSE). Ein „License“-Button wird zudem im Footer der Add-on-UI angezeigt.

GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007 <https://www.gnu.org/licenses/>
