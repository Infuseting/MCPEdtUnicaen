from fastmcp import FastMCP, Context
import math
import json
import os
import urllib.request
import urllib.parse
import datetime
import re
import asyncio
from uuid import UUID
from typing import Optional
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse
from utils import *
from mcp.server.sse import SseServerTransport
from mcp.shared.message import ServerMessageMetadata, SessionMessage
import mcp.types as mcp_types

_MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
_MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
_MCP_MOUNT = os.getenv("MCP_MOUNT", "/mcp")
_MCP_SSE_PATH = os.getenv("MCP_SSE_PATH", "/sse")
_MCP_MESSAGE_PATH = os.getenv("MCP_MESSAGE_PATH", "/messages/")




mcp = FastMCP("EDT Unicaen MCP Server")

# Create SSE transport helper (used internally by FastMCP when serving SSE)
sse_transport = SseServerTransport(_MCP_MESSAGE_PATH)



_MY_EDT = os.getenv("MY_EDT", "").strip() or None

@mcp.tool(name="prochain_cours", title="Prochain cours", description="Donne le prochain cours et son heure à partir du nom d'un EDT (prof/salle/student/univ). Si aucun nom n'est fourni, utilise MY_EDT si configuré. L'IA doit fournir les dates au format ISO complet (ex: 2025-10-25T08:00:00 ou 2025-10-25T08:00).")
async def prochain_cours(nom: Optional[str] = None, ctx: Optional[Context] = None) -> dict:
    """MCP tool: retourne le prochain cours (heure + résumé) pour un nom d'EDT.

    - recherche case-insensitive dans les fichiers locaux
    - construit l'URL ADE selon adeProjectId
    - tente de récupérer et parser un ICS pour trouver le prochain événement
    """
    # If caller did not provide a name or used an alias for self, fall back to
    # (1) the HTTP header MY_EDT supplied by the client for this session (via ctx),
    # (2) then to the environment variable MY_EDT.
    if not nom or not str(nom).strip() or str(nom).strip().lower() in ("me", "moi", "self"):
        # Try extract from context headers (session-scoped)
        nom_from_ctx = None
        if ctx is not None:
            try:
                # attempt to get request object (may be sync or awaitable)
                print(ctx)
                req = getattr(ctx, "request", None)
                if req is None:
                    get_req = getattr(ctx, "get_http_request", None)
                    if callable(get_req):
                        maybe = get_req()
                        if hasattr(maybe, "__await__"):
                            req = await maybe
                        else:
                            req = maybe
                if req is not None:
                    headers = getattr(req, "headers", None)
                    if headers:
                        for k in ("MY_EDT", "My-Edt", "my_edt", "X-MY-EDT"):
                            v = headers.get(k)
                            if v:
                                nom_from_ctx = v
                                break
            except Exception:
                nom_from_ctx = None

        if nom_from_ctx:
            nom = nom_from_ctx
        else:
            env = os.getenv("MY_EDT", "").strip() or None
            if env:
                nom = env
            else:
                return {"ok": False, "error": "Aucun nom fourni et MY_EDT non configuré"}

    matches = find_entries_by_name(nom)
    if not matches:
        return {"ok": False, "error": "Aucune entrée trouvée pour ce nom"}

    # use first match for now
    entry = matches[0]
    # Build the single update URL to edt.infuseting.fr
    url = build_ade_url(entry)
    if url:
        try:
            content = fetch_url(url)
        except Exception as e:
            return {"ok": False, "error": f"Erreur lors de la récupération de l'URL: {e}", "url": url}

        # The update endpoint returns JSON (see the provided PHP). Try parsing JSON first.
        update_next = parse_update_json_and_next_event(content)
        # Build a richer event (try to extract location and professor) by parsing
        # the full events list and matching the next event.
        def extract_location_from_ev(ev):
            raw = ev.get("raw")
            if isinstance(raw, dict):
                return raw.get("LOCATION") or raw.get("location") or raw.get("room") or raw.get("Salle")
            if isinstance(raw, str):
                m = re.search(r"LOCATION:([^\r\n]+)", raw)
                if m:
                    return m.group(1).strip()
            return None

        def extract_prof_from_ev(ev):
            raw = ev.get("raw")
            if isinstance(raw, dict):
                for k in ("INTERVENANT", "PROF", "TEACHER", "ENSEIGNANT", "ORGANIZER", "AUTHOR"):
                    v = raw.get(k) or raw.get(k.lower())
                    if v:
                        return v
                # sometimes professor is inside summary
                s = raw.get("SUMMARY") or raw.get("summary") or ""
                if isinstance(s, str):
                    return s
            if isinstance(raw, str):
                # try ORGANIZER or SUMMARY contains professor
                m = re.search(r"ORGANIZER:[^\r\n]*CN=([^;\r\n]+)", raw)
                if m:
                    return m.group(1).strip()
                m2 = re.search(r"SUMMARY:([^\r\n]+)", raw)
                if m2:
                    # heuristic: split on '-' or '—' and return second part if looks like a name
                    s = m2.group(1).strip()
                    parts = re.split(r"[-—]", s)
                    if len(parts) > 1:
                        return parts[-1].strip()
                    return s
            return None

        if update_next:
            # try to find the matching event in parsed JSON events for richer info
            try:
                events = parse_update_json_events(content)
            except Exception:
                events = []
            rich = None
            if events:
                # convert update_next start to datetime for matching
                try:
                    upd_dt = datetime.datetime.fromisoformat(update_next.get("start"))
                except Exception:
                    upd_dt = None
                if upd_dt:
                    for ev in events:
                        if ev.get("start") and ev.get("start") == upd_dt:
                            rich = {
                                "start": ev["start"].isoformat(),
                                "summary": ev.get("summary"),
                                "location": extract_location_from_ev(ev),
                                "prof": extract_prof_from_ev(ev),
                            }
                            break
            if not rich:
                # fallback: return the simple update_next
                return {"ok": True, "source": url, "next": update_next}
            return {"ok": True, "source": url, "next": rich}

        # If no next event found in JSON, still try ICS parsing fallback in case the endpoint forwarded ICS
        ics_next = parse_ics_next_event(content)
        if ics_next:
            return {"ok": True, "source": url, "next": ics_next}

        # Fallback: return raw content snippet and the URL so the caller can inspect
        snippet = content[:2000]
        return {"ok": True, "source": url, "next": None, "raw_snippet": snippet}

    # If we couldn't build an update URL (missing adeProjectId/adeResources), fall back to searching the raw entry
    return {"ok": False, "error": "Impossible de construire l'URL de mise à jour (adeProjectId ou adeResources manquant)", "matches": matches}


