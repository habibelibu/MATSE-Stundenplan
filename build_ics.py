#!/usr/bin/env python3
"""MATSE-Stundenplan (RWTH Aachen) -> abonnierbare ICS-Datei fuer Google Kalender.

Nur Python-Standardbibliothek, keine Abhaengigkeiten.

Normalbetrieb (holt die Feeds online):
    python3 build_ics.py

Offline-Test mit lokalen JSON-Dateien:
    python3 build_ics.py --lehrjahr-datei tests/fixtures/feed2.json \
        --wahl-datei tests/fixtures/feed4.json --heute 2026-10-06 \
        --ausgabe /tmp/test.ics --kein-heartbeat

Bei jedem Fehler (Netzwerk, ungueltiges JSON, leerer Lehrjahr-Feed) wird die
bisherige ICS-Datei NICHT veraendert und das Skript endet mit Exit-Code 1.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "matse-stundenplan-ics/1.0 (persoenliche Stundenplan-Synchronisation eines Azubis)"
UID_DOMAIN = "matse-stundenplan"
DTSTAMP = "20000101T000000Z"  # konstant, damit die Ausgabe deterministisch bleibt
HEARTBEAT_DAYS = 21
RETRY_PAUSES = (5, 20)  # Sekunden Pause vor Versuch 2 und 3
TIMEOUT = 30

DEFAULTS = {
    "lehrjahr_feed_id": 2,
    "wahlmodul_feed_id": 4,
    "gruppe": 1,
    "wahlmodule": [],
    "feiertage": True,
    "tage_zurueck": 120,
    "tage_voraus": 400,
    "feed_basis_url": "https://www.matse.itc.rwth-aachen.de/stundenplan/web/eventFeed",
    "ausgabe": "docs/stundenplan.ics",
}

VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    "TZID:Europe/Berlin",
    "X-LIC-LOCATION:Europe/Berlin",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:+0100",
    "TZOFFSETTO:+0200",
    "TZNAME:CEST",
    "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0200",
    "TZOFFSETTO:+0100",
    "TZNAME:CET",
    "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
]

CHANGE_PREFIX = re.compile(r"^\(!\)\s*")
BR = re.compile(r"<br\s*/?>", re.I)
TAGS = re.compile(r"<[^>]+>")
GROUP_RE = re.compile(r"^Gruppe\s+(\d+)\s*[:\t ]\s*(.*)$")


class FeedError(Exception):
    """Fehler beim Holen oder Lesen eines Feeds."""


# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------
def load_config(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
    except (OSError, ValueError) as exc:
        raise FeedError(f"config.json konnte nicht gelesen werden: {exc}")
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    try:
        cfg["gruppe"] = int(cfg["gruppe"])
        cfg["lehrjahr_feed_id"] = int(cfg["lehrjahr_feed_id"])
        cfg["wahlmodul_feed_id"] = int(cfg["wahlmodul_feed_id"])
        cfg["tage_zurueck"] = int(cfg["tage_zurueck"])
        cfg["tage_voraus"] = int(cfg["tage_voraus"])
    except (TypeError, ValueError) as exc:
        raise FeedError(f"config.json: ungueltiger Zahlenwert ({exc})")
    if not isinstance(cfg["wahlmodule"], list):
        raise FeedError("config.json: 'wahlmodule' muss eine Liste sein")
    return cfg


# --------------------------------------------------------------------------
# Feeds holen / lesen
# --------------------------------------------------------------------------
def parse_feed_json(raw: bytes, source: str) -> list:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FeedError(f"{source}: kein gueltiges JSON ({exc})")
    if not isinstance(data, list):
        raise FeedError(f"{source}: JSON-Array erwartet, bekommen: {type(data).__name__}")
    return data


def read_feed_file(path: str) -> list:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise FeedError(f"{path}: {exc}")
    return parse_feed_json(raw, path)


def fetch_feed(cfg: dict, feed_id: int, start: dt.date, end: dt.date) -> list:
    # Der Pfadteil "<id>&null" muss exakt so bleiben (so ruft ihn die Webseite auf).
    url = f"{cfg['feed_basis_url']}/{feed_id}&null?start={start.isoformat()}&end={end.isoformat()}"
    last_error: Exception | None = None
    for attempt in range(1, len(RETRY_PAUSES) + 2):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
            return parse_feed_json(raw, f"Feed {feed_id}")
        except (urllib.error.URLError, TimeoutError, OSError, FeedError) as exc:
            last_error = exc
            print(f"Feed {feed_id}: Versuch {attempt} fehlgeschlagen: {exc}", file=sys.stderr)
            if attempt <= len(RETRY_PAUSES):
                time.sleep(RETRY_PAUSES[attempt - 1])
    raise FeedError(f"Feed {feed_id} nicht abrufbar nach {len(RETRY_PAUSES) + 1} Versuchen: {last_error}")


# --------------------------------------------------------------------------
# Hilfsfunktionen fuer Texte
# --------------------------------------------------------------------------
def split_name(name: str) -> tuple[str, bool]:
    """Liefert (Name ohne '(!) '-Praefix, wurde_geaendert)."""
    name = (name or "").strip()
    changed = bool(CHANGE_PREFIX.match(name))
    return CHANGE_PREFIX.sub("", name).strip(), changed


def info_lines(info: str) -> list[str]:
    """information (HTML mit <br />) -> Liste bereinigter Zeilen, leere Raender entfernt."""
    text = html.unescape(BR.sub("\n", info or ""))
    text = TAGS.sub("", text)
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln == "" and (not out or out[-1] == ""):
            continue  # fuehrende/doppelte Leerzeilen weg
        out.append(ln)
    while out and out[-1] == "":
        out.pop()
    return out


def parse_group_line(line: str):
    """'Gruppe 2<TAB>DB (Eichhof)<TAB><TAB>S004' -> (2, 'DB (Eichhof)', 'S004') oder None."""
    m = GROUP_RE.match(line)
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"\t+|\s{2,}", m.group(2).strip()) if p.strip()]
    if not parts:
        return None
    subject = parts[0]
    room = parts[-1] if len(parts) > 1 else ""
    return int(m.group(1)), subject, room


def location_text(loc) -> str:
    if not isinstance(loc, dict):
        return ""
    name = (loc.get("name") or "").strip()
    addr = " ".join(x for x in ((loc.get("street") or "").strip(), (loc.get("nr") or "").strip()) if x)
    return ", ".join(x for x in (name, addr) if x)


def make_uid(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{digest}@{UID_DOMAIN}"


def parse_dt(value) -> dt.datetime:
    return dt.datetime.fromisoformat(str(value))


# --------------------------------------------------------------------------
# Events bauen
# --------------------------------------------------------------------------
def is_holiday(item: dict) -> bool:
    return str(item.get("isHoliday", "")).strip() not in ("", "0")


def build_event(item: dict, feed_id: int, group: int, warnings: list[str]) -> dict | None:
    name, changed = split_name(item.get("name") or item.get("title") or "")
    if not name:
        return None
    try:
        start = parse_dt(item["start"])
        end = parse_dt(item["end"])
    except (KeyError, ValueError) as exc:
        warnings.append(f"Termin '{name}' uebersprungen (Zeit nicht lesbar: {exc})")
        return None
    if end < start:
        end = start

    prefix = "(!) " if changed else ""
    lines = info_lines(item.get("information", ""))
    base_location = location_text(item.get("location"))
    lecturer = item.get("lecturer") if isinstance(item.get("lecturer"), dict) else {}
    lecturer_name = (lecturer.get("name") or "").strip()  # E-Mail bewusst nicht uebernommen

    summary = prefix + name
    location = base_location
    desc: list[str] = []

    group_lines = [g for g in (parse_group_line(ln) for ln in lines) if g]
    if name.lower().startswith("übung") and group_lines:
        mine = next((g for g in group_lines if g[0] == group), None)
        notes = [ln for ln in lines if ln and not parse_group_line(ln)]
        if mine:
            _, subject, room = mine
            summary = f"{prefix}Übung {subject}"
            location = room
            desc.extend(notes)
            desc.append(f"Deine Gruppe ({group}): {subject}" + (f", Raum {room}" if room else ""))
            desc.append("")
            desc.append("Alle Gruppen:")
            for g_no, g_subject, g_room in group_lines:
                desc.append(f"Gruppe {g_no}: {g_subject}" + (f", Raum {g_room}" if g_room else ""))
            if base_location:
                desc.append("")
                desc.append(f"Hauptraum laut Plan: {base_location}")
        else:
            warnings.append(f"Uebung am {start:%d.%m.%Y %H:%M}: keine Zeile fuer Gruppe {group} gefunden")
            desc.extend(lines)
    else:
        if lecturer_name:
            desc.append(f"Dozent: {lecturer_name}")
        desc.extend(lines)
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        loc_desc = (loc.get("desc") or "").strip()
        if loc_desc:
            desc.append(f"Ort: {loc_desc}")

    description = "\n".join(desc).strip()
    uid = make_uid(str(feed_id), name, start.isoformat(), end.isoformat())
    return {
        "uid": uid,
        "summary": summary,
        "location": location,
        "description": description,
        "start": start,
        "end": end,
        "allday": bool(item.get("allDay")),
    }


def build_holiday(item: dict, warnings: list[str]) -> dict | None:
    name, _ = split_name(item.get("name") or item.get("title") or "")
    try:
        start = parse_dt(item["start"])
        end = parse_dt(item.get("end") or item["start"])
    except (KeyError, ValueError) as exc:
        warnings.append(f"Feiertag '{name}' uebersprungen ({exc})")
        return None
    if end < start:
        end = start
    return {
        "uid": make_uid("holiday", name, start.date().isoformat()),
        "summary": name,
        "location": "",
        "description": "",
        "start": start,
        "end": end,
        "allday": True,
        "transparent": True,
    }


def build_events(feed_lehrjahr: list, feed_wahl: list, cfg: dict,
                 win_start: dt.date, win_end: dt.date, warnings: list[str]):
    """Gibt (events, anzahl_lehrjahr_termine_ohne_feiertage) zurueck."""
    events: dict[str, dict] = {}
    lehrjahr_count = 0
    group = cfg["gruppe"]

    for item in feed_lehrjahr:
        if not isinstance(item, dict):
            continue
        if is_holiday(item):
            if cfg["feiertage"]:
                ev = build_holiday(item, warnings)
                if ev and win_start <= ev["start"].date() <= win_end:
                    events[ev["uid"]] = ev
            continue
        ev = build_event(item, cfg["lehrjahr_feed_id"], group, warnings)
        if ev and win_start <= ev["start"].date() <= win_end:
            events[ev["uid"]] = ev
            lehrjahr_count += 1

    whitelist = [w.lower() for w in cfg["wahlmodule"] if str(w).strip()]
    for item in feed_wahl:
        if not isinstance(item, dict) or is_holiday(item):
            continue  # Feiertage kommen schon aus dem Lehrjahr-Feed
        name, _ = split_name(item.get("name") or item.get("title") or "")
        if not any(w in name.lower() for w in whitelist):
            continue
        ev = build_event(item, cfg["wahlmodul_feed_id"], group, warnings)
        if ev and win_start <= ev["start"].date() <= win_end:
            events[ev["uid"]] = ev

    ordered = sorted(events.values(), key=lambda e: (e["start"], e["uid"]))
    return ordered, lehrjahr_count


# --------------------------------------------------------------------------
# ICS schreiben
# --------------------------------------------------------------------------
def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Zeilen auf max. 75 Oktette umbrechen (RFC 5545), ohne UTF-8-Zeichen zu zerteilen."""
    parts: list[str] = []
    cur = ""
    cur_len = 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if cur_len + n > 75:
            parts.append(cur)
            cur, cur_len = " " + ch, 1 + n
        else:
            cur += ch
            cur_len += n
    parts.append(cur)
    return "\r\n".join(parts)


