# Wabenwatt für Home Assistant

[![Validate](https://github.com/nikdom/wabenwatt-hacs/actions/workflows/validate.yml/badge.svg)](https://github.com/nikdom/wabenwatt-hacs/actions/workflows/validate.yml)

Meldet die aktuelle Leistung deiner PV-Anlage jede Minute an [wabenwatt.de](https://wabenwatt.de) – ohne `configuration.yaml`, ohne Blueprint, ohne Neustart. *English below.*

## Was die Integration tut

- Pro Anlage einmal hinzufügen: Token eintragen, Leistungssensor(en) wählen, fertig. Beim Speichern geht sofort ein erster Report raus – die Anlage erscheint innerhalb von zwei Minuten als aktiv.
- Danach alle 60 Sekunden ein Report mit dem aktuellen Wert. `kW`-Sensoren werden nach Watt umgerechnet; mehrere String-Sensoren werden addiert.
- Fehler sind in Home Assistant sichtbar: Entitäten **Status**, **Letzter Report**, **Letzter Fehler** und **Gemeldete Leistung**. Ein widerrufener Token löst die übliche „Erneut authentifizieren“-Meldung aus.
- Optional ein Batterie-Sensor für Anlagen mit getrennter Batteriemessung (Hybrid-Wechselrichter), inklusive Schalter zum Umkehren des Vorzeichens.

## Installation

**Über HACS (empfohlen):**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikdom&repository=wabenwatt-hacs&category=integration)

Oder manuell in HACS: *Integrationen → ⋮ → Benutzerdefinierte Repositories* → `https://github.com/nikdom/wabenwatt-hacs` (Kategorie „Integration“) → installieren → Home Assistant neu starten.

**Ohne HACS:** den Ordner `custom_components/wabenwatt` in dein `config/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Wabenwatt*.
2. Anlagen-Token eintragen – du findest ihn auf wabenwatt.de im Integrations-Tab der Anlage unter „Token anzeigen“.
3. Leistungssensor(en) wählen:
   - **Steckersolar** (Micro-Wechselrichter): der AC-Wert.
   - **String-/Hybrid-Wechselrichter:** die DC-Leistung der Strings – nicht der AC-Wert, der bei Hybridanlagen auch die Abgabe des Akkus enthält.
   - Keine Gesamt-Entität? Je String eine Entität wählen, die Werte werden addiert.
4. Nur bei getrennter Batteriemessung: den Batterie-Sensor setzen (Wabenwatt erwartet positiv = Entladung; sonst „Vorzeichen umkehren“ einschalten).

Weitere Anlage? Die Integration einfach noch einmal hinzufügen. Sensoren später ändern: *Konfigurieren* am Eintrag.

## Fehlersuche

| Status | Bedeutung |
|---|---|
| **Meldet** | Der letzte Report wurde angenommen. |
| **Sensor nicht verfügbar** | Ein gewählter Sensor liefert gerade keinen Zahlenwert (`unavailable`/`unknown`). Es wird bewusst **nichts** gesendet – ein Teilwert wäre falsch. Welcher Sensor blockiert, steht im Attribut `blocking_entity`. |
| **Fehler** | Der Server hat den Report abgelehnt; Code und Meldung stehen in **Letzter Fehler** (z. B. `REPORT_REJECTED` = Wert unplausibel hoch, meist kW statt W; `BATTERY_NOT_SUPPORTED` = Anlage ist nicht für getrennte Batteriemessung eingerichtet). |

Ein `0`-Wert in der Nacht ist korrekt und wird gemeldet. Leicht negative Werte (Standby-Verbrauch) werden als `0` gesendet.

---

# Wabenwatt for Home Assistant

Reports your PV plant's current power to [wabenwatt.de](https://wabenwatt.de) every minute – no `configuration.yaml`, no blueprint, no restart.

## What it does

- Add once per plant: enter the token, pick the power sensor(s), done. A first report is sent on save, so the plant shows up as active within two minutes.
- Afterwards one report every 60 seconds. `kW` sensors are converted to watts; several string sensors are added up.
- Errors are visible in Home Assistant: **Status**, **Last report**, **Last error** and **Reported power** entities. A revoked token triggers the usual re-authentication notice.
- Optional battery sensor for plants with separate battery metering (hybrid inverters), including a switch to invert the sign.

## Installation

Via HACS: use the badge above, or add `https://github.com/nikdom/wabenwatt-hacs` as a custom repository (category *Integration*), install, restart Home Assistant. Without HACS: copy `custom_components/wabenwatt` into your `config/custom_components/` and restart.

## Setup

1. *Settings → Devices & services → Add integration → Wabenwatt*.
2. Enter the plant token from wabenwatt.de (plant → Integrations tab → “Show token”).
3. Pick the power sensor(s): plug-in solar → the AC value; string/hybrid inverters → the DC power of the strings (not the AC value, which for hybrid systems includes the battery output). No total entity? Pick one per string, they are summed.
4. Only with separate battery metering: set the battery sensor (positive = discharging; otherwise enable “Invert battery sign”).

Another plant? Add the integration again. Change sensors later via *Configure* on the entry.

## Troubleshooting

| Status | Meaning |
|---|---|
| **Reporting** | The last report was accepted. |
| **Sensor unavailable** | A selected sensor has no numeric value right now. Nothing is sent on purpose – a partial value would be wrong. The `blocking_entity` attribute names the sensor. |
| **Error** | The server rejected the report; code and message are in **Last error** (e.g. `REPORT_REJECTED` = implausibly high, usually kW instead of W; `BATTERY_NOT_SUPPORTED` = plant not configured for separate battery metering). |

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```
