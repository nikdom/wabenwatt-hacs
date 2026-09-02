# Wabenwatt für Home Assistant

[![Validate](https://github.com/nikdom/wabenwatt-hacs/actions/workflows/validate.yml/badge.svg)](https://github.com/nikdom/wabenwatt-hacs/actions/workflows/validate.yml)

Meldet die aktuelle Leistung deiner PV-Anlage und deines Hausspeichers jede Minute an [wabenwatt.de](https://wabenwatt.de) – ohne `configuration.yaml`, ohne Blueprint. *English below.*

## Was die Integration tut

- Pro **Gerät** einmal hinzufügen – PV-Anlage oder Hausspeicher: Token eintragen, Sensor(en) wählen, fertig. Der Anlagenname kommt von wabenwatt – so siehst du sofort, ob du den richtigen Token erwischt hast. Beim Speichern geht sofort ein erster Report raus – die Anlage erscheint innerhalb von zwei Minuten als aktiv.
- Danach alle 60 Sekunden ein Report mit dem aktuellen Wert. `kW`-Sensoren werden nach Watt umgerechnet; mehrere String-Sensoren werden addiert.
- Fehler sind in Home Assistant sichtbar: Entitäten **Status**, **Letzter Report**, **Letzter Fehler** und **Gemeldete Leistung**. Ein widerrufener Token löst die übliche „Erneut authentifizieren“-Meldung aus.
- **Hausspeicher als eigenes Gerät:** eigener Token, Leistungssensor (positiv = Entladung, mit Schalter zum Umkehren) und optional der Ladestand in Prozent. Entitäten **Gemeldete Batterieleistung** und **Gemeldeter Ladestand**.

> **Geändert in 0.3.0:** Der Batterie-Sensor im PV-Formular ist entfallen. Ein Hausspeicher ist bei wabenwatt seit 2026-09-02 ein eigenes Gerät mit eigenem Token — er kann damit einen Ladestand melden, hängt nicht an einer Anlage und bleibt bestehen, wenn du die Anlage löschst. Wer den alten Weg genutzt hat: den Speicher auf wabenwatt.de anlegen und hier als zweites Gerät hinzufügen. Ein PV-Eintrag mit altem Batterie-Sensor meldet weiterhin, nur eben ohne Akkuwert.

## Installation

**Über HACS (empfohlen):**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikdom&repository=wabenwatt-hacs&category=integration)

Oder manuell in HACS: *Integrationen → ⋮ → Benutzerdefinierte Repositories* → `https://github.com/nikdom/wabenwatt-hacs` (Kategorie „Integration“) → installieren → Home Assistant neu starten.

**Ohne HACS:** den Ordner `custom_components/wabenwatt` in dein `config/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Wabenwatt*.
2. Gerätetyp wählen (**PV-Anlage** oder **Hausspeicher**) und den Token eintragen – du findest ihn auf wabenwatt.de auf der Seite des jeweiligen Geräts. Mehr braucht es nicht: Name und Gerät ergeben sich aus dem Token.
3. Leistungssensor(en) wählen:
   - **Steckersolar** (Micro-Wechselrichter): der AC-Wert.
   - **String-/Hybrid-Wechselrichter:** die DC-Leistung der Strings – nicht der AC-Wert, der bei Hybridanlagen auch die Abgabe des Akkus enthält.
   - Keine Gesamt-Entität? Je String eine Entität wählen, die Werte werden addiert.
4. Beim **Hausspeicher** stattdessen: den Batterieleistungs-Sensor wählen (Wabenwatt erwartet positiv = Entladung; sonst „Vorzeichen umkehren“ einschalten) und optional den Ladestand-Sensor in Prozent.

Weiteres Gerät? Die Integration einfach noch einmal hinzufügen. Sensoren später ändern: *Konfigurieren* am Eintrag.

## Fehlersuche

| Status | Bedeutung |
|---|---|
| **Meldet** | Der letzte Report wurde angenommen. |
| **Sensor nicht verfügbar** | Ein gewählter Sensor liefert gerade keinen Zahlenwert (`unavailable`/`unknown`). Es wird bewusst **nichts** gesendet – ein Teilwert wäre falsch. Welcher Sensor blockiert, steht im Attribut `blocking_entity`. |
| **Fehler** | Der Server hat den Report abgelehnt; Code und Meldung stehen in **Letzter Fehler** (z. B. `REPORT_REJECTED` = Wert unplausibel hoch, meist kW statt W; `REPORT_INVALID` = der Token gehört zum anderen Gerätetyp). |

Ein `0`-Wert in der Nacht ist korrekt und wird gemeldet. Leicht negative Werte (Standby-Verbrauch) werden als `0` gesendet.

**Letzter Fehler wird beim nächsten erfolgreichen Report gelöscht.** Steht dort dauerhaft `RATE_LIMITED`, obwohl die Anlage aktiv meldet: das war ein Bug bis v0.2.0 (behoben in v0.2.1) — der Setup-Validierungs-Report und der erste automatische Report lagen zu dicht beieinander und der zweite wurde vom Server abgelehnt; ein einmaliger, harmloser Treffer blieb aber für immer als „letzter Fehler" stehen. Aktualisieren auf v0.2.1 oder neuer behebt das.

---

# Wabenwatt for Home Assistant

Reports your PV plant's current power to [wabenwatt.de](https://wabenwatt.de) every minute – no `configuration.yaml`, no blueprint.

## What it does

- Add once per plant: enter the token, pick the power sensor(s), done. The plant's name comes from wabenwatt, so you see right away whether you grabbed the right token. A first report is sent on save, so the plant shows up as active within two minutes.
- Afterwards one report every 60 seconds. `kW` sensors are converted to watts; several string sensors are added up.
- Errors are visible in Home Assistant: **Status**, **Last report**, **Last error** and **Reported power** entities. A revoked token triggers the usual re-authentication notice.
- **Home storage as its own device:** its own token, a power sensor (positive = discharging, with a switch to invert) and optionally the state of charge in percent. Entities **Reported battery power** and **Reported state of charge**.

> **Changed in 0.3.0:** the battery sensor is gone from the PV form. On wabenwatt a home battery has been its own device with its own token since 2026-09-02 — it can report a state of charge, does not hang off a plant, and survives that plant's deletion. If you used the old path: create the storage on wabenwatt.de and add it here as a second device. A PV entry with an old battery sensor keeps reporting, just without the battery value.

## Installation

Via HACS: use the badge above, or add `https://github.com/nikdom/wabenwatt-hacs` as a custom repository (category *Integration*), install, restart Home Assistant. Without HACS: copy `custom_components/wabenwatt` into your `config/custom_components/` and restart.

## Setup

1. *Settings → Devices & services → Add integration → Wabenwatt*.
2. Enter the plant token from wabenwatt.de (plant → Integrations tab → “Show token”). That is all: name and plant follow from the token.
3. Pick the power sensor(s): plug-in solar → the AC value; string/hybrid inverters → the DC power of the strings (not the AC value, which for hybrid systems includes the battery output). No total entity? Pick one per string, they are summed.
4. For **home storage** instead: pick the battery power sensor (positive = discharging; otherwise enable “Invert the sign”) and optionally the state-of-charge sensor in percent.

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
