"""Glue between The Poneglyph System and the ``drawing_search`` package.

Corporate-search credentials are supplied out of band (they are user- and
site-specific and must not live in the repo). Resolution order:

  1. JSON file at  ~/.poneglyph_drawing_search.json  (or $PONEGLYPH_DWG_CONFIG)
       {
         "base_url":      "https://drawings.example.com",
         "search_path":   "/search/searchGT.html",   (optional)
         "download_url":  "https://drawings.example.com",  (optional)
         "cookies":       { "filenet-es": "...", "_WL_AUTHCOOKIE_filenet-es": "..." }
       }
  2. Environment variables, filling any gaps left by the file:
       PONEGLYPH_DWG_BASE_URL
       PONEGLYPH_DWG_SEARCH_PATH
       PONEGLYPH_DWG_DOWNLOAD_URL
       PONEGLYPH_DWG_COOKIES   -> raw "k=v; k2=v2" cookie header string

When nothing is configured, ``is_configured()`` is False and the API surfaces
that so the UI can fall back to manual drawing entry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

try:
    from drawing_search import (
        DrawingSearchClient,
        SearchParams,
        DrawingSearchCache,
        DRAWING_TYPES,
        DRAWING_SUBJECTS,
        FACILITIES,
    )
    from drawing_search.form_fetcher import fetch_form_options
    from drawing_search.lookup_tables import save_cached_options, load_cached_options

    _HAVE_PKG = True
except Exception:  # pragma: no cover - package missing / broken
    _HAVE_PKG = False


_CONFIG_PATH = os.environ.get(
    "PONEGLYPH_DWG_CONFIG",
    os.path.join(os.path.expanduser("~"), ".poneglyph_drawing_search.json"),
)

# Default drawing type / subject guesses per device type. These are only
# *pre-selections* in the search form — the user can override every field.
# type "E" = Electrical; subjects: 06 P&C, 07 Metering, 10 AC Power, 20 Grounding.
DEVICE_TYPE_HINTS: dict[str, dict[str, str]] = {
    "Relay":                    {"drawing_type": "E", "drawing_subject": "06"},
    "CTTB":                     {"drawing_type": "E", "drawing_subject": "06"},
    "FTBlock":                  {"drawing_type": "E", "drawing_subject": "06"},
    "IsoBlock":                 {"drawing_type": "E", "drawing_subject": "06"},
    "CurrentTransformer":       {"drawing_type": "E", "drawing_subject": "06"},
    "VoltageTransformer":       {"drawing_type": "E", "drawing_subject": "06"},
    "DualWindingVT":            {"drawing_type": "E", "drawing_subject": "06"},
    "CircuitBreaker":           {"drawing_type": "E", "drawing_subject": "06"},
    "Disconnect":               {"drawing_type": "E", "drawing_subject": "06"},
    "VoltageRegulator":         {"drawing_type": "E", "drawing_subject": "06"},
    "PowerTransformer":         {"drawing_type": "E", "drawing_subject": "06"},
    "AuxiliaryTransformer":     {"drawing_type": "E", "drawing_subject": "06"},
    "Meter":                    {"drawing_type": "E", "drawing_subject": "07"},
    "VoltageSource":            {"drawing_type": "E", "drawing_subject": "10"},
    "Bus":                      {"drawing_type": "E", "drawing_subject": "10"},
    "Line":                     {"drawing_type": "E", "drawing_subject": "10"},
    "PowerLine":                {"drawing_type": "E", "drawing_subject": "10"},
    "Wire":                     {"drawing_type": "E", "drawing_subject": "10"},
    "ShuntCapacitor":           {"drawing_type": "E", "drawing_subject": "10"},
    "ShuntReactor":             {"drawing_type": "E", "drawing_subject": "10"},
    "SurgeArrester":            {"drawing_type": "E", "drawing_subject": "10"},
    "SVC":                      {"drawing_type": "E", "drawing_subject": "10"},
    "SeriesCapacitor":          {"drawing_type": "E", "drawing_subject": "10"},
    "SeriesReactor":            {"drawing_type": "E", "drawing_subject": "10"},
    "LineTrap":                 {"drawing_type": "E", "drawing_subject": "10"},
    "NeutralGroundingResistor": {"drawing_type": "E", "drawing_subject": "20"},
}


def _load_file_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_cookie_header(raw: str) -> dict:
    out: dict[str, str] = {}
    for pair in (raw or "").split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _resolve_config() -> dict:
    """Merge file config (primary) with env vars (fallback)."""
    fc = _load_file_config()
    cfg = {
        "base_url": fc.get("base_url") or os.environ.get("PONEGLYPH_DWG_BASE_URL", ""),
        "search_path": fc.get("search_path") or os.environ.get("PONEGLYPH_DWG_SEARCH_PATH") or None,
        "download_url": fc.get("download_url") or os.environ.get("PONEGLYPH_DWG_DOWNLOAD_URL") or None,
        "cookies": {},
    }
    try:
        cfg["cache_refresh_hours"] = float(
            fc.get("cache_refresh_hours")
            or os.environ.get("PONEGLYPH_DWG_CACHE_HOURS")
            or 4
        )
    except (TypeError, ValueError):
        cfg["cache_refresh_hours"] = 4.0
    cookies = fc.get("cookies")
    if isinstance(cookies, dict) and cookies:
        cfg["cookies"] = {str(k): str(v) for k, v in cookies.items()}
    else:
        cfg["cookies"] = _parse_cookie_header(os.environ.get("PONEGLYPH_DWG_COOKIES", ""))
    return cfg


def save_config(patch: dict) -> dict:
    """Merge *patch* into the JSON config file and return the public view.

    Accepts base_url, download_url, search_path, cache_refresh_hours, cookies.
    Empty strings clear a field; missing keys are left untouched.
    """
    cur = _load_file_config()
    for key in ("base_url", "download_url", "search_path"):
        if key in patch:
            v = (patch[key] or "").strip()
            if v:
                cur[key] = v
            else:
                cur.pop(key, None)
    if "cache_refresh_hours" in patch:
        try:
            cur["cache_refresh_hours"] = max(0.0, float(patch["cache_refresh_hours"]))
        except (TypeError, ValueError):
            pass
    if isinstance(patch.get("cookies"), dict):
        cur["cookies"] = {str(k): str(v) for k, v in patch["cookies"].items() if k}
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=2)
    except OSError as exc:
        return {"ok": False, "error": f"could not write {_CONFIG_PATH}: {exc}"}
    return {"ok": True, **get_public_config()}


def get_public_config() -> dict:
    """Config for the settings UI — never returns cookie values."""
    cfg = _resolve_config()
    return {
        "configured": bool(cfg["base_url"]),
        "base_url": cfg["base_url"],
        "download_url": cfg["download_url"] or "",
        "search_path": cfg["search_path"] or "",
        "cache_refresh_hours": cfg["cache_refresh_hours"],
        "cookie_names": sorted(cfg["cookies"].keys()),
        "config_path": _CONFIG_PATH,
        "platform": sys.platform,
    }


# ── Windows Integrated Auth cookie grab ────────────────────────────────────

def _ps_grab_windows_cookies(url: str) -> dict:
    """Fetch cookies via Windows Integrated Authentication (NTLM/Kerberos).

    Uses PowerShell Invoke-WebRequest with -UseDefaultCredentials so the current
    Windows domain account is used automatically — no password prompt required.
    Returns {name: value}. Raises RuntimeError on failure.
    """
    if sys.platform != "win32":
        raise RuntimeError("Windows authentication cookie grab requires Windows.")
    url_esc = url.replace("'", "''")
    ps = (
        f"$url = '{url_esc}'; "
        "$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession; "
        "$status = 0; "
        "try { "
        "  $r = Invoke-WebRequest -Uri $url -UseDefaultCredentials -UseBasicParsing -WebSession $session; "
        "  $status = $r.StatusCode "
        "} catch [System.Net.WebException] { "
        "  if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode } "
        "} catch { $status = -1 }; "
        "$obj = [PSCustomObject]@{ status = $status; cookies = $session.Cookies.GetCookies($url) }; "
        "Write-Host '__PGS_JSON_START__'; "
        "$obj | ConvertTo-Json -Depth 5 | Write-Host; "
        "Write-Host '__PGS_JSON_END__'"
    ).replace("\n", "")
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "BYPASS", "-Command", ps],
            capture_output=True, text=True, timeout=30, creationflags=flags,
        )
    except FileNotFoundError:
        raise RuntimeError("PowerShell not found.")
    if r.returncode != 0 and "__PGS_JSON_START__" not in r.stdout:
        raise RuntimeError(f"PowerShell error:\n{(r.stderr or r.stdout).strip()}")
    stdout = r.stdout
    start = stdout.find("__PGS_JSON_START__")
    end = stdout.find("__PGS_JSON_END__")
    if start == -1 or end == -1:
        raise RuntimeError(f"Could not locate JSON output.\n\nOutput: {stdout[:300]}")
    json_text = stdout[start + len("__PGS_JSON_START__"):end].strip()
    try:
        data = {k: v.replace("\r", "") if isinstance(v, str) else v
                for k, v in json.loads(json_text).items()}
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError(f"Could not parse PowerShell output:\n{exc}\n\n{json_text[:300]}") from exc
    raw = data.get("cookies") or []
    if isinstance(raw, dict):
        raw = [raw]
    result = {}
    for cookie in (raw if isinstance(raw, list) else []):
        name = cookie.get("Name") or cookie.get("name", "")
        value = cookie.get("Value") if "Value" in cookie else cookie.get("value", "")
        if name:
            result[name] = (value or "").replace("\r", "")
    return result


def grab_windows_cookies() -> dict:
    """Grab session cookies for the configured base URL via Windows auth and
    persist them to the config file."""
    cfg = _resolve_config()
    if not cfg["base_url"]:
        return {"ok": False, "error": "Set the Drawing Search URL first."}
    try:
        cookies = _ps_grab_windows_cookies(cfg["base_url"])
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    if not cookies:
        return {"ok": False, "error": "No cookies returned — not authenticated, or the URL is wrong."}
    save_config({"cookies": cookies})
    global _options_cache
    _options_cache = None  # force option re-fetch with the fresh session
    return {"ok": True, "cookie_names": sorted(cookies)}


def is_configured() -> bool:
    if not _HAVE_PKG:
        return False
    cfg = _resolve_config()
    return bool(cfg["base_url"])


def _client():
    cfg = _resolve_config()
    if not cfg["base_url"]:
        raise RuntimeError("drawing search is not configured")
    return DrawingSearchClient(
        base_url=cfg["base_url"],
        cookies=cfg["cookies"] or None,
        cache=DrawingSearchCache(),
        search_path=cfg["search_path"],
        download_url=cfg["download_url"],
    )


# ── Options (facility / type / subject dropdowns) ───────────────────────────

_options_cache: dict | None = None


def get_options(refresh: bool = False) -> dict:
    """Return {facilities, drawing_types, drawing_subjects} code->label maps.

    Tries a live fetch once (persisted by the package's own JSON cache), then
    falls back to whatever the package currently has loaded.
    """
    global _options_cache
    if _options_cache is not None and not refresh:
        return _options_cache

    if _HAVE_PKG and refresh:
        cfg = _resolve_config()
        if cfg["base_url"]:
            try:
                opts = fetch_form_options(base_url=cfg["base_url"], cookies=cfg["cookies"] or None)
                if opts and any(opts.values()):
                    save_cached_options(opts)
                    _options_cache = {
                        "facilities": opts.get("facilities", {}),
                        "drawing_types": opts.get("drawing_types", {}),
                        "drawing_subjects": opts.get("drawing_subjects", {}),
                    }
                    return _options_cache
            except Exception:
                pass

    _options_cache = {
        "facilities": dict(FACILITIES) if _HAVE_PKG else {},
        "drawing_types": dict(DRAWING_TYPES) if _HAVE_PKG else {},
        "drawing_subjects": dict(DRAWING_SUBJECTS) if _HAVE_PKG else {},
    }
    return _options_cache


# ── Search ────────────────────────────────────────────────────────────────

_ALLOWED_PARAMS = {
    "state", "facility", "drawing_type", "drawing_subject", "sheet_number",
    "serial_from", "serial_to", "drawing_num_op", "drawing_num",
    "title_op", "title", "title2_op", "title2",
    "manufacturer_name", "manufacturer_doc_num", "remarks_contain",
    "legacy_document_num", "page", "page_size",
}


def search(params: dict) -> dict:
    """Run a drawing search. Returns a JSON-serialisable dict."""
    if not is_configured():
        return {"configured": False, "results": [], "error": "not configured"}

    kw = {k: v for k, v in (params or {}).items() if k in _ALLOWED_PARAMS and v not in (None, "")}
    kw.setdefault("state", "Released")
    try:
        kw["page"] = int(kw.get("page", 0))
    except (TypeError, ValueError):
        kw["page"] = 0
    try:
        kw["page_size"] = min(200, int(kw.get("page_size", 50)))
    except (TypeError, ValueError):
        kw["page_size"] = 50

    try:
        client = _client()
        ttl = _resolve_config()["cache_refresh_hours"] * 3600.0
        try:
            if client.cache is not None and ttl > 0:
                client.cache.clear_expired(ttl)
        except Exception:
            pass
        paged = client.search_paged(SearchParams(**kw))
    except Exception as exc:
        return {"configured": True, "results": [], "error": str(exc)}

    results = [
        {
            "document_id": r.document_id,
            "drawing_number": r.drawing_number,
            "title": r.title,
            "facility": r.facility,
            "drawing_type": r.drawing_type,
            "drawing_subject": r.drawing_subject,
            "revision": r.revision,
            "paper_size": r.paper_size,
            "state": r.state,
            "document_url": r.document_url,
            "legacy_doc_number": r.legacy_doc_number,
        }
        for r in paged.results
    ]
    return {
        "configured": True,
        "results": results,
        "page": paged.page,
        "page_size": paged.page_size,
        "total_count": paged.total_count,
        "has_next": paged.has_next,
    }


def list_revisions(drawing_number: str) -> dict:
    """Enumerate every revision the corporate system holds for one drawing
    number. Used to bind a "sibling revisions" list to an attached drawing."""
    drawing_number = (drawing_number or "").strip()
    if not drawing_number:
        return {"configured": is_configured(), "revisions": [], "error": "no drawing number"}
    if not is_configured():
        return {"configured": False, "revisions": []}
    try:
        client = _client()
        paged = client.search_all_pages(
            SearchParams(
                state="",                       # any state — we want superseded revs too
                drawing_num=drawing_number,
                drawing_num_op="starts with",
                page_size=200,
            ),
            max_pages=10,
        )
    except Exception as exc:
        return {"configured": True, "revisions": [], "error": str(exc)}

    seen, revs = set(), []
    for r in paged:
        if (r.drawing_number or "").strip().upper() != drawing_number.upper():
            continue
        key = (r.revision or "", r.state or "")
        if key in seen:
            continue
        seen.add(key)
        revs.append({
            "revision": r.revision,
            "state": r.state,
            "title": r.title,
            "document_url": r.document_url,
            "document_id": r.document_id,
            "drawing_subject": r.drawing_subject,
            "paper_size": r.paper_size,
        })
    return {"configured": True, "drawing_number": drawing_number, "revisions": revs}
