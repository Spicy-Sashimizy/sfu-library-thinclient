"""Evidence from the SFU library thin client: ``POST /api/search``.

The thin client is a separate project (this spike is moving out of its tree).
Interface contract as read from ``source/sfu_library_mcp_http.py`` on
2026-10-29 — see docs/03_THIN_CLIENT_INTERFACE.md:

    POST {base}/api/search   body {"query": str, "limit": int<=50,
                                   "year_from"?: int, "year_to"?: int,
                                   "open_access_only"?: bool, "type"?: str}
    -> {"results": [<work dict>...], "meta": {"count": N}, "notes": [str...]}
    GET  {base}/api/index_status -> {"metrics": {"coverage_end": "YYYY-MM-DD", ...}, ...}

Only the standard library is used (urllib) so this module has no dependencies.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..models import Evidence


class ThinClientRetriever:
    name = "thinclient"

    def __init__(self, base_url: str = "http://localhost:8788", timeout: float = 30.0,
                 year_from: int | None = None, year_to: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.year_from = year_from
        self.year_to = year_to

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base_url + path, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def health(self) -> dict:
        return self._get("/health")

    def coverage_end(self) -> str | None:
        """Last publication date the LOCAL index covers (served by
        GET /api/index_status, not /health)."""
        try:
            data = self._get("/api/index_status")
        except (urllib.error.URLError, json.JSONDecodeError):
            return None
        return (data.get("metrics") or {}).get("coverage_end")

    def retrieve(self, query: str, k: int = 5) -> list[Evidence]:
        body: dict = {"query": query, "limit": max(1, min(k, 50))}
        if self.year_from:
            body["year_from"] = self.year_from
        if self.year_to:
            body["year_to"] = self.year_to
        data = self._post("/api/search", body)
        out: list[Evidence] = []
        for w in data.get("results") or []:
            wid = w.get("openalex_id") or w.get("doi") or w.get("id") or ""
            title = w.get("title") or w.get("display_name") or ""
            abstract = w.get("abstract") or ""
            year = w.get("publication_year") or w.get("year") or ""
            out.append(Evidence(
                id=str(wid), text=f"{title} ({year}). {abstract}".strip(), source=self.name,
                score=float(w.get("score") or 0.0),
                meta={"doi": w.get("doi"), "year": year, "notes": data.get("notes") or []},
            ))
        return out
