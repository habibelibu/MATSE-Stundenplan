# MATSE-Stundenplan in Google Kalender

Dieses Projekt holt deinen Stundenplan (2. Lehrjahr, Übungsgruppe 2, Wahlmodule C++ und
Parallelprogrammierung) von der MATSE-Webseite und stellt ihn als **Kalender-Abo** bereit.
Google Kalender holt sich Änderungen danach selbst. Ein Rechner von dir muss dafür nicht laufen.

So funktioniert es: Einmal am Tag startet GitHub automatisch ein kleines Python-Skript, das
die Stundenplan-Daten abruft, deine Termine herausfiltert und eine Datei `stundenplan.ics`
erzeugt. Diese Datei ist unter einer festen Internet-Adresse erreichbar.

---

## Einmalige Einrichtung (ca. 15–20 Minuten)

### 1. GitHub-Account
Falls du noch keinen hast: auf <https://github.com> mit "Sign up" einen kostenlosen Account anlegen.

### 2. Neues Repository anlegen
1. Oben rechts auf **+** → **New repository**.
2. **Repository name:** z. B. `stundenplan`.
3. **Public** auswählen (nötig, damit GitHub Pages kostenlos ist).
4. Haken bei **Add a README file** setzen und auf **Create repository** klicken.

### 3. Dateien hochladen
1. Entpacke die ZIP-Datei auf deinem Rechner.
2. Im Repository: **Add file → Upload files**.
3. Ziehe **alle** Dateien und Ordner aus dem entpackten Ordner in das Browserfenster
   (`build_ics.py`, `config.json`, `heartbeat.txt`, `README.md`, die Ordner `docs`, `tests`
   und `.github`).
4. Unten auf **Commit changes** klicken.

> **Wichtig:** Der Ordner `.github` beginnt mit einem Punkt und ist auf manchen Rechnern
> versteckt (Mac: im Finder `Cmd + Shift + .` drücken). Wenn er sich nicht hochladen lässt:
> **Add file → Create new file**, als Namen `.github/workflows/update.yml` eintippen
> (die Schrägstriche legen die Ordner an), den Inhalt der Datei `update.yml` hineinkopieren
> und mit **Commit changes** speichern.
>
> Kontrolle: Im Repository muss unter **Actions** der Workflow
> **"Stundenplan aktualisieren"** auftauchen.

### 4. GitHub Pages einschalten
1. Im Repository: **Settings → Pages**.
2. Unter **Build and deployment → Source** die Option **GitHub Actions** auswählen.

(Das muss passieren, **bevor** du den Workflow zum ersten Mal startest.)

### 5. Workflow einmal starten
1. Reiter **Actions**. Falls GitHub fragt, ob Workflows aktiviert werden sollen, bestätige das.
2. Links **Stundenplan aktualisieren** wählen → rechts **Run workflow** → **Run workflow**.
3. Warte 1–2 Minuten, bis beide Schritte (`build` und `deploy`) einen grünen Haken haben.

### 6. Feed-Adresse kopieren
Die Adresse sieht so aus (Namen ersetzen):

```
https://DEIN-GITHUB-NAME.github.io/stundenplan/stundenplan.ics
```

Öffne sie im Browser. Es sollte Text erscheinen, der mit `BEGIN:VCALENDAR` anfängt
(oder die Datei wird heruntergeladen). Die Adresse findest du auch unter
**Settings → Pages** und im Schritt `deploy` des Workflow-Laufs.

### 7. In Google Kalender hinzufügen
Das geht **nur am Computer im Browser**, nicht in der Handy-App:

1. <https://calendar.google.com> öffnen.
2. Links neben **Weitere Kalender** auf **+** → **Per URL**.
3. Die Adresse aus Schritt 6 einfügen → **Kalender hinzufügen**.

Der Kalender **MATSE Stundenplan** erscheint danach automatisch auch in der Google-Kalender-App
auf dem Handy, wenn du dort mit demselben Google-Konto angemeldet bist. Falls nicht: App →
Einstellungen → den Kalender **MATSE Stundenplan** aktivieren (Haken setzen).

---

## Was danach passiert

- **Täglich gegen 04:30 UTC** (5:30 / 6:30 Uhr deutscher Zeit) holt GitHub den Plan neu.
- **Google ist langsam:** Abonnierte Kalender aktualisiert Google nur alle paar Stunden, manchmal
  erst nach etwa einem Tag. Eine kurzfristige Raumänderung kann also verspätet erscheinen. Das
  lässt sich nicht beschleunigen. Geänderte Termine erkennst du am Präfix **(!)** im Titel.
- **Normalfall: du musst nichts tun.**

---

## Wenn etwas schiefgeht

GitHub schickt dir eine **E-Mail "Run failed: Stundenplan aktualisieren"**, sobald ein Lauf
fehlschlägt. Der Kalender bleibt dann unverändert, die zuletzt gute Version ist weiter online.

So findest du die Ursache:
1. Reiter **Actions** → den roten Lauf anklicken → **build** → Schritt **ICS erzeugen**.
2. Dort steht eine Zeile, die mit `FEHLER:` beginnt.