def event_lines(ev: dict) -> list[str]:
    out = ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{DTSTAMP}"]
    if ev["allday"]:
        end_date = max(ev["end"].date(), ev["start"].date()) + dt.timedelta(days=1)
        out.append("DTSTART;VALUE=DATE:" + ev["start"].strftime("%Y%m%d"))
        out.append("DTEND;VALUE=DATE:" + end_date.strftime("%Y%m%d"))
        if ev.get("transparent"):
            out.append("TRANSP:TRANSPARENT")
    else:
        out.append("DTSTART;TZID=Europe/Berlin:" + ev["start"].strftime("%Y%m%dT%H%M%S"))
        out.append("DTEND;TZID=Europe/Berlin:" + ev["end"].strftime("%Y%m%dT%H%M%S"))
    out.append("SUMMARY:" + esc(ev["summary"]))
    if ev["location"]:
        out.append("LOCATION:" + esc(ev["location"]))
    if ev["description"]:
        out.append("DESCRIPTION:" + esc(ev["description"]))
    out.append("END:VEVENT")
    return out


def render_ics(events: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//matse-stundenplan//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:MATSE Stundenplan",
        "X-WR-TIMEZONE:Europe/Berlin",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    lines.extend(VTIMEZONE)
    for ev in events:
        lines.extend(event_lines(ev))
    lines.append("END:VCALENDAR")
    return "".join(fold(ln) + "\r\n" for ln in lines)


def write_atomic(path: str, content: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-ics-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------
# Heartbeat (haelt den GitHub-Zeitplan am Leben)
# --------------------------------------------------------------------------
def update_heartbeat(path: str, today: dt.date) -> bool:
    last = None
    try:
        with open(path, encoding="utf-8") as fh:
            last = dt.date.fromisoformat(fh.read().strip()[:10])
    except (OSError, ValueError):
        pass
    if last is None or last > today or (today - last).days >= HEARTBEAT_DAYS:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(today.isoformat() + "\n")
        return True
    return False


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MATSE-Stundenplan -> ICS")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--lehrjahr-datei", help="Offline: lokale JSON-Datei statt Lehrjahr-Feed")
    ap.add_argument("--wahl-datei", help="Offline: lokale JSON-Datei statt Wahlmodul-Feed")
    ap.add_argument("--ausgabe", help="Zieldatei der ICS (ueberschreibt config.json)")
    ap.add_argument("--heute", help="Datum JJJJ-MM-TT (nur fuer Tests)")
    ap.add_argument("--kein-heartbeat", action="store_true", help="heartbeat.txt nicht anfassen")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        today = dt.date.fromisoformat(args.heute) if args.heute else dt.datetime.now(dt.timezone.utc).date()
        win_start = today - dt.timedelta(days=cfg["tage_zurueck"])
        win_end = today + dt.timedelta(days=cfg["tage_voraus"])

        if bool(args.lehrjahr_datei) != bool(args.wahl_datei):
            raise FeedError("Offline-Modus braucht beide Dateien: --lehrjahr-datei und --wahl-datei")
        if args.lehrjahr_datei:
            feed_lj = read_feed_file(args.lehrjahr_datei)
            feed_wahl = read_feed_file(args.wahl_datei)
        else:
            feed_lj = fetch_feed(cfg, cfg["lehrjahr_feed_id"], win_start, win_end)
            feed_wahl = fetch_feed(cfg, cfg["wahlmodul_feed_id"], win_start, win_end)

        warnings: list[str] = []
        events, lj_count = build_events(feed_lj, feed_wahl, cfg, win_start, win_end, warnings)
        if lj_count == 0:
            raise FeedError(
                f"Der Lehrjahr-Feed (ID {cfg['lehrjahr_feed_id']}) enthaelt im Zeitraum "
                f"{win_start} bis {win_end} keine Termine. Stimmt 'lehrjahr_feed_id' in config.json? "
                "Die bisherige Kalenderdatei bleibt unveraendert."
            )

        out_path = args.ausgabe or os.path.join(HERE, cfg["ausgabe"])
        write_atomic(out_path, render_ics(events))
    except FeedError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"Hinweis: {w}", file=sys.stderr)
    if not args.kein_heartbeat:
        if update_heartbeat(os.path.join(HERE, "heartbeat.txt"), today):
            print("heartbeat.txt aktualisiert")
    print(f"OK: {len(events)} Termine nach {out_path} geschrieben "
          f"({lj_count} aus dem Lehrjahr-Feed, Zeitraum {win_start} bis {win_end})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