@mcp.tool(name="disponibilite_salle", title="Disponibilité salle", description="Indique si une salle est disponible maintenant et jusqu\u2019\u00e0 quelle heure. Si une heure de debut et/ou de fin est fournie (ex: '08:00' ou ISO), limite la recherche à cette plage horaire. Les réponses incluent les dates/horaires au format ISO complet (ex: 2025-10-25T08:00:00).")
def disponibilite_salle(nom: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None, ctx: Optional[Context] = None) -> dict:
    """Retourne la disponibilité d'une salle (free/busy) et l'heure de fin si occupée.

    Logic:
    - cherche la salle dans `salle` (ou timetable/univ)
    - appelle l'endpoint de mise à jour pour la date d'aujourd'hui
    - récupère la liste d'events pour aujourd'hui
    - si un event englobe maintenant -> occupied until its DTEND (ou DTSTART if no DTEND)
    - else -> free until next event start (or None pour la fin de journée)

    Paramètres supplémentaires:
    - start: chaîne 'HH:MM' ou ISO datetime pour limiter la recherche
    - end: chaîne 'HH:MM' ou ISO datetime pour limiter la recherche
    """


    matches = find_entries_by_name(nom)
    if not matches:
        return {"ok": False, "error": "Aucune salle trouvée pour ce nom"}

    # prefer entries of type 'salle' or 'univ-timetable'
    entry = None
    for m in matches:
        if m.get("type") in ("salle", "univ-timetable"):
            entry = m
            break
    if not entry:
        entry = matches[0]

    url = build_ade_url(entry, date=datetime.date.today())
    if not url:
        return {"ok": False, "error": "Impossible de construire l'URL de mise à jour pour cette salle", "matches": matches}

    try:
        content = fetch_url(url)
    except Exception as e:
        return {"ok": False, "error": f"Erreur lors de la récupération de l'URL: {e}", "url": url}

    today = datetime.date.today().strftime("%Y-%m-%d")
    events = parse_update_json_events(content, only_date=today)
    # fallback to ICS parsing if nothing
    if not events:
        events = parse_ics_events(content)

    now = datetime.datetime.now()

    # parse optional limits
    start_dt = parse_limit_to_datetime(start)
    end_dt = parse_limit_to_datetime(end)

    # If both provided but invalid range
    if start_dt and end_dt and end_dt < start_dt:
        return {"ok": False, "error": "La limite de fin est antérieure à la limite de début"}

    # If a range was provided, filter events to those that intersect the window
    if start_dt or end_dt:
        filtered = []
        for ev in events:
            ev_start = ev.get("start")
            ev_end = ev.get("end") or ev_start
            if not ev_start or not ev_end:
                continue
            win_start = start_dt or datetime.datetime.min
            win_end = end_dt or datetime.datetime.max
            # intersect if event starts before window end and ends after window start
            if ev_start < win_end and ev_end > win_start:
                filtered.append(ev)
        events = filtered

    # Normalize: ensure end times exist; if missing, set end = start
    for ev in events:
        if not ev.get("end"):
            ev["end"] = ev.get("start")

    # events that are currently happening
    ongoing = [e for e in events if e["start"] and e["end"] and e["start"] <= now < e["end"]]
    if ongoing:
        ongoing.sort(key=lambda e: e["end"])
        e = ongoing[0]
        resp = {"ok": True, "available": False, "until": e["end"].isoformat(), "summary": e.get("summary"), "source": url}
        if start_dt:
            resp["range_start"] = start_dt.isoformat()
        if end_dt:
            resp["range_end"] = end_dt.isoformat()
        return resp

    # next upcoming
    future = [e for e in events if e["start"] and e["start"] > now]
    if future:
        future.sort(key=lambda e: e["start"])
        nxt = future[0]
        resp = {"ok": True, "available": True, "free_until": nxt["start"].isoformat(), "next_summary": nxt.get("summary"), "source": url}
        if start_dt:
            resp["range_start"] = start_dt.isoformat()
        if end_dt:
            resp["range_end"] = end_dt.isoformat()
        return resp

    # no more events today -> free all day
    resp = {"ok": True, "available": True, "free_until": None, "note": "Aucun cours r\u00e9pertori\u00e9 pour aujourd\u2019hui", "source": url}
    if start_dt:
        resp["range_start"] = start_dt.isoformat()
    if end_dt:
        resp["range_end"] = end_dt.isoformat()
    return resp


