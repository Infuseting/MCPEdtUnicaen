from mcp.server.fastmcp import FastMCP
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

# Optional fallback: name to use when no EDT name is provided to tools.
# Expected format: "FIRSTNAME LASTNAME" (set via environment variable MY_EDT)
_MY_EDT = os.getenv("MY_EDT", "").strip() or None



mcp = FastMCP(
    "EDT Unicaen MCP Server",
    host=_MCP_HOST,
    port=_MCP_PORT,
    mount_path=_MCP_MOUNT,
    sse_path=_MCP_SSE_PATH,
    message_path=_MCP_MESSAGE_PATH,
    streamable_http_path=_MCP_MOUNT,
)

sse_transport = SseServerTransport(_MCP_MESSAGE_PATH)



@mcp.tool(name="prochain_cours", title="Prochain cours", description="Donne le prochain cours et son heure à partir du nom d'un EDT (prof/salle/student/univ). Si aucun nom n'est fourni, utilise MY_EDT si configuré. L'IA doit fournir les dates au format ISO complet (ex: 2025-10-25T08:00:00 ou 2025-10-25T08:00).")
def prochain_cours(nom: Optional[str] = None) -> dict:
    """MCP tool: retourne le prochain cours (heure + résumé) pour un nom d'EDT.

    - recherche case-insensitive dans les fichiers locaux
    - construit l'URL ADE selon adeProjectId
    - tente de récupérer et parser un ICS pour trouver le prochain événement
    """
    # If caller did not provide a name or used an alias for self, fall back to MY_EDT
    if not nom or not str(nom).strip() or str(nom).strip().lower() in ("me", "moi", "self"):
        if _MY_EDT:
            nom = _MY_EDT
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
        if update_next:
            return {"ok": True, "source": url, "next": update_next}

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
def disponibilite_salle(nom: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None) -> dict:
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


# small health endpoint to validate the HTTP/SSE server is reachable
@mcp.custom_route(path="/health", methods=["GET"])
async def _health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "server": mcp.name, "mount": _MCP_MOUNT, "sse_path": _MCP_SSE_PATH})

# execute and return the stdio output
if __name__ == "__main__":
    print("Starting MCP server...")
    mcp.run("stdio")
    print("MCP server stopped.")

