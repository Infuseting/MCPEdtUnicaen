import json
import urllib.request
import urllib.parse
import datetime
import re
from utils import *
from typing import Optional

base_url = "https://edt.infuseting.fr/assets/json/"
prof_url = base_url + "prof.json"
salle_url = base_url + "salle.json"
student_url = base_url + "student.json"
univ_url = base_url + "univ.json"


def load_json(path: str):
    """Load JSON from local file or URL."""
    if path.startswith("http://") or path.startswith("https://"):
        with urllib.request.urlopen(path) as resp:
            return json.load(resp)
    else:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

_prof_data = load_json(prof_url).get("prof", [])
_salle_data = load_json(salle_url).get("salle", [])
_student_data = load_json(student_url).get("student", [])
_univ_data = load_json(univ_url).get("univ", [])

def parse_limit_to_datetime(value: Optional[str]) -> Optional[datetime.datetime]:
    """Try to parse a start/end limit string into a datetime.

    Accepts:
    - ISO-like datetime strings (YYYY-MM-DDTHH:MM[:SS] or YYYY-MM-DD HH:MM[:SS])
    - Time-only strings like HH:MM or HH:MM:SS (interpreted for today)
    Returns a naive datetime or None if empty/invalid.
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Try ISO datetime parse first (also accepts 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DDTHH:MM')
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        pass

    # Common date-only formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    # Interpret as start of that day (00:00:00)
    m_date_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m_date_iso:
        try:
            d = datetime.date.fromisoformat(s)
            return datetime.datetime.combine(d, datetime.time.min)
        except Exception:
            pass

    m_date_eu = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", s)
    if m_date_eu:
        try:
            day = int(m_date_eu.group(1))
            month = int(m_date_eu.group(2))
            year = int(m_date_eu.group(3))
            d = datetime.date(year, month, day)
            return datetime.datetime.combine(d, datetime.time.min)
        except Exception:
            pass

    # Natural words
    if s.lower() in ("today", "aujourd'hui", "aujourdhui"):
        d = datetime.date.today()
        return datetime.datetime.combine(d, datetime.time.min)
    if s.lower() in ("tomorrow", "demain"):
        d = datetime.date.today() + datetime.timedelta(days=1)
        return datetime.datetime.combine(d, datetime.time.min)

    # If it's only a time like HH:MM or HH:MM:SS, interpret for today
    m = re.match(r"^(\d{1,2}):(\d{2})(:(\d{2}))?$", s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        second = int(m.group(4)) if m.group(4) else 0
        today = datetime.date.today()
        try:
            return datetime.datetime.combine(today, datetime.time(hour, minute, second))
        except Exception:
            return None

    # Unknown format
    return None
def find_entries_by_name(name: str):
    """Search in prof/student/salle/univ for matching descTT/nameUniv.

    Returns a list of entries with keys: type, desc, adeUniv, adeResources, adeProjectId
    """
    name_l = name.lower()
    results = []

    def check_list(items, key_desc, typ):
        for it in items:
            desc = (it.get(key_desc) or "").strip()
            if desc and name_l in desc.lower():
                results.append({
                    "type": typ,
                    "desc": desc,
                    "adeUniv": it.get("adeUniv"),
                    "adeResources": it.get("adeResources"),
                    "adeProjectId": int(it.get("adeProjectId")) if it.get("adeProjectId") is not None else None,
                })

    check_list(_prof_data, "descTT", "prof")
    check_list(_student_data, "descTT", "student")
    check_list(_salle_data, "descTT", "salle")
    # univ entries have nameUniv and timetable list
    for u in _univ_data:
        if name_l in (u.get("nameUniv","") or "").lower():
            results.append({
                "type": "univ",
                "desc": u.get("nameUniv"),
                "adeUniv": u.get("adeUniv"),
                "adeResources": None,
                "adeProjectId": None,
                "timetable": u.get("timetable", []),
            })
        # also check timetable entries
        for t in u.get("timetable", []):
            if name_l in (t.get("descTT","") or "").lower():
                results.append({
                    "type": "univ-timetable",
                    "desc": t.get("descTT"),
                    "adeUniv": u.get("adeUniv"),
                    "adeResources": t.get("adeResources"),
                    "adeProjectId": int(t.get("adeProjectId")) if t.get("adeProjectId") is not None else None,
                })

    return results


def build_ade_url(entry, date: datetime.date | None = None):
    """Construct the ADE/proxy URL according to adeProjectId rules.

    - adeProjectId == 2024 -> intervenant ICS via proxy (intervenant)
    - adeProjectId == 2023 -> etudiant ICS via proxy (etudiant)
    - otherwise -> anonymous_cal.jsp with params (resources, projectId, firstDate, lastDate)
    """
    # New behaviour: single request to edt.infuseting.fr/update with parameters.
    adeResources = entry.get("adeResources")
    adeProjectId = entry.get("adeProjectId")
    if adeProjectId is None or adeResources is None:
        return None
    d = date or datetime.date.today()
    params = {
        "adeBase": str(adeProjectId),
        "adeRessources": str(adeResources),
        "lastUpdate": "0",
        "date": d.strftime("%Y-%m-%d"),
    }
    print("https://edt.infuseting.fr/update/index.php" + "?" + urllib.parse.urlencode(params))
    return "https://edt.infuseting.fr/update/index.php" + "?" + urllib.parse.urlencode(params)


def fetch_url(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "MCPEdtUnicaen/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


def parse_ics_next_event(ics_text: str):
    """Very small ICS parser: extract VEVENT DTSTART/SUMMARY and return next event after now.

    Returns dict or None.
    """
    now = datetime.datetime.now()
    events = []
    parts = re.split(r"BEGIN:VEVENT\r?\n", ics_text)
    for part in parts[1:]:
        # limit to until END:VEVENT
        vevent = part.split("END:VEVENT")[0]
        m = re.search(r"DTSTART(?:;[^:]+)?:([0-9TZ+-]+)", vevent)
        if not m:
            continue
        dtstr = m.group(1).strip()
        # ignore all-day events (DATE only)
        if re.fullmatch(r"\d{8}", dtstr):
            continue
        # try parse
        dt = None
        try:
            if dtstr.endswith("Z"):
                dt = datetime.datetime.strptime(dtstr, "%Y%m%dT%H%M%SZ")
            else:
                # try with seconds
                try:
                    dt = datetime.datetime.strptime(dtstr, "%Y%m%dT%H%M%S")
                except Exception:
                    dt = datetime.datetime.strptime(dtstr, "%Y%m%dT%H%M")
        except Exception:
            # fallback: skip
            continue

        # summary
        s = ""
        m2 = re.search(r"SUMMARY:(.+)", vevent)
        if m2:
            s = m2.group(1).strip()

        events.append({"start": dt, "summary": s, "raw": vevent})

    # pick next
    future = [e for e in events if e["start"] and e["start"] > now]
    if not future:
        return None
    future.sort(key=lambda e: e["start"])
    nxt = future[0]
        return {"start": nxt["start"].isoformat(), "summary": nxt["summary"]}


def parse_ics_events(ics_text: str):
    """Parse ICS and return list of events with start, end, summary."""
    events = []
    parts = re.split(r"BEGIN:VEVENT\r?\n", ics_text)
    for part in parts[1:]:
        vevent = part.split("END:VEVENT")[0]
        m = re.search(r"DTSTART(?:;[^:]+)?:([0-9TZ+-]+)", vevent)
        if not m:
            continue
        dtstart = m.group(1).strip()
        # skip all-day
        if re.fullmatch(r"\d{8}", dtstart):
            continue
        dt1 = None
        try:
            if dtstart.endswith("Z"):
                dt1 = datetime.datetime.strptime(dtstart, "%Y%m%dT%H%M%SZ")
            else:
                try:
                    dt1 = datetime.datetime.strptime(dtstart, "%Y%m%dT%H%M%S")
                except Exception:
                    dt1 = datetime.datetime.strptime(dtstart, "%Y%m%dT%H%M")
        except Exception:
            continue

        # DTEND
        dt2 = None
        m2 = re.search(r"DTEND(?:;[^:]+)?:([0-9TZ+-]+)", vevent)
        if m2:
            dtend = m2.group(1).strip()
            try:
                if dtend.endswith("Z"):
                    dt2 = datetime.datetime.strptime(dtend, "%Y%m%dT%H%M%SZ")
                else:
                    try:
                        dt2 = datetime.datetime.strptime(dtend, "%Y%m%dT%H%M%S")
                    except Exception:
                        dt2 = datetime.datetime.strptime(dtend, "%Y%m%dT%H%M")
            except Exception:
                dt2 = None

        s = ""
        m3 = re.search(r"SUMMARY:(.+)", vevent)
        if m3:
            s = m3.group(1).strip()

        events.append({"start": dt1, "end": dt2, "summary": s, "raw": vevent})

    return events


def parse_update_json_and_next_event(json_text: str):
    """Parse JSON returned by https://edt.infuseting.fr/update and find next event.

    Expected structure: { "YYYY-MM-DD": { "content": [ { 'DTSTART': 'YYYYmmddTHHMMSS', 'SUMMARY': '...' }, ... ], 'lastUpdate': ... }, ... }
    Returns next event dict or None.
    """
    try:
        data = json.loads(json_text)
    except Exception:
        return None

    now = datetime.datetime.now()
    events = []
    for key, val in data.items():
        # skip non-dict
        if not isinstance(val, dict):
            continue
        content = val.get("content") or []
        if not isinstance(content, list):
            continue
        for ev in content:
            dtstr = ev.get("DTSTART") or ev.get("start") or None
            summary = ev.get("SUMMARY") or ev.get("summary") or ev.get("SUMMARY:CONFERENCE") or ""
            if not dtstr:
                continue
            # try parsing with common formats
            dt = None
            for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
                try:
                    dt = datetime.datetime.strptime(dtstr, fmt)
                    break
                except Exception:
                    continue
            if not dt:
                # try ISO parse fallback
                try:
                    dt = datetime.datetime.fromisoformat(dtstr)
                except Exception:
                    continue

            events.append({"start": dt, "summary": summary, "raw": ev})

    future = [e for e in events if e["start"] and e["start"] > now]
    if not future:
        return None
    future.sort(key=lambda e: e["start"])
    nxt = future[0]
    return {"start": nxt["start"].isoformat(), "summary": nxt["summary"]}


def parse_update_json_events(json_text: str, only_date: str | None = None):
    """Return list of events (with start, end, summary) from update endpoint JSON.

    If only_date is provided (YYYY-MM-DD), only events for that date are returned.
    """
    try:
        data = json.loads(json_text)
    except Exception:
        return []

    events = []
    for key, val in data.items():
        if only_date and key != only_date:
            continue
        if not isinstance(val, dict):
            continue
        content = val.get("content") or []
        if not isinstance(content, list):
            continue
        for ev in content:
            dtstr = ev.get("DTSTART") or ev.get("start") or None
            dtendstr = ev.get("DTEND") or ev.get("end") or None
            summary = ev.get("SUMMARY") or ev.get("summary") or ""
            if not dtstr:
                continue
            dt = None
            for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
                try:
                    dt = datetime.datetime.strptime(dtstr, fmt)
                    break
                except Exception:
                    continue
            if not dt:
                try:
                    dt = datetime.datetime.fromisoformat(dtstr)
                except Exception:
                    continue

            dtend = None
            if dtendstr:
                for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
                    try:
                        dtend = datetime.datetime.strptime(dtendstr, fmt)
                        break
                    except Exception:
                        continue
                if not dtend:
                    try:
                        dtend = datetime.datetime.fromisoformat(dtendstr)
                    except Exception:
                        dtend = None

            events.append({"start": dt, "end": dtend, "summary": summary, "raw": ev})

    return events