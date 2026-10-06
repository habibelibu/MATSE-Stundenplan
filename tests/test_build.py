"""Tests fuer build_ics.py (nur Standardbibliothek).

Ausfuehren:  python3 -m unittest discover -s tests -v

Die Fixtures in tests/fixtures sind gekuerzte Nachbauten der echten Feeds
(Stand 06.10.2026). Getestet wird mit festem 'heute' = 2026-10-06.
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import build_ics  # noqa: E402

FEED2 = os.path.join(HERE, "fixtures", "feed2.json")
FEED4 = os.path.join(HERE, "fixtures", "feed4.json")
CONFIG = os.path.join(ROOT, "config.json")


def read_text(path, **kw):
    with open(path, encoding="utf-8", **kw) as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def run_build(out, lehrjahr=FEED2, wahl=FEED4, extra=()):
    argv = ["--config", CONFIG, "--lehrjahr-datei", lehrjahr, "--wahl-datei", wahl,
            "--heute", "2026-10-06", "--ausgabe", out, "--kein-heartbeat", *extra]
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = build_ics.main(argv)
    return code, err.getvalue()


def unfold(text):
    return text.replace("\r\n ", "")


def parse_events(text):
    """Minimaler, strenger ICS-Parser: Liste von Dicts {PROPERTY: wert} je VEVENT."""
    events, cur = [], None
    for line in unfold(text).split("\r\n"):
        if line == "BEGIN:VEVENT":
            assert cur is None, "verschachteltes VEVENT"
            cur = {}
        elif line == "END:VEVENT":
            events.append(cur)
            cur = None
        elif cur is not None and line:
            key, _, value = line.partition(":")
            cur[key] = value
    assert cur is None, "VEVENT nicht geschlossen"
    return events


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = os.path.join(cls.tmp.name, "test.ics")
        code, cls.err = run_build(cls.out)
        assert code == 0, cls.err
        cls.text = read_text(cls.out, newline="")
        cls.events = parse_events(cls.text)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def by_summary(self, needle):
        return [e for e in self.events if needle in e["SUMMARY"]]

    # --- Struktur -----------------------------------------------------
    def test_calendar_structure(self):
        lines = unfold(self.text).split("\r\n")
        self.assertEqual(lines[0], "BEGIN:VCALENDAR")
        self.assertEqual(lines[-2], "END:VCALENDAR")
        self.assertEqual(lines[-1], "")
        self.assertIn("X-WR-CALNAME:MATSE Stundenplan", lines)
        self.assertIn("TZID:Europe/Berlin", lines)
        self.assertEqual(self.text.count("BEGIN:VEVENT"), self.text.count("END:VEVENT"))

    def test_crlf_and_line_length(self):
        self.assertNotIn("\n", self.text.replace("\r\n", ""))
        for raw in self.text.split("\r\n"):
            self.assertLessEqual(len(raw.encode("utf-8")), 75, raw)

    def test_uids_unique_and_required_fields(self):
        uids = [e["UID"] for e in self.events]
        self.assertEqual(len(uids), len(set(uids)))
        for e in self.events:
            self.assertIn("SUMMARY", e)
            self.assertTrue(any(k.startswith("DTSTART") for k in e))
            self.assertTrue(any(k.startswith("DTEND") for k in e))

    def test_no_email_addresses(self):
        self.assertIsNone(re.search(r"[\w.]+@(?!matse-stundenplan)[\w.-]+", self.text))
        self.assertNotIn("fh-aachen.de", self.text)
        self.assertNotIn("rwth-aachen.de", self.text)

    # --- Wahlmodule -----------------------------------------------------
    def test_cpp(self):
        cpp = self.by_summary("C++")
        self.assertEqual(len(cpp), 15)
        starts = sorted(e["DTSTART;TZID=Europe/Berlin"] for e in cpp)
        self.assertEqual(starts[0], "20261009T081500")
        for e in cpp:
            self.assertTrue(e["DTSTART;TZID=Europe/Berlin"].endswith("T081500"))
            self.assertTrue(e["DTEND;TZID=Europe/Berlin"].endswith("T113000"))
        import datetime as dt
        for s in starts:
            self.assertEqual(dt.datetime.strptime(s, "%Y%m%dT%H%M%S").weekday(), 4)  # Freitag

    def test_parallelprogrammierung(self):
        pp = self.by_summary("Parallelprogrammierung")
        self.assertEqual(len(pp), 6)
        days = sorted(e["DTSTART;TZID=Europe/Berlin"][:8] for e in pp)
        self.assertEqual(days, ["20270225", "20270226", "20270301", "20270302", "20270303", "20270304"])
        for e in pp:
            self.assertTrue(e["DTSTART;TZID=Europe/Berlin"].endswith("T083000"))
            self.assertTrue(e["DTEND;TZID=Europe/Berlin"].endswith("T163000"))
            self.assertIn("Seminarraum 004", e["LOCATION"])

    def test_other_wahlmodule_excluded(self):
        for name in ("BWL", "Machine Learning", "Technische Informatik", "Technisches Englisch", "Security"):
            self.assertEqual(self.by_summary(name), [], name)

    # --- Feiertage ------------------------------------------------------
    def test_holidays_deduplicated_allday_transparent(self):
        hol = self.by_summary("Feiertag")
        names = [e["SUMMARY"] for e in hol]
        self.assertEqual(len(names), len(set(zip(names, [e["DTSTART;VALUE=DATE"] for e in hol]))))
        allerheiligen = [e for e in hol if e["DTSTART;VALUE=DATE"] == "20261101"]
        self.assertEqual(len(allerheiligen), 1)
        self.assertEqual(allerheiligen[0]["DTEND;VALUE=DATE"], "20261102")
        self.assertEqual(allerheiligen[0]["TRANSP"], "TRANSPARENT")
        # 2028 liegt ausserhalb des Zeitfensters (heute + 400 Tage)
        self.assertFalse([e for e in hol if e["DTSTART;VALUE=DATE"].startswith("2028")])

    def test_holidays_can_be_disabled(self):
        cfg = json.loads(read_text(CONFIG))
        cfg["feiertage"] = False
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "c.json")
            write_text(cfg_path, json.dumps(cfg))
            out = os.path.join(tmp, "o.ics")
            code, _ = run_build(out, extra=("--config", cfg_path))
            self.assertEqual(code, 0)
            self.assertNotIn("Feiertag", read_text(out))

    # --- Uebungen / Gruppe 2 -------------------------------------------
    def test_uebung_group2(self):
        ueb = [e for e in self.events if "Übung" in e["SUMMARY"]]
        self.assertTrue(ueb)
        first = [e for e in ueb if e["DTSTART;TZID=Europe/Berlin"] == "20261006T100000"][0]
        self.assertEqual(first["SUMMARY"], "Übung DB (B. Poniatowski)")
        self.assertEqual(first["LOCATION"], "SW23/147")
        self.assertIn("Raumänderung", first["DESCRIPTION"].replace("\\n", "\n"))
        self.assertIn("Alle Gruppen", first["DESCRIPTION"])
        second = [e for e in ueb if e["DTSTART;TZID=Europe/Berlin"] == "20261006T123000"][0]
        self.assertEqual(second["SUMMARY"], "Übung SWT (J. Poniatowski)")
        self.assertEqual(second["LOCATION"], "SW 23/147")
        third = [e for e in ueb if e["DTSTART;TZID=Europe/Berlin"] == "20261006T141500"][0]
        self.assertEqual(third["SUMMARY"], "Übung STO (Dreßen)")

    def test_changed_marker_kept_and_uid_stable(self):
        changed = [e for e in self.events if e["SUMMARY"].startswith("(!) ")]
        self.assertTrue(changed)
        # '(!)' darf die UID nicht veraendern: Termin = gleicher Termin mit/ohne Praefix
        uid_plain = build_ics.make_uid("2", "Übung 2. Lehrjahr", "2026-10-13T10:00:00", "2026-10-13T11:30:00")
        self.assertIn(uid_plain, [e["UID"] for e in self.events])

    def test_uebung_without_group_line_is_kept(self):
        item = {"title": "Übung 2. Lehrjahr", "name": "Übung 2. Lehrjahr", "start": "2026-10-20T10:00:00",
                "end": "2026-10-20T11:30:00", "location": {"name": "Hörsaal", "street": "", "nr": "", "desc": ""},
                "lecturer": {"name": "", "mail": ""}, "information": "Gruppe 1\tSTO (X)\t\tHörsaal<br />Gruppe 3\tDB (Y)\t\tS003<br />",
                "isHoliday": "", "isExercise": "1", "allDay": False, "isLecture": "0"}
        warnings = []
        ev = build_ics.build_event(item, 2, 2, warnings)
        self.assertIsNotNone(ev)
        self.assertEqual(ev["summary"], "Übung 2. Lehrjahr")
        self.assertIn("Gruppe 1", ev["description"])
        self.assertTrue(warnings)

    # --- Zeit / Zeitzone -----------------------------------------------
    def test_vtimezone_rules(self):
        self.assertIn("RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", self.text)
        self.assertIn("RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", self.text)
        self.assertIn("TZOFFSETTO:+0200", self.text)
        self.assertIn("TZOFFSETTO:+0100", self.text)

    def test_window(self):
        starts = [e.get("DTSTART;TZID=Europe/Berlin") or e["DTSTART;VALUE=DATE"] for e in self.events]
        self.assertTrue(all("20260608" <= s[:8] <= "20271110" for s in starts))

    # --- Determinismus / Fehlersicherheit -------------------------------
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a.ics"), os.path.join(tmp, "b.ics")
            run_build(a)
            run_build(b)
            self.assertEqual(read_bytes(a), read_bytes(b))
            self.assertEqual(read_bytes(a), read_bytes(self.out))

    def test_invalid_json_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "o.ics")
            write_text(out, "ALT")
            bad = os.path.join(tmp, "bad.json")
            write_text(bad, "<html>Wartungsarbeiten</html>")
            code, err = run_build(out, lehrjahr=bad)
            self.assertEqual(code, 1)
            self.assertIn("FEHLER", err)
            self.assertEqual(read_text(out), "ALT")

    def test_empty_lehrjahr_feed_fails_and_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "o.ics")
            write_text(out, "ALT")
            empty = os.path.join(tmp, "empty.json")
            write_text(empty, "[]")
            code, err = run_build(out, lehrjahr=empty)
            self.assertEqual(code, 1)
            self.assertEqual(read_text(out), "ALT")

    def test_empty_wahl_result_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "o.ics")
            empty = os.path.join(tmp, "empty.json")
            write_text(empty, "[]")
            code, _ = run_build(out, wahl=empty)
            self.assertEqual(code, 0)
            self.assertTrue(parse_events(read_text(out, newline=""))[0].get("SUMMARY"))

    def test_heartbeat(self):
        import datetime as dt
        with tempfile.TemporaryDirectory() as tmp:
            hb = os.path.join(tmp, "heartbeat.txt")
            today = dt.date(2026, 10, 6)
            self.assertTrue(build_ics.update_heartbeat(hb, today))          # fehlt -> schreiben
            self.assertFalse(build_ics.update_heartbeat(hb, today + dt.timedelta(days=20)))
            self.assertTrue(build_ics.update_heartbeat(hb, today + dt.timedelta(days=21)))


if __name__ == "__main__":
    unittest.main()
