# Wabenwatt für Home Assistant

[![Validate](https://github.com/nikdom/wabenwatt-hacs/actions/workflows/validate.yml/badge.svg)](https://github.com/nikdom/wabenwatt-hacs/actions/workflows/validate.yml)

Meldet die aktuelle Leistung deiner PV-Anlage, deines Hausspeichers und deines Netzanschlusses (Zähler) jede Minute an [wabenwatt.de](https://wabenwatt.de) – ohne `configuration.yaml`, ohne Blueprint. *English below.*

## Was die Integration tut

- Pro **Gerät** einmal hinzufügen – PV-Anlage, Hausspeicher oder Zähler: Token eintragen, Sensor(en) wählen, fertig. Der Anlagenname kommt von wabenwatt – so siehst du sofort, ob du den richtigen Token erwischt hast. Beim Speichern geht sofort ein erster Report raus – die Anlage erscheint innerhalb von zwei Minuten als aktiv.
- Danach alle 60 Sekunden ein Report mit dem aktuellen Wert. `kW`-Sensoren werden nach Watt umgerechnet; mehrere String-Sensoren werden addiert.
- Fehler sind in Home Assistant sichtbar: Entitäten **Status**, **Letzter Report**, **Letzter Fehler** und **Gemeldete Leistung**. Ein widerrufener Token löst die übliche „Erneut authentifizieren“-Meldung aus.
- **Hausspeicher als eigenes Gerät:** eigener Token, Leistungssensor (positiv = Entladung, mit Schalter zum Umkehren) und optional der Ladestand in Prozent. Entitäten **Gemeldete Batterieleistung** und **Gemeldeter Ladestand**.
- **Zähler (Netzanschluss, neu in 0.5.0)** als eigenes Gerät: eigener Token, die Netzleistung mit Vorzeichen und optional die Zählerstände. Entität **Gemeldete Netzleistung** (W, positiv = Bezug, negativ = Einspeisung).

> **Geändert in 0.3.0:** Der Batterie-Sensor im PV-Formular ist entfallen. Ein Hausspeicher ist bei wabenwatt seit 2026-09-02 ein eigenes Gerät mit eigenem Token — er kann damit einen Ladestand melden, hängt nicht an einer Anlage und bleibt bestehen, wenn du die Anlage löschst. Wer den alten Weg genutzt hat: den Speicher auf wabenwatt.de anlegen und hier als zweites Gerät hinzufügen. Ein PV-Eintrag mit altem Batterie-Sensor meldet weiterhin, nur eben ohne Akkuwert.

## Installation

**Über HACS (empfohlen):**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikdom&repository=wabenwatt-hacs&category=integration)

Oder manuell in HACS: *Integrationen → ⋮ → Benutzerdefinierte Repositories* → `https://github.com/nikdom/wabenwatt-hacs` (Kategorie „Integration“) → installieren → Home Assistant neu starten.

**Ohne HACS:** den Ordner `custom_components/wabenwatt` in dein `config/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Wabenwatt*.
2. Gerätetyp wählen (**PV-Anlage**, **Hausspeicher** oder **Zähler**) und den Token eintragen – du findest ihn auf wabenwatt.de auf der Seite des jeweiligen Geräts. Mehr braucht es nicht: Name und Gerät ergeben sich aus dem Token.
3. Leistungssensor(en) wählen:
   - **Steckersolar** (Micro-Wechselrichter): der AC-Wert.
   - **String-/Hybrid-Wechselrichter:** die DC-Leistung der Strings – nicht der AC-Wert, der bei Hybridanlagen auch die Abgabe des Akkus enthält.
   - Keine Gesamt-Entität? Je String eine Entität wählen, die Werte werden addiert.
4. Beim **Hausspeicher** stattdessen: den Batterieleistungs-Sensor wählen (Wabenwatt erwartet positiv = Entladung; sonst „Vorzeichen umkehren“ einschalten) und optional den Ladestand-Sensor in Prozent.
5. Beim **Zähler** stattdessen die Netzleistung in **genau einer** von zwei Formen (siehe unten) und optional die Zählerstände.

### Zähler (Netzanschluss)

**Vorzeichen:** Wabenwatt erwartet **positiv = Bezug aus dem Netz, negativ = Einspeisung**. Negative Werte sind hier ein echter Messwert und werden nicht auf `0` gekappt (anders als bei PV).

**Netzleistung – genau eine Form:**

1. **Ein Sensor mit Vorzeichen** (der Normalfall). Hält dein Sensor es andersherum (positiv = Einspeisung, z. B. „Netzeinspeisung“ mancher Wechselrichter-Integrationen), „Vorzeichen umkehren“ einschalten.
2. **Zwei Sensoren, beide ≥ 0:** Bezugsleistung und Einspeiseleistung getrennt (z. B. DSMR-Zähler, manche Wechselrichter). Gemeldet wird Bezug − Einspeisung.

Leistung in `W`, `kW`, `MW` oder `mW` (ohne Einheit = W).

**Zählerstände (optional):** Bezug gesamt (OBIS 1.8.0) und Einspeisung gesamt (2.8.0) als Energie-Sensoren in `Wh`, `kWh` oder `MWh`. Sie dienen nur der Anzeige auf der Zählerseite; die Energiebilanz rechnet wabenwatt selbst aus der Leistung. Liefert ein Zählerstand gerade keinen Wert, wird der Report trotzdem gesendet – der Stand dann als leer (`null`). Liefert die **Netzleistung** keinen Wert, wird nichts gesendet.

**Welche Sensoren passen typischerweise:**

| Quelle | Netzleistung | Zählerstände |
|---|---|---|
| **Tibber Pulse** | `power` minus `power_production` → Form 2 (beide ≥ 0) | `accumulated_consumption` / `accumulated_production` sind Tageswerte, nicht nehmen; bei manchen Zählern gibt es `last_meter_consumption` / `last_meter_production` |
| **SML-Lesekopf** über Tasmota oder ESPHome | OBIS 16.7.0 (vorzeichenbehaftet) → Form 1 | 1.8.0 / 2.8.0 |
| **Shelly 3EM / Pro 3EM** | Gesamtwirkleistung (`total_act_power`, Summe der drei Phasen) → Form 1 | Gesamtenergie Bezug / Rückspeisung (`total_act_energy` / `total_act_ret_energy`) |
| **Hybrid-Wechselrichter** (Huawei, Fronius, SMA, Kostal, SolarEdge …) | Netz- bzw. Zählerleistung des angeschlossenen Smart Meters → Form 1, Vorzeichen prüfen | Bezug / Einspeisung gesamt, falls die Integration sie liefert |
| **evcc** | Netzleistung (`grid power`) → Form 1, evcc hält bereits positiv = Bezug | – |

Im Zweifel: beim Kochen muss der Wert positiv sein, bei voller Sonne und wenig Verbrauch negativ.

Weiteres Gerät? Die Integration einfach noch einmal hinzufügen. Sensoren später ändern: *Konfigurieren* am Eintrag.

## Fehlersuche

| Status | Bedeutung |
|---|---|
| **Meldet** | Der letzte Report wurde angenommen. |
| **Sensor nicht verfügbar** | Ein gewählter Sensor liefert gerade keinen Zahlenwert (`unavailable`/`unknown`). Es wird bewusst **nichts** gesendet – ein Teilwert wäre falsch. Welcher Sensor blockiert, steht im Attribut `blocking_entity`. |
| **Fehler** | Der Server hat den Report abgelehnt; Code und Meldung stehen in **Letzter Fehler** (z. B. `REPORT_REJECTED` = Wert unplausibel hoch, meist kW statt W; `REPORT_INVALID` = der Token gehört zum anderen Gerätetyp). |

Ein `0`-Wert in der Nacht ist korrekt und wird gemeldet. Leicht negative PV-Werte (Standby-Verbrauch) werden als `0` gesendet; beim Zähler bleibt negativ negativ (Einspeisung).

**Letzter Fehler wird beim nächsten erfolgreichen Report gelöscht.** Steht dort dauerhaft `RATE_LIMITED`, obwohl die Anlage aktiv meldet: das war ein Bug bis v0.2.0 (behoben in v0.2.1) — der Setup-Validierungs-Report und der erste automatische Report lagen zu dicht beieinander und der zweite wurde vom Server abgelehnt; ein einmaliger, harmloser Treffer blieb aber für immer als „letzter Fehler" stehen. Aktualisieren auf v0.2.1 oder neuer behebt das.

---

# Wabenwatt for Home Assistant

Reports the current power of your PV plant, your home storage and your grid connection (meter) to [wabenwatt.de](https://wabenwatt.de) every minute – no `configuration.yaml`, no blueprint.

## What it does

- Add once per plant: enter the token, pick the power sensor(s), done. The plant's name comes from wabenwatt, so you see right away whether you grabbed the right token. A first report is sent on save, so the plant shows up as active within two minutes.
- Afterwards one report every 60 seconds. `kW` sensors are converted to watts; several string sensors are added up.
- Errors are visible in Home Assistant: **Status**, **Last report**, **Last error** and **Reported power** entities. A revoked token triggers the usual re-authentication notice.
- **Home storage as its own device:** its own token, a power sensor (positive = discharging, with a switch to invert) and optionally the state of charge in percent. Entities **Reported battery power** and **Reported state of charge**.
- **Grid meter (new in 0.5.0)** as its own device: its own token, the signed grid power and optionally the meter readings. Entity **Reported grid power** (W, positive = import, negative = export).

> **Changed in 0.3.0:** the battery sensor is gone from the PV form. On wabenwatt a home battery has been its own device with its own token since 2026-09-02 — it can report a state of charge, does not hang off a plant, and survives that plant's deletion. If you used the old path: create the storage on wabenwatt.de and add it here as a second device. A PV entry with an old battery sensor keeps reporting, just without the battery value.

## Installation

Via HACS: use the badge above, or add `https://github.com/nikdom/wabenwatt-hacs` as a custom repository (category *Integration*), install, restart Home Assistant. Without HACS: copy `custom_components/wabenwatt` into your `config/custom_components/` and restart.

## Setup

1. *Settings → Devices & services → Add integration → Wabenwatt*.
2. Enter the plant token from wabenwatt.de (plant → Integrations tab → “Show token”). That is all: name and plant follow from the token.
3. Pick the power sensor(s): plug-in solar → the AC value; string/hybrid inverters → the DC power of the strings (not the AC value, which for hybrid systems includes the battery output). No total entity? Pick one per string, they are summed.
4. For **home storage** instead: pick the battery power sensor (positive = discharging; otherwise enable “Invert the sign”) and optionally the state-of-charge sensor in percent.
5. For a **grid meter** instead: the grid power in **exactly one** of two forms (below) and optionally the meter readings.

### Grid meter

**Sign:** wabenwatt expects **positive = import from the grid, negative = export**. Negative values are a real measurement here and are not clamped to `0` (unlike PV).

**Grid power — exactly one form:**

1. **One signed sensor** (the usual case). If yours has it the other way round (positive = export, e.g. “grid feed-in” of some inverter integrations), enable “Invert the sign”.
2. **Two sensors, both ≥ 0:** import power and export power separately (e.g. DSMR meters, some inverters). Reported is import − export.

Power in `W`, `kW`, `MW` or `mW` (no unit = W).

**Meter readings (optional):** total import (OBIS 1.8.0) and total export (2.8.0) as energy sensors in `Wh`, `kWh` or `MWh`. Only shown on the meter's page; wabenwatt computes the energy balance from the power itself. If a reading has no value right now, the report is still sent with that reading empty (`null`). If the **grid power** has no value, nothing is sent.

**Sensors that typically work:**

| Source | Grid power | Meter readings |
|---|---|---|
| **Tibber Pulse** | `power` minus `power_production` → form 2 (both ≥ 0) | `accumulated_consumption` / `accumulated_production` are daily values, don't use them; some meters offer `last_meter_consumption` / `last_meter_production` |
| **SML reading head** via Tasmota or ESPHome | OBIS 16.7.0 (signed) → form 1 | 1.8.0 / 2.8.0 |
| **Shelly 3EM / Pro 3EM** | total active power (`total_act_power`, all three phases) → form 1 | total energy / returned energy (`total_act_energy` / `total_act_ret_energy`) |
| **Hybrid inverters** (Huawei, Fronius, SMA, Kostal, SolarEdge …) | grid/meter power of the attached smart meter → form 1, check the sign | total import / export if the integration provides them |
| **evcc** | grid power → form 1, evcc already uses positive = import | – |

When in doubt: while cooking the value must be positive, in full sun with little consumption negative.

Another plant? Add the integration again. Change sensors later via *Configure* on the entry.

## Troubleshooting

| Status | Meaning |
|---|---|
| **Reporting** | The last report was accepted. |
| **Sensor unavailable** | A selected sensor has no numeric value right now. Nothing is sent on purpose – a partial value would be wrong. The `blocking_entity` attribute names the sensor. |
| **Error** | The server rejected the report; code and message are in **Last error** (e.g. `REPORT_REJECTED` = implausibly high, usually kW instead of W; `REPORT_INVALID` = the token belongs to the other device type). |

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## Releases

HACS offers GitHub releases as installable versions, so every release is a tag — never a moving branch:

1. Bump `version` in `custom_components/wabenwatt/manifest.json` **and** `pyproject.toml` (same value), commit.
2. Tag that commit `vX.Y.Z` and push the tag: `git tag v0.3.0 && git push origin v0.3.0`.
3. The `Release` workflow refuses a tag whose version does not match, runs lint and tests, and only then creates the GitHub release with generated notes.

Never move or delete a published tag; ship a fix as the next version.