| Meldung | Bedeutung / Was tun |
|---|---|
| `Feed … nicht abrufbar` | Die MATSE-Seite war kurz nicht erreichbar. Meist reicht es, abzuwarten. Du kannst den Lauf auch über **Re-run all jobs** wiederholen. |
| `kein gültiges JSON` | Die Seite hat etwas anderes als Plandaten geliefert (z. B. Wartungsseite). Abwarten und morgen erneut prüfen. Bleibt es dauerhaft, hat sich vermutlich das Format geändert, dann schick die Log-Zeilen weiter. |
| `Lehrjahr-Feed … keine Termine` | Die `lehrjahr_feed_id` in `config.json` passt nicht mehr (z. B. neues Lehrjahr). Siehe unten. |
| `Permission denied to github-actions[bot]` | **Settings → Actions → General → Workflow permissions → Read and write permissions** auswählen, speichern, Lauf wiederholen. |

**Zeitplan abgeschaltet?** GitHub deaktiviert geplante Workflows in öffentlichen Repositories
nach 60 Tagen ohne Aktivität. Dagegen schreibt das Skript mindestens alle 3 Wochen einen
Eintrag in `heartbeat.txt`. Sollte GitHub den Zeitplan trotzdem abschalten, erscheint unter
**Actions** ein Hinweis mit dem Knopf **Enable workflow**, ein Klick genügt.

---

## Einstellungen ändern (`config.json`)

Datei im Repository anklicken → Stift-Symbol (Edit) → ändern → **Commit changes**.
Danach unter **Actions → Run workflow** einmal manuell starten.

| Eintrag | Bedeutung |
|---|---|
| `lehrjahr_feed_id` | Nummer des Feeds für dein Lehrjahr (aktuell `2` = 2. Lehrjahr) |
| `wahlmodul_feed_id` | Nummer des Feeds mit den Wahlmodulen (aktuell `4`) |
| `gruppe` | deine Übungsgruppe (1–4) |
| `wahlmodule` | Liste von Namensteilen der Wahlmodule, die du belegt hast. Groß-/Kleinschreibung egal. Beispiel: `["C++", "Parallelprogrammierung"]` |
| `feiertage` | `true` = Feiertage als ganztägige Termine anzeigen, `false` = ausblenden |
| `tage_zurueck` / `tage_voraus` | Zeitfenster rund um heute (Standard: 120 Tage zurück, 400 Tage voraus) |

Die Anführungszeichen, Kommas und eckigen Klammern in der Datei dürfen nicht verloren gehen.

### Beim Wechsel ins 3. Lehrjahr

Ich konnte nicht automatisch ermitteln, welche Feed-Nummer zu welchem Lehrjahr gehört. Die
Seite lädt ihre Daten per JavaScript nach. So findest du es selbst in 2 Minuten heraus:

1. Öffne <https://www.matse.itc.rwth-aachen.de/stundenplan/web/index.html> und wähle dein neues
   Lehrjahr bzw. die gewünschte Ansicht aus.
2. Drücke **F12** → Reiter **Netzwerk** (Network) → Filter **Fetch/XHR**, dann Seite neu laden.
3. Suche die Anfrage, die so aussieht: `eventFeed/3&null?start=…`. Die Zahl direkt nach
   `eventFeed/` ist die gesuchte Nummer.
4. Trage sie in `config.json` bei `lehrjahr_feed_id` ein (bei neuen Wahlmodulen ggf. auch
   `wahlmodul_feed_id` und `wahlmodule`) und passe `gruppe` an, falls sich deine Gruppe ändert.

### Andere Wahlmodule

Ergänze den Namen (oder einen eindeutigen Teil davon) in `wahlmodule`, genau wie er auf der
Stundenplan-Seite steht. Nur Termine, deren Name diesen Text enthält, werden übernommen.

---

## Technische Details (nur falls du neugierig bist)

- `build_ics.py` benötigt nur Python 3 (Standardbibliothek), keine Installation von Paketen.
- Die Ausgabe ist deterministisch: gleiche Daten ergeben eine byte-identische Datei. Deshalb
  wird nur bei echten Änderungen committet.
- Jeder Termin hat eine stabile ID (aus Feed, Name, Start und Ende). Eine Raumänderung
  aktualisiert den vorhandenen Termin, statt einen zweiten anzulegen. Eine Zeitänderung
  entfernt den alten und legt den neuen Termin an.
- In der ICS stehen **keine E-Mail-Adressen** von Dozenten. Das Repository ist öffentlich,
  die Datei enthält nur, was ohnehin auf der Stundenplan-Seite steht, plus deine Gruppennummer
  im Dateiinhalt (Beschreibung der Übungstermine).
- Tests (optional, auf deinem Rechner mit Python 3):
  `python3 -m unittest discover -s tests -v`
- Lokaler Probelauf mit den mitgelieferten Beispieldaten:
  `python3 build_ics.py --lehrjahr-datei tests/fixtures/feed2.json --wahl-datei tests/fixtures/feed4.json --heute 2026-10-06 --ausgabe /tmp/test.ics --kein-heartbeat`
- Die Dateien in `tests/fixtures` sind gekürzte Nachbauten der echten Feeds (Stand 06.10.2026).