@mcp.tool(name="ou_est_prof", title="Où est le prof", description="Donne la localisation actuelle d'un enseignant (salle / en ligne) ou son prochain lieu. ")
async def ou_est_prof(nom: str = None) -> dict:
    """Retourne où se trouve (ou sera) un professeur.

    Comportement :
    - Recherche le professeur dans les assets (comme les autres tools)
    - Récupère l'update endpoint pour la date d'aujourd'hui
    - Parse les events (JSON fallback ICS)
    - Si un event englobe `now` -> retourne la salle/summary et la fin
    - Sinon -> retourne le prochain event avec heure et lieu
    """

    matches = find_entries_by_name(nom)
    if not matches:
        return {"ok": False, "error": "Aucune entrée trouvée pour ce nom"}

    # Prefer prof entries
    entry = None
    for m in matches:
        if m.get("type") == "prof":
            entry = m
            break
    if not entry:
        entry = matches[0]

    # Fetch today's events
    url = build_ade_url(entry, date=datetime.date.today())
    if not url:
        return {"ok": False, "error": "Impossible de construire l'URL de mise à jour (adeProjectId ou adeResources manquant)", "matches": matches}

    try:
        content = fetch_url(url)
    except Exception as e:
        return {"ok": False, "error": f"Erreur lors de la récupération de l'URL: {e}", "url": url}

    today = datetime.date.today().strftime("%Y-%m-%d")
    events = parse_update_json_events(content, only_date=today)
    if not events:
        events = parse_ics_events(content)

    now = datetime.datetime.now()

    # Normalize end times
    for ev in events:
        if not ev.get("end"):
            ev["end"] = ev.get("start")

    # helper to extract location from raw event
    def extract_location(ev):
        raw = ev.get("raw")
        # raw may be dict (JSON) or string (ICS)
        if isinstance(raw, dict):
            return raw.get("LOCATION") or raw.get("location") or raw.get("room") or None
        if isinstance(raw, str):
            m = re.search(r"LOCATION:([^\r\n]+)", raw)
            if m:
                return m.group(1).strip()
        return None

    # find ongoing events
    ongoing = [e for e in events if e.get("start") and e.get("end") and e["start"] <= now < e["end"]]
    if ongoing:
        ongoing.sort(key=lambda e: e["end"])
        e = ongoing[0]
        loc = extract_location(e) or e.get("summary")
        return {"ok": True, "name": nom, "status": "in_class", "until": e["end"].isoformat(), "location": loc, "summary": e.get("summary"), "source": url}

    # next upcoming
    future = [e for e in events if e.get("start") and e["start"] > now]
    if future:
        future.sort(key=lambda e: e["start"])
        nxt = future[0]
        loc = extract_location(nxt) or nxt.get("summary")
        return {"ok": True, "name": nom, "status": "free_now", "next_start": nxt["start"].isoformat(), "next_location": loc, "next_summary": nxt.get("summary"), "source": url}

    return {"ok": True, "name": nom, "status": "free_all_day", "note": "Aucun cours répertorié pour aujourd'hui", "source": url}

# small health endpoint to validate the HTTP/SSE server is reachable
@mcp.custom_route(path="/health", methods=["GET"])
async def _health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "server": mcp.name, "mount": _MCP_MOUNT, "sse_path": _MCP_SSE_PATH})


# Root route: return 200 to satisfy probes from connectors (some clients/bridges
# probe `/` and treat a 404 as an error). See FastMCP/OpenAI connector notes.
@mcp.custom_route(path="/", methods=["GET"])
async def _root(request):
    # Return plain text/HTML to avoid confusing probes that expect non-JSON content
    from starlette.responses import PlainTextResponse

    txt = f"{mcp.name} — SSE endpoint available at { _MCP_SSE_PATH } (MCP mount: { _MCP_MOUNT })"
    return PlainTextResponse(txt)

# execute and return the stdio output
if __name__ == "__main__":
    print("Starting MCP server (SSE transport)...")
    # Run the FastMCP server using the SSE transport so clients can connect via HTTP/SSE
    # The `FastMCP` instance was configured with `sse_path` and `message_path` above.
    mcp.run(transport="sse", host=_MCP_HOST, port=_MCP_PORT)
    print("MCP server stopped.")

