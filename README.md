# Access Guard für Home Assistant

Rechte pro Benutzer und ein Zugriffsprotokoll für Home Assistant.

- **Bereiche pro Benutzer sperren:** Medien, Kameras, Energie, Verlauf, Logbuch, Karte & Standorte, To-do-Listen, Kalender und einzelne Dashboards. Gesperrte Bereiche verschwinden aus der Seitenleiste und sind auch per Link oder API nicht erreichbar.
- **Menüpunkte ausblenden:** Pro Benutzer serverseitig, also auf allen Geräten gleichzeitig, auch auf Wall-Displays und in der App.
- **Entitäten verstecken:** Diese Entitäten sieht der Benutzer nirgends (Dashboards, Suche, Verlauf) und kann sie nicht schalten.
- **Zugriffsprotokoll:** Wer hat sich wann angemeldet, auf welchem Gerät, mit welcher IP? Fehlgeschlagene Anmeldungen und gesperrte Zugriffsversuche werden mitprotokolliert.
- **Admin-Seite „Zugriffe“:** Protokoll, angemeldete Geräte je Benutzer (umbenennen oder abmelden) und eine Übersicht der Einschränkungen.

Getestet mit Home Assistant 2026.8 und 2026.10.

## Installation

### Über HACS (Updates per Klick)

1. HACS → ⋮ → **Benutzerdefinierte Repositories**
2. Repository-URL dieses Repos eintragen, Typ **Integration**
3. „Access Guard“ herunterladen und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Access Guard**

Neue Versionen erscheinen danach wie gewohnt als Update. Ab Home Assistant 2026.11 übernimmt der eingebaute Marketplace die HACS-Installation automatisch.

### Manuell

Den Ordner `custom_components/access_guard` nach `/config/custom_components/access_guard` kopieren (z. B. mit dem Samba- oder File-Editor-Add-on), Home Assistant neu starten und die Integration hinzufügen.

## Einrichtung

**Einstellungen → Geräte & Dienste → Access Guard → Konfigurieren**

- **Benutzer einschränken:** Benutzer wählen, dann Bereiche sperren, Dashboards sperren, Menüpunkte ausblenden und Entitäten verstecken.
- **Protokoll-Einstellungen:** Was protokolliert wird und wie lange (Standard: 30 Tage).

Die Änderungen wirken sofort. Offene Browser-Tabs übernehmen sie nach dem Neuladen.

> Mitarbeiter sollten **normale Benutzer** sein, keine Administratoren. Administratoren können sich viele Rechte selbst zurückholen.

## Was „sperren“ genau bedeutet

| Bereich | Seitenleiste | Gesperrt zusätzlich |
|---|---|---|
| Medien | „Medien“ | Medienbrowser, Mediensuche, „Medien durchsuchen“ bei Mediaplayern, `/media/…` |
| Kameras | – | Livestream, WebRTC, Snapshots, Kamera-Entitäten, Kamera- und UniFi-Protect-Ordner im Medienbrowser, `/api/camera_proxy*`, `/api/unifiprotect/*` |
| Energie | „Energie“ | Energie-Daten |
| Verlauf | „Verlauf“ | Verlaufsdaten (auch Verlaufsdiagramme in Dashboards) |
| Logbuch | „Logbuch/Aktivität“ | Logbuch-Daten (auch Logbuch-Karten) |
| Karte & Standorte | „Karte“ | Personen- und Geräte-Tracker-Entitäten |
| To-do-Listen | „To-do-Listen“ | To-do-Daten und -Entitäten |
| Kalender | „Kalender“ | Kalender-Daten und -Entitäten |

## Protokoll

Protokolliert werden:

- **Anmeldung / Anmeldung fehlgeschlagen:** über das Login-Formular, mit eingegebenem Benutzernamen. Passwörter werden nie gespeichert.
- **Sitzung:** jedes Öffnen von App oder Browser, mit Gerät, IP und Dauer.
- **Gesperrt:** blockierte Zugriffsversuche, gebündelt (gleicher Benutzer und Bereich innerhalb von 5 Minuten). Automatische Abrufe von Dashboard-Karten (Verlauf, Energie usw.) werden zwar blockiert, aber nicht protokolliert.

Für Automationen gibt es zwei Events:

```yaml
# Benachrichtigung bei fehlgeschlagener Anmeldung
triggers:
  - trigger: event
    event_type: access_guard_login
    event_data:
      success: false
actions:
  - action: notify.notify
    data:
      message: >
        Fehlgeschlagene Anmeldung als „{{ trigger.event.data.username }}“
        von {{ trigger.event.data.device }} ({{ trigger.event.data.ip }})
```

`access_guard_denied` enthält `user`, `area`, `detail`, `ip` und `device`.

**Datenschutz:** Das Protokoll enthält personenbezogene Daten. Mitarbeiter sollten darüber informiert sein, und die Aufbewahrungsdauer sollte so kurz wie möglich sein.

## Grenzen

Home Assistant hat selbst kein Rechtesystem. Access Guard schließt die Wege, die ein normaler Benutzer in der Oberfläche oder per Link hat. Gegen jemanden, der sich gezielt mit der API und Templates beschäftigt, ist das keine Garantie. Dafür bleiben ein paar Lücken:

- Templates (z. B. Markdown-Karten) können Zustände aller Entitäten lesen.
- Kamerabilder über Token-Links (`/api/camera_proxy/…?token=…`) lassen sich keinem Benutzer zuordnen. Deshalb werden die Kamera-Entitäten versteckt, damit niemand an den Token kommt.
- Für Administratoren gelten die Einschränkungen nur teilweise.

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest
```
