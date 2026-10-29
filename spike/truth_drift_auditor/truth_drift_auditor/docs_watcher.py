"""Google Docs watcher: poll ``documents.get``, diff paragraphs, feed the
auditor, post findings back as Drive comments.

Facts this design rests on (docs/01_RESEARCH_2026-10-29.md §1):
- The Claude Google Drive connector reads on demand; it cannot watch a doc.
- Drive push notifications carry no content and have no latency target, and
  Docs revisions may be merged — so we poll.
- The Docs API read quota is 300 requests/min/user, so a 3-5 s interval is safe.
- Comments: Drive v3 ``comments.create`` works unanchored; ``quotedFileContent``
  shows the quoted text in the comment card. Anchoring to a range in a Google
  Doc uses an undocumented anchor format and is NOT attempted here.
- The Docs API cannot create Suggesting-mode edits.

Dependencies (not installed in the thin-client venv):
    pip install google-api-python-client google-auth-oauthlib
OAuth: an installed-app ``credentials.json`` from Google Cloud; ``token.json``
is written next to it on first run. Scopes: documents.readonly + drive (for
comments).
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable

from .models import Paragraph, ParagraphReport

SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive",
]


def _creds(credentials_json: str | Path, token_json: str | Path):
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
    token_json = Path(token_json)
    creds = Credentials.from_authorized_user_file(str(token_json), SCOPES) if token_json.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_json), SCOPES)
            creds = flow.run_local_server(port=0)
        token_json.write_text(creds.to_json(), encoding="utf-8")
    return creds


def paragraphs_from_document(doc: dict) -> list[Paragraph]:
    """Flatten a Docs API document body into Paragraph objects with the API's
    startIndex/endIndex (tabs-aware when present)."""
    bodies = []
    if doc.get("tabs"):
        for tab in doc["tabs"]:
            bodies.append(tab.get("documentTab", {}).get("body", {}))
    else:
        bodies.append(doc.get("body", {}))
    out: list[Paragraph] = []
    i = 0
    for body in bodies:
        for el in body.get("content", []):
            p = el.get("paragraph")
            if not p:
                continue
            text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])).strip()
            if len(text) < 20:
                continue
            out.append(Paragraph(index=i, text=text, start=el.get("startIndex", 0),
                                 end=el.get("endIndex", 0),
                                 sha1=hashlib.sha1(text.encode("utf-8")).hexdigest()))
            i += 1
    return out


class DocsWatcher:
    def __init__(self, document_id: str, credentials_json: str | Path, token_json: str | Path,
                 interval_s: float = 4.0, post_comments: bool = False):
        from googleapiclient.discovery import build  # type: ignore
        creds = _creds(credentials_json, token_json)
        self.docs = build("docs", "v1", credentials=creds, cache_discovery=False)
        self.drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.document_id = document_id
        self.interval_s = max(2.0, interval_s)     # 300 reads/min/user quota; stay far below
        self.post_comments = post_comments
        self.seen: dict[str, str] = {}             # paragraph sha1 -> comment id (or "")

    def fetch(self) -> list[Paragraph]:
        doc = self.docs.documents().get(documentId=self.document_id, includeTabsContent=True).execute()
        return paragraphs_from_document(doc)

    def changed(self, paras: list[Paragraph]) -> list[Paragraph]:
        return [p for p in paras if p.sha1 not in self.seen]

    def comment(self, report: ParagraphReport) -> str:
        lines = []
        for f in report.numeric:
            if not f.ok:
                lines.append(f"Number drift: you wrote {f.quote}; measured value is {f.expected}{f.unit} ({f.path}).")
        for c in report.claims:
            if c.verdict == "CONTRADICTED":
                lines.append(f"Contradicted: \"{c.quote}\" — {c.note} [evidence: {', '.join(c.evidence_ids)}]")
        if report.tier2:
            lines.append("Reviewer note: " + report.tier2)
        if not lines:
            return ""
        body = {"content": "\n".join(lines),
                "quotedFileContent": {"mimeType": "text/plain", "value": report.paragraph.text[:200]}}
        res = self.drive.comments().create(fileId=self.document_id, body=body, fields="id").execute()
        return res.get("id", "")

    def run(self, audit: Callable[[Paragraph], ParagraphReport], on_report: Callable[[ParagraphReport], None] | None = None,
            max_iterations: int | None = None) -> None:
        n = 0
        while max_iterations is None or n < max_iterations:
            n += 1
            try:
                paras = self.fetch()
            except Exception as e:
                print(f"[watcher] fetch failed: {e}")
                time.sleep(self.interval_s)
                continue
            for p in self.changed(paras):
                rep = audit(p)
                cid = ""
                if self.post_comments and rep.drifted:
                    try:
                        cid = self.comment(rep)
                    except Exception as e:
                        rep.errors.append(f"comment: {e}")
                self.seen[p.sha1] = cid
                if on_report:
                    on_report(rep)
            time.sleep(self.interval_s)
