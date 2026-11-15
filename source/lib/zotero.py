"""Zotero API wrapper for saving and browsing library items.

Provides ZoteroClient that maps normalized work metadata to Zotero items, manages
collections, detects duplicates via multi-signal deconfliction, and
wraps all API calls with a circuit breaker.
"""

import logging
import os
import re
import threading
import time

import requests

from lib.config import ServerConfig
from lib.retry import CircuitBreaker

logger = logging.getLogger("sfu_library_mcp")

RECORD_ID_TAG = "Duck-Library-RecordID"


_item_types_cache: list[str] | None = None
_item_types_cache_ts: float = 0.0
_ITEM_TYPES_TTL = 86400
_item_types_lock = threading.Lock()


def fetch_zotero_item_types() -> list[str]:
    """Return all valid Zotero item type names from the public API (no auth needed).

    Results are cached for 24 hours. Falls back to the previous cache on
    network error; returns an empty list if the API has never been reached.
    """
    global _item_types_cache, _item_types_cache_ts
    with _item_types_lock:
        now = time.time()
        if _item_types_cache is not None and now - _item_types_cache_ts < _ITEM_TYPES_TTL:
            return _item_types_cache
        try:
            resp = requests.get("https://api.zotero.org/itemTypes", timeout=10)
            resp.raise_for_status()
            _item_types_cache = [entry["itemType"] for entry in resp.json()]
            _item_types_cache_ts = now
            logger.info("Fetched %d Zotero item types from API", len(_item_types_cache))
        except Exception as e:
            logger.warning("Could not fetch Zotero item types: %s", e)
            if _item_types_cache is None:
                _item_types_cache = []
        return _item_types_cache


PDF_MAX_BYTES = 100 * 1024 * 1024


def download_pdf(url: str, dest_path: str, max_bytes: int = PDF_MAX_BYTES) -> int:
    """Stream a PDF from an http(s) URL to `dest_path`. Returns the byte count.

    arXiv `/abs/` links are rewritten to `/pdf/`. Raises ZoteroError when the
    URL is not http(s), the download fails or exceeds `max_bytes`, or the body
    is not a PDF; the partial file is removed in every failure case.
    """
    if not re.match(r"^https?://", url or "", re.I):
        raise ZoteroError("pdf_url must be an http(s) URL")
    url = re.sub(r"(arxiv\.org)/abs/", r"\1/pdf/", url, flags=re.I)
    written = 0
    try:
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "DuckLibrary/1.0"}) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    written += len(chunk)
                    if written > max_bytes:
                        raise ZoteroError(f"PDF exceeds {max_bytes // (1024 * 1024)} MB limit")
                    f.write(chunk)
        if not is_pdf_file(dest_path):
            raise ZoteroError("Downloaded file is not a PDF (no %PDF header)")
        return written
    except ZoteroError:
        _remove_quietly(dest_path)
        raise
    except Exception as e:
        _remove_quietly(dest_path)
        raise ZoteroError(f"PDF download failed: {e}") from e


def is_pdf_file(path: str) -> bool:
    """True when the file starts with the %PDF magic bytes."""
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


_item_type_fields_cache: dict[str, tuple[float, frozenset[str]]] = {}
_ITEM_BASE_KEYS = frozenset({"itemType", "creators", "tags", "collections", "relations"})


def fetch_zotero_item_type_fields(item_type: str) -> frozenset[str] | None:
    """Return the field names Zotero accepts for `item_type` (public API, no auth).

    Cached per type for 24 hours. Falls back to the previous cache entry on
    network error; returns None if this type's fields have never been fetched.
    """
    with _item_types_lock:
        now = time.time()
        cached = _item_type_fields_cache.get(item_type)
        if cached and now - cached[0] < _ITEM_TYPES_TTL:
            return cached[1]
        try:
            resp = requests.get(
                "https://api.zotero.org/itemTypeFields",
                params={"itemType": item_type},
                timeout=10,
            )
            resp.raise_for_status()
            fields = frozenset(entry["field"] for entry in resp.json())
            _item_type_fields_cache[item_type] = (now, fields)
            return fields
        except Exception as e:
            logger.warning("Could not fetch Zotero fields for %s: %s", item_type, e)
            return cached[1] if cached else None


def drop_invalid_fields(item: dict) -> dict:
    """Remove fields Zotero rejects for the item's type.

    Uses the live per-type field list; when it is unavailable, drops only
    empty-valued fields so blank defaults (ISSN, volume, ...) never reach the API.
    """
    allowed = fetch_zotero_item_type_fields(item.get("itemType", ""))
    dropped = []
    for key in list(item):
        if key in _ITEM_BASE_KEYS:
            continue
        if (allowed is not None and key not in allowed) or (allowed is None and item[key] in ("", None)):
            if item[key] not in ("", None):
                dropped.append(key)
            del item[key]
    if dropped:
        logger.info("Dropped fields invalid for %s: %s", item.get("itemType"), ", ".join(dropped))
    return item


class ZoteroError(Exception):
    """Raised when a Zotero API operation fails."""
    pass


class ZoteroClient:
    """Zotero API client with circuit breaker and collection management."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self._zot = None
        self._breaker = CircuitBreaker(
            threshold=config.circuit_breaker_threshold,
            timeout=config.circuit_breaker_timeout,
        )
        self._authenticated = False
        self._auth_info = {}

    @property
    def zot(self):
        """Lazy-load pyzotero on first use."""
        if self._zot is None:
            if not self.config.zotero_api_key or not self.config.zotero_user_id:
                raise ZoteroError(
                    "Zotero credentials not configured. Set SFU_ZOTERO_API_KEY "
                    "and SFU_ZOTERO_USER_ID environment variables."
                )
            from pyzotero import zotero
            self._zot = zotero.Zotero(
                self.config.zotero_user_id,
                "user",
                self.config.zotero_api_key,
            )
        return self._zot

    def _call_zotero(self, operation_name: str, func, *args, **kwargs):
        """Wrapper for all Zotero API calls with circuit breaker + logging."""
        if not self._breaker.can_proceed():
            raise ZoteroError(
                f"Zotero API circuit breaker is OPEN — too many recent failures. "
                f"Will retry automatically after {self.config.circuit_breaker_timeout}s."
            )
        try:
            result = func(*args, **kwargs)
            self._breaker.record_success()
            logger.info("Zotero API: %s succeeded", operation_name)
            return result
        except ZoteroError:
            self._breaker.record_failure()
            raise
        except Exception as e:
            self._breaker.record_failure()
            logger.error(
                "Zotero API: %s failed (%s), failure_count=%d",
                operation_name, e, self._breaker.failure_count,
            )
            raise ZoteroError(f"Zotero API error in {operation_name}: {e}") from e


    def verify_credentials(self) -> dict:
        """Verify Zotero API credentials by calling key_info().

        Returns:
            dict with "valid" bool and credential details on success,
            or "valid": False with "message" on failure.
        """
        if not self.config.zotero_api_key or not self.config.zotero_user_id:
            return {
                "valid": False,
                "message": "Zotero credentials not configured. "
                           "Set SFU_ZOTERO_API_KEY and SFU_ZOTERO_USER_ID.",
            }
        try:
            info = self._call_zotero("key_info", self.zot.key_info)
        except ZoteroError as e:
            self._authenticated = False
            self._auth_info = {}
            return {"valid": False, "message": str(e)}

        access = info.get("access", {})
        user_access = access.get("user", {})
        username = info.get("username", "")
        user_id = info.get("userID", self.config.zotero_user_id)

        self._authenticated = True
        self._auth_info = {
            "username": username,
            "userID": user_id,
            "access": {
                "library": user_access.get("library", False),
                "files": user_access.get("files", False),
                "notes": user_access.get("notes", False),
                "write": user_access.get("write", False),
            },
        }
        logger.info("Zotero credentials verified for user: %s (ID: %s)", username, user_id)
        return {
            "valid": True,
            "username": username,
            "userID": user_id,
            "access": self._auth_info["access"],
        }

    def ensure_authenticated(self, force: bool = False) -> bool:
        """Ensure Zotero credentials are valid (lazy, cached).

        Args:
            force: If True, re-verify even if already authenticated.

        Returns:
            True if credentials are valid, False otherwise.
        """
        if force:
            self._authenticated = False
            self._auth_info = {}

        if self._authenticated:
            return True

        if not self.config.zotero_api_key or not self.config.zotero_user_id:
            return False

        result = self.verify_credentials()
        return result["valid"]


    @staticmethod
    def _parse_author_name(author_str: str) -> dict:
        """Parse an author string into Zotero creator dict.

        Handles:
        - "Last, First" format
        - "First Last" format
        - Single name (e.g. "Aristotle")
        """
        if not author_str:
            return {"creatorType": "author", "lastName": "", "firstName": ""}

        if "," in author_str:
            parts = author_str.split(",", 1)
            return {
                "creatorType": "author",
                "lastName": parts[0].strip(),
                "firstName": parts[1].strip(),
            }
        else:
            parts = author_str.strip().split()
            if len(parts) == 1:
                return {
                    "creatorType": "author",
                    "lastName": parts[0],
                    "firstName": "",
                }
            return {
                "creatorType": "author",
                "lastName": parts[-1],
                "firstName": " ".join(parts[:-1]),
            }


    def metadata_to_zotero_item(self, metadata: dict) -> dict:
        """Map a normalized work dict (`openalex.normalize_work` shape) to a Zotero item template."""
        resource_type = metadata.get("resource_type", "other")
        type_map = {
            "article": "journalArticle",
            "magazine_article": "magazineArticle",
            "newspaper_article": "newspaperArticle",
            "book": "book",
            "book_section": "bookSection",
            "conference_paper": "conferencePaper",
            "thesis": "thesis",
            "webpage": "webpage",
            "software": "computerProgram",
            "report": "report",
            "dataset": "dataset",
            "film": "film",
            "video": "videoRecording",
            "audio": "audioRecording",
            "patent": "patent",
            "presentation": "presentation",
            "preprint": "preprint",
            "dissertation": "thesis",
            "other": "document",
        }
        item_type = metadata.get("zotero_item_type") or type_map.get(resource_type, "document")

        authors = metadata.get("authors") or metadata.get("creators", [])
        creators = [self._parse_author_name(a) for a in authors]

        editors = metadata.get("editors", [])
        for ed in editors:
            parsed = self._parse_author_name(ed)
            parsed["creatorType"] = "editor"
            creators.append(parsed)

        item = {
            "itemType": item_type,
            "title": metadata.get("title", ""),
            "creators": creators,
            "date": metadata.get("date", ""),
            "DOI": metadata.get("doi", ""),
            "ISBN": metadata.get("isbn", ""),
            "ISSN": metadata.get("issn", ""),
            "volume": metadata.get("volume", ""),
            "issue": metadata.get("issue", ""),
            "extra": "",
        }

        spage = metadata.get("spage", "")
        epage = metadata.get("epage", "")
        pages = metadata.get("pages", "")
        if pages:
            item["pages"] = pages
        elif spage and epage:
            item["pages"] = f"{spage}-{epage}"
        elif spage:
            item["pages"] = spage

        if item_type == "journalArticle":
            item["publicationTitle"] = metadata.get("source", "")
        elif item_type in ("magazineArticle", "newspaperArticle"):
            item["publicationTitle"] = metadata.get("source", "")
        elif item_type == "book":
            item["publisher"] = metadata.get("publisher", "")
            if metadata.get("edition"):
                item["edition"] = metadata["edition"]
        elif item_type == "bookSection":
            item["publicationTitle"] = metadata.get("book_title", "")
            item["publisher"] = metadata.get("publisher", "")
        elif item_type == "conferencePaper":
            item["conferenceName"] = metadata.get("conference_name", "") or metadata.get("source", "")
            item["place"] = metadata.get("conference_location", "")
        elif item_type == "thesis":
            item["university"] = metadata.get("institution", "")
            degree = (metadata.get("degree_type", "") or "").lower()
            item["thesisType"] = (
                "Master's Thesis" if degree in ("masters", "master's", "master")
                else "Doctoral Dissertation"
            )
        elif item_type == "webpage":
            item["websiteTitle"] = metadata.get("source", "")
            if metadata.get("url"):
                item["url"] = metadata["url"]
            if metadata.get("accessed_date"):
                item["accessDate"] = metadata["accessed_date"]
        elif item_type == "computerProgram":
            item["publisher"] = metadata.get("publisher", "")
            if metadata.get("version"):
                item["versionNumber"] = metadata["version"]
            if metadata.get("url"):
                item["url"] = metadata["url"]
        elif item_type == "report":
            item["institution"] = metadata.get("publisher", "")
            if metadata.get("report_number"):
                item["reportNumber"] = metadata["report_number"]
            if metadata.get("url"):
                item["url"] = metadata["url"]
        elif item_type == "dataset":
            item["repository"] = metadata.get("publisher", "")
            if metadata.get("url"):
                item["url"] = metadata["url"]
        elif item_type == "preprint":
            item["repository"] = metadata.get("source", "") or metadata.get("publisher", "")
            if metadata.get("url"):
                item["url"] = metadata["url"]
        else:
            item["publicationTitle"] = metadata.get("source", "")
            item["publisher"] = metadata.get("publisher", "")
            if metadata.get("url"):
                item["url"] = metadata["url"]

        record_id = metadata.get("record_id", "")
        if record_id:
            item["extra"] = f"{RECORD_ID_TAG}: {record_id}"

        return drop_invalid_fields(item)


    def create_item(self, zotero_item: dict, collection_key: str | None = None) -> str:
        """Create a Zotero item, optionally in a collection. Returns item key."""
        if collection_key:
            zotero_item["collections"] = [collection_key]

        resp = self._call_zotero(
            "create_item",
            self.zot.create_items,
            [zotero_item],
        )

        if not resp or "successful" not in resp:
            raise ZoteroError(f"Unexpected response from create_items: {resp}")

        successful = resp.get("successful", {})
        if not successful:
            failed = resp.get("failed", {})
            raise ZoteroError(f"Failed to create Zotero item: {failed}")

        item_key = successful["0"]["key"]
        logger.info("Created Zotero item: %s (%s)", item_key, zotero_item.get("title", "")[:60])
        return item_key


    def list_collections(self) -> list[dict]:
        """List all Zotero collections."""
        collections = self._call_zotero(
            "list_collections",
            self.zot.collections,
        )
        result = []
        for c in collections:
            data = c.get("data", {})
            meta = c.get("meta", {})
            result.append({
                "key": data.get("key", ""),
                "name": data.get("name", ""),
                "parent_key": data.get("parentCollection", ""),
                "num_items": meta.get("numItems", 0),
            })
        return result

    def find_collection_by_name(self, name: str, parent_key: str | None = None) -> str | None:
        """Find a collection by name (case-insensitive), optionally under a parent.

        Args:
            name: Collection name to find.
            parent_key: If specified, only match collections with this parentCollection.

        Returns:
            Collection key or None.
        """
        collections = self.list_collections()
        name_lower = name.lower()
        for c in collections:
            if c["name"].lower() == name_lower:
                if parent_key is not None:
                    if c.get("parent_key", "") == parent_key:
                        return c["key"]
                else:
                    return c["key"]
        return None

    def create_collection(self, name: str, parent_key: str | None = None) -> str:
        """Create a new collection, optionally as a subcollection. Returns its key."""
        payload = {"name": name}
        if parent_key:
            payload["parentCollection"] = parent_key

        resp = self._call_zotero(
            "create_collection",
            self.zot.create_collections,
            [payload],
        )

        if not resp or "successful" not in resp:
            raise ZoteroError(f"Unexpected response from create_collections: {resp}")

        successful = resp.get("successful", {})
        if not successful:
            failed = resp.get("failed", {})
            raise ZoteroError(f"Failed to create collection: {failed}")

        key = successful["0"]["key"]
        parent_info = f" (parent: {parent_key})" if parent_key else ""
        logger.info("Created Zotero collection: %s (%s)%s", key, name, parent_info)
        return key

    def find_or_create_collection(self, name: str, parent_key: str | None = None) -> str:
        """Find a collection by name, or create it. Returns key.

        Args:
            name: Collection name.
            parent_key: If specified, find/create under this parent collection.
        """
        key = self.find_collection_by_name(name, parent_key=parent_key)
        if key:
            logger.info("Found existing collection '%s' -> %s", name, key)
            return key
        logger.info("Collection '%s' not found, creating...", name)
        return self.create_collection(name, parent_key=parent_key)


    def _format_item(self, item: dict) -> dict:
        """Format a raw pyzotero item dict into a clean dict."""
        data = item.get("data", {})
        creators = data.get("creators", [])
        author_names = []
        for c in creators:
            last = c.get("lastName", "")
            first = c.get("firstName", "")
            if last and first:
                author_names.append(f"{last}, {first}")
            elif last:
                author_names.append(last)
            elif c.get("name"):
                author_names.append(c["name"])

        collections = data.get("collections", [])
        tags = [t.get("tag", "") for t in data.get("tags", [])]

        return {
            "key": data.get("key", ""),
            "title": data.get("title", ""),
            "authors": author_names,
            "date": data.get("date", ""),
            "item_type": data.get("itemType", ""),
            "DOI": data.get("DOI", ""),
            "ISBN": data.get("ISBN", ""),
            "publication": data.get("publicationTitle", "") or data.get("publisher", ""),
            "collections": collections,
            "tags": tags,
        }

    def format_item_summary(self, item: dict) -> str:
        """Format a Zotero item dict into a human-readable string."""
        parts = []
        title = item.get("title", "Untitled")
        parts.append(f"Title: {title}")

        authors = item.get("authors", [])
        if authors:
            parts.append(f"Authors: {'; '.join(authors)}")

        date = item.get("date", "")
        if date:
            parts.append(f"Date: {date}")

        item_type = item.get("item_type", "")
        if item_type:
            parts.append(f"Type: {item_type}")

        pub = item.get("publication", "")
        if pub:
            parts.append(f"Publication: {pub}")

        doi = item.get("DOI", "")
        if doi:
            parts.append(f"DOI: {doi}")

        isbn = item.get("ISBN", "")
        if isbn:
            parts.append(f"ISBN: {isbn}")

        tags = item.get("tags", [])
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")

        collections = item.get("collections", [])
        if collections:
            parts.append(f"Collections: {', '.join(collections)}")

        key = item.get("key", "")
        if key:
            parts.append(f"Zotero Key: {key}")

        return "\n".join(parts)

    def get_item(self, item_key: str) -> dict | None:
        """Return the raw item for `item_key`, or None if the library has no such item."""
        try:
            return self._call_zotero("get_item", self.zot.item, item_key)
        except ZoteroError as e:
            if type(e.__cause__).__name__ == "ResourceNotFoundError" or "404" in str(e):
                return None
            raise

    def get_pdf_attachments(self, item_key: str) -> list[dict]:
        """Return the PDF attachment children of `item_key` (raw data dicts)."""
        children = self._call_zotero("get_children", self.zot.children, item_key)
        return [
            c.get("data", {}) for c in children
            if c.get("data", {}).get("itemType") == "attachment"
            and c.get("data", {}).get("contentType") == "application/pdf"
        ]

    def attach_file(self, item_key: str, file_path: str) -> dict:
        """Upload `file_path` as a stored-file attachment under `item_key`.

        Returns pyzotero's attachment_simple result ({"success", "failure",
        "unchanged"}); raises ZoteroError when the upload did not succeed.
        """
        resp = self._call_zotero("attach_file", self.zot.attachment_simple, [file_path], item_key)
        if not resp or (not resp.get("success") and not resp.get("unchanged")):
            raise ZoteroError(f"Attachment upload failed: {resp}")
        logger.info("Attached %s to Zotero item %s", os.path.basename(file_path), item_key)
        return resp

    CITATION_EXPORT_FORMATS = ("bib", "citation", "bibtex", "biblatex", "ris", "csljson")

    @staticmethod
    def _csl_html_to_text(fragment) -> str:
        """Strip a CSL HTML fragment (bytes or str) to one line of readable text."""
        import html as html_lib
        if isinstance(fragment, bytes):
            fragment = fragment.decode("utf-8", errors="replace")
        text = re.sub(r"</?(?:div|br|p)\b[^>]*>", " ", str(fragment or ""), flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        return " ".join(html_lib.unescape(text).split())

    @classmethod
    def _csl_bibliography_entries(cls, bibliography) -> list[str]:
        """Split a format=bib XHTML bibliography into plain-text entries, in style order."""
        if isinstance(bibliography, (list, tuple)):
            return [t for t in (cls._csl_html_to_text(b) for b in bibliography) if t]
        if isinstance(bibliography, bytes):
            bibliography = bibliography.decode("utf-8", errors="replace")
        chunks = re.split(r"<div\b[^>]*class=\"[^\"]*\bcsl-entry\b[^\"]*\"[^>]*>", str(bibliography or ""))
        if len(chunks) == 1:
            whole = cls._csl_html_to_text(chunks[0])
            return [whole] if whole else []
        return [t for t in (cls._csl_html_to_text(c) for c in chunks[1:]) if t]

    @staticmethod
    def _export_entries_to_text(entries) -> list[str]:
        """Normalise per-item export payloads (str/bytes/bibtexparser db) to text blocks."""
        if entries is None:
            return []
        if hasattr(entries, "entries") and not isinstance(entries, (list, tuple, str, bytes)):
            import bibtexparser
            text = bibtexparser.dumps(entries).strip()
            return [text] if text else []
        if isinstance(entries, (str, bytes)):
            entries = [entries]
        out = []
        for e in entries:
            if isinstance(e, bytes):
                e = e.decode("utf-8", errors="replace")
            text = str(e or "").strip()
            if text:
                out.append(text)
        return out

    @staticmethod
    def _csljson_items(entries) -> list[dict]:
        """Flatten csljson payloads: a list of CSL items, or {"items": [...]} wrappers."""
        if isinstance(entries, dict):
            entries = entries.get("items", [entries])
        out = []
        for e in entries or []:
            if isinstance(e, dict) and isinstance(e.get("items"), list):
                out.extend(x for x in e["items"] if isinstance(x, dict))
            elif isinstance(e, dict):
                out.append(e)
        return out

    def export_citations(
        self,
        item_keys: list[str] | None = None,
        collection_key: str | None = None,
        fmt: str = "bib",
        style: str = "apa",
        locale: str = "en-US",
        limit: int = 50,
    ) -> list:
        """Have Zotero format references from the library (read-only).

        Exactly one of `item_keys` (<= 50, the Web API itemKey cap) or
        `collection_key` must be given. `fmt`:
          - "bib": format=bib, one XHTML bibliography sorted and numbered by
            the CSL style; returned as a list of plain-text entries. The API
            ignores `limit` for format=bib (cap 150), so collection results are
            truncated to `limit` client-side.
          - "citation": Atom content=citation, one in-text citation per item,
            stripped to plain text.
          - "bibtex" / "biblatex" / "ris": Atom content=<fmt>, one raw text
            block per item.
          - "csljson": Atom content=csljson, a list of CSL-JSON item dicts.
        `style`/`locale` only apply to bib and citation.
        """
        if fmt not in self.CITATION_EXPORT_FORMATS:
            raise ZoteroError(f"Unsupported citation format: {fmt}")
        if bool(item_keys) == bool(collection_key):
            raise ZoteroError("Provide exactly one of item_keys or collection_key.")
        if item_keys and len(item_keys) > 50:
            raise ZoteroError("At most 50 item keys per request (Zotero itemKey limit).")
        limit = max(1, min(int(limit), 100))

        if item_keys:
            func, args = self.zot.items, ()
            params = {"itemKey": ",".join(item_keys)}
            request_limit = len(item_keys)
        else:
            func, args = self.zot.collection_items, (collection_key,)
            params = {"itemType": "-attachment || note"}
            request_limit = limit

        if fmt == "bib":
            raw = self._call_zotero(
                "export_bibliography", func, *args, format="bib", style=style, locale=locale, **params,
            )
            entries = self._csl_bibliography_entries(raw)
            return entries if item_keys else entries[:limit]

        if fmt == "citation":
            raw = self._call_zotero(
                "export_citations", func, *args,
                content="citation", style=style, locale=locale, limit=request_limit, **params,
            )
            return [t for t in (self._csl_html_to_text(c) for c in (raw or [])) if t]

        processors = getattr(self.zot, "processors", None)
        if isinstance(processors, dict) and fmt not in processors and "bibtex" in processors:
            processors[fmt] = processors["bibtex"]
        raw = self._call_zotero(
            f"export_{fmt}", func, *args, content=fmt, limit=request_limit, **params,
        )
        if fmt == "csljson":
            return self._csljson_items(raw)
        return self._export_entries_to_text(raw)

    def list_children(self, item_key: str, item_type: str | None = None, cap: int = 1000) -> list[dict]:
        """Return the raw data dicts of `item_key`'s children, paged 100 at a time.

        Filters to `item_type` client-side when given and stops after `cap` children.
        """
        out: list[dict] = []
        start = 0
        while start < cap:
            page = self._call_zotero(
                "get_children", self.zot.children, item_key, limit=100, start=start,
            ) or []
            for child in page:
                data = child.get("data", {})
                if item_type is None or data.get("itemType") == item_type:
                    out.append(data)
            if len(page) < 100:
                break
            start += 100
        return out

    def resolve_reading_attachments(self, item_key: str) -> tuple[dict, list[dict]] | None:
        """Resolve `item_key` to (item data, file attachments to read).

        A parent item yields its file attachments (linked URLs excluded); an
        attachment key yields itself. Returns None when the item does not exist.
        """
        item = self.get_item(item_key)
        if not item:
            return None
        data = item.get("data", {})
        if data.get("itemType") == "attachment":
            return data, [data]
        attachments = [
            c for c in self.list_children(item_key, "attachment")
            if c.get("linkMode") != "linked_url"
        ]
        return data, attachments

    def get_annotations(self, attachment_key: str, cap: int = 1000) -> list[dict]:
        """Return annotation items under `attachment_key`, in reading order (annotationSortIndex)."""
        annotations = self.list_children(attachment_key, "annotation", cap=cap)
        return sorted(annotations, key=lambda a: a.get("annotationSortIndex") or "")

    def get_child_notes(self, item_key: str) -> list[dict]:
        """Return the note items directly under `item_key` (raw data dicts)."""
        return self.list_children(item_key, "note")

    def get_fulltext(self, attachment_key: str) -> dict | None:
        """Return the full-text payload for an attachment, or None when nothing is indexed.

        The payload has `content` plus either indexedPages/totalPages (PDF) or
        indexedChars/totalChars (text documents). The API answers 404 when the
        attachment has no synced full-text index.
        """
        try:
            result = self._call_zotero("get_fulltext", self.zot.fulltext_item, attachment_key)
        except ZoteroError as e:
            if type(e.__cause__).__name__ == "ResourceNotFoundError" or "404" in str(e):
                return None
            raise
        if not isinstance(result, dict) or not result.get("content"):
            return None
        return result

    @staticmethod
    def note_html_to_text(html_text: str) -> str:
        """Convert a Zotero note's HTML body to readable plain text (paragraphs, lists, line breaks)."""
        from html.parser import HTMLParser

        block_tags = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "tr", "ul", "ol", "table"}

        class _NoteText(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.parts: list[str] = []
                self.skip = 0

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self.skip += 1
                elif tag == "br":
                    self.parts.append("\n")
                elif tag == "li":
                    self.parts.append("\n- ")
                elif tag in block_tags:
                    self.parts.append("\n\n")
                elif tag in ("td", "th"):
                    self.parts.append(" | ")

            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self.skip = max(0, self.skip - 1)
                elif tag in block_tags:
                    self.parts.append("\n\n")

            def handle_data(self, data):
                if not self.skip:
                    self.parts.append(re.sub(r"\s+", " ", data))

        parser = _NoteText()
        parser.feed(html_text or "")
        parser.close()
        text = "".join(parser.parts)
        text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    _NON_EDITABLE_TYPES = ("attachment", "note", "annotation")
    _DATA_META_KEYS = frozenset({
        "key", "version", "dateAdded", "dateModified", "parentItem", "deleted", "inPublications",
    })

    @staticmethod
    def _inline_markdown(text: str) -> str:
        """Escape one line of user text and render `code`, **bold**, *italic*, [text](http-url)."""
        import html as html_mod

        out = []
        for part in re.split(r"(`[^`]+`)", text):
            if len(part) > 1 and part.startswith("`") and part.endswith("`"):
                out.append(f"<code>{html_mod.escape(part[1:-1], quote=True)}</code>")
                continue
            s = html_mod.escape(part, quote=True)
            s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', s)
            s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
            s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
            out.append(s)
        return "".join(out)

    @classmethod
    def note_to_html(cls, text: str) -> str:
        """Convert plain text / simple Markdown to the HTML Zotero stores in a note.

        All user text is HTML-escaped; only headings (#), bullet and numbered
        lists, paragraphs, line breaks, `code`, **bold**, *italic* and
        http(s) links are rendered as markup.
        """
        blocks: list[str] = []
        para: list[str] = []
        items: list[str] = []
        list_tag = ""

        def flush_para():
            if para:
                blocks.append("<p>" + "<br>".join(para) + "</p>")
                para.clear()

        def flush_list():
            nonlocal list_tag
            if items:
                blocks.append(f"<{list_tag}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{list_tag}>")
                items.clear()
            list_tag = ""

        for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw.rstrip()
            heading = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
            bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
            numbered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
            if not line.strip():
                flush_para()
                flush_list()
            elif heading:
                flush_para()
                flush_list()
                level = len(heading.group(1))
                blocks.append(f"<h{level}>{cls._inline_markdown(heading.group(2).strip())}</h{level}>")
            elif bullet or numbered:
                flush_para()
                tag = "ul" if bullet else "ol"
                if list_tag and list_tag != tag:
                    flush_list()
                list_tag = tag
                items.append(cls._inline_markdown((bullet or numbered).group(1).strip()))
            else:
                flush_list()
                para.append(cls._inline_markdown(line.strip()))
        flush_para()
        flush_list()
        return "".join(blocks)

    @staticmethod
    def _creator_label(creator: dict) -> str:
        last = creator.get("lastName", "")
        first = creator.get("firstName", "")
        if last and first:
            return f"{last}, {first}"
        return last or first or creator.get("name", "")

    @staticmethod
    def is_version_conflict(error: Exception) -> bool:
        """True when `error` wraps a Zotero 412 Precondition Failed (version mismatch)."""
        cause = error.__cause__
        if cause is not None and type(cause).__name__ == "PreConditionFailedError":
            return True
        return "changed in Zotero since it was read" in str(error) or "Code: 412" in str(error)

    def _patch_item(self, operation_name: str, payload: dict) -> None:
        """PATCH `payload` (must carry key + version) via pyzotero update_item.

        pyzotero sends If-Unmodified-Since-Version from payload["version"]; an
        HTTP 412 is re-raised as a ZoteroError saying the item changed since read.
        """
        try:
            self._call_zotero(operation_name, self.zot.update_item, payload)
        except ZoteroError as e:
            if self.is_version_conflict(e):
                raise ZoteroError(
                    f"Item {payload.get('key')} changed in Zotero since it was read "
                    f"(version {payload.get('version')}); nothing was written. Retry to apply "
                    f"the change to the current version."
                ) from e
            raise

    def _get_editable_item(self, item_key: str) -> dict:
        item = self.get_item(item_key)
        if not item:
            raise ValueError(f"No Zotero item with key '{item_key}'.")
        item_type = item.get("data", {}).get("itemType", "")
        if item_type in self._NON_EDITABLE_TYPES:
            raise ValueError(f"Item '{item_key}' is a {item_type}, not a regular item.")
        return item

    def add_note(self, parent_key: str, note_html: str, tags: list[str] | None = None) -> str:
        """Create a child note under `parent_key`. Returns the new note's key."""
        parent = self._get_editable_item(parent_key)
        note = {
            "itemType": "note",
            "note": note_html,
            "parentItem": parent.get("data", {}).get("key") or parent_key,
            "tags": [{"tag": t} for t in (tags or [])],
            "collections": [],
            "relations": {},
        }
        return self.create_item(note)

    def update_item_fields(
        self,
        item_key: str,
        fields: dict[str, str],
        creators: list[str] | None = None,
        item_type: str | None = None,
    ) -> dict:
        """Edit an item's fields/creators/type with a version-checked PATCH.

        Field names are validated against the target type's live field list;
        unknown names raise ValueError and nothing is written. On a type change,
        existing fields the new type lacks are left out of the PATCH and
        reported as dropped.

        Returns {"key", "title", "item_type", "changes": [(field, before, after)],
        "dropped": [(field, old_value)], "written": bool}.
        """
        item = self._get_editable_item(item_key)
        data = item.get("data", {})
        current_type = data.get("itemType", "")
        target_type = (item_type or "").strip() or current_type
        if target_type in self._NON_EDITABLE_TYPES:
            raise ValueError(f"Cannot change an item into a {target_type}.")

        allowed = fetch_zotero_item_type_fields(target_type)
        if allowed is None:
            known = fetch_zotero_item_types()
            if known and target_type not in known:
                raise ValueError(
                    f"Unknown Zotero item type '{target_type}'. Valid types: {', '.join(sorted(known))}."
                )
            raise ZoteroError(f"Could not load the Zotero field list for '{target_type}'; nothing was written.")

        invalid = sorted(k for k in fields if k not in allowed)
        if invalid:
            raise ValueError(
                f"Field(s) not valid for item type '{target_type}': {', '.join(invalid)}. "
                f"Nothing was written. Valid fields: {', '.join(sorted(allowed))}."
            )
        non_string = sorted(
            k for k, v in fields.items() if isinstance(v, bool) or not isinstance(v, (str, int, float))
        )
        if non_string:
            raise ValueError(f"Field values must be strings: {', '.join(non_string)}.")

        payload: dict = {"key": data.get("key") or item_key, "version": item.get("version", data.get("version"))}
        changes: list[tuple[str, str, str]] = []
        dropped: list[tuple[str, str]] = []

        if target_type != current_type:
            payload["itemType"] = target_type
            changes.append(("itemType", current_type, target_type))
            for k, v in data.items():
                if k in _ITEM_BASE_KEYS or k in self._DATA_META_KEYS or k in allowed:
                    continue
                if v not in ("", None):
                    dropped.append((k, str(v)))

        for k, v in fields.items():
            new_value = str(v)
            before = str(data.get(k, "") or "")
            if before != new_value:
                payload[k] = new_value
                changes.append((k, before, new_value))

        if creators is not None:
            new_creators = [self._parse_author_name(a.strip()) for a in creators if a and a.strip()]
            before_labels = [self._creator_label(c) for c in data.get("creators", [])]
            after_labels = [self._creator_label(c) for c in new_creators]
            if before_labels != after_labels:
                payload["creators"] = new_creators
                changes.append(("creators", "; ".join(before_labels), "; ".join(after_labels)))

        result = {
            "key": payload["key"],
            "title": str(fields.get("title") or data.get("title", "")),
            "item_type": target_type,
            "changes": changes,
            "dropped": dropped,
            "written": False,
        }
        if changes:
            self._patch_item("update_item", payload)
            result["written"] = True
            logger.info("Updated Zotero item %s: %s", payload["key"], ", ".join(c[0] for c in changes))
        return result

    def modify_item_collections(self, item_keys: list[str], collection_key: str, action: str) -> list[dict]:
        """Add (`action="add"`) or remove (`"remove"`) items to/from a collection.

        One version-checked PATCH per item (pyzotero addto_collection /
        deletefrom_collection). Returns per-item dicts {"key", "title",
        "status", "detail"}; status is one of added, removed, unchanged,
        not_found, skipped, conflict, error.
        """
        if action not in ("add", "remove"):
            raise ValueError(f"Unknown action '{action}'; use 'add' or 'remove'.")
        func = self.zot.addto_collection if action == "add" else self.zot.deletefrom_collection
        results = []
        for key in item_keys:
            row = {"key": key, "title": "", "status": "", "detail": ""}
            results.append(row)
            try:
                item = self.get_item(key)
            except ZoteroError as e:
                row.update(status="error", detail=str(e))
                continue
            if not item:
                row["status"] = "not_found"
                continue
            data = item.setdefault("data", {})
            row["title"] = data.get("title", "")
            if data.get("parentItem") or data.get("itemType") == "annotation":
                row.update(status="skipped", detail="child items cannot be placed in collections")
                continue
            data.setdefault("collections", [])
            item.setdefault("key", data.get("key", key))
            item.setdefault("version", data.get("version"))
            present = collection_key in data["collections"]
            if (action == "add") == present:
                row.update(status="unchanged", detail="already in collection" if present else "not in collection")
                continue
            try:
                self._call_zotero(f"{action}_collection", func, collection_key, item)
                row["status"] = "added" if action == "add" else "removed"
            except ZoteroError as e:
                if self.is_version_conflict(e):
                    row.update(status="conflict", detail="changed since read; retry")
                else:
                    row.update(status="error", detail=str(e))
        return results

    def modify_item_tags(self, item_keys: list[str], add: list[str], remove: list[str]) -> list[dict]:
        """Add/remove tags on each item with a version-checked read-modify-write.

        Tag matching is exact (Zotero tags are case-sensitive). Returns per-item
        dicts {"key", "title", "status", "added", "removed", "detail"}; status
        is one of updated, unchanged, not_found, conflict, error.
        """
        remove_set = set(remove)
        results = []
        for key in item_keys:
            row = {"key": key, "title": "", "status": "", "added": [], "removed": [], "detail": ""}
            results.append(row)
            try:
                item = self.get_item(key)
            except ZoteroError as e:
                row.update(status="error", detail=str(e))
                continue
            if not item:
                row["status"] = "not_found"
                continue
            data = item.get("data", {})
            row["title"] = data.get("title", "") or data.get("itemType", "")
            existing = data.get("tags", []) or []
            kept = [t for t in existing if t.get("tag") not in remove_set]
            row["removed"] = [t.get("tag") for t in existing if t.get("tag") in remove_set]
            names = {t.get("tag") for t in kept}
            for tag in add:
                if tag not in names:
                    kept.append({"tag": tag})
                    names.add(tag)
                    row["added"].append(tag)
            if not row["added"] and not row["removed"]:
                row["status"] = "unchanged"
                continue
            payload = {
                "key": data.get("key") or key,
                "version": item.get("version", data.get("version")),
                "tags": kept,
            }
            try:
                self._patch_item("update_tags", payload)
                row["status"] = "updated"
            except ZoteroError as e:
                status = "conflict" if self.is_version_conflict(e) else "error"
                detail = "changed since read; retry" if status == "conflict" else str(e)
                row.update(status=status, added=[], removed=[], detail=detail)
        return results

    TRASH_BATCH_MAX = 50
    UNFILED_SCAN_PAGE = 100
    UNFILED_SCAN_CAP = 1000

    def _format_cleanup_item(self, item: dict) -> dict:
        """_format_item plus the trash-relevant fields (deleted flag, parent, children, dates)."""
        data = item.get("data", {})
        out = self._format_item(item)
        out.update({
            "deleted": bool(data.get("deleted")),
            "parent_item": data.get("parentItem", "") or "",
            "num_children": int(item.get("meta", {}).get("numChildren", 0) or 0),
            "date_added": data.get("dateAdded", ""),
            "date_modified": data.get("dateModified", ""),
            "version": data.get("version", item.get("version")),
        })
        return out

    def _set_deleted_flag(self, item_keys: list[str], deleted: bool) -> dict:
        """Flip the Web API `deleted` property on up to TRASH_BATCH_MAX items.

        Uses POST /items with {key, version, deleted} objects (PATCH semantics,
        per-object version check) through pyzotero's create_items, because
        pyzotero's update_item/update_items run check_items, which rejects the
        `deleted` key. Returns {"changed", "skipped", "not_found", "failed"}:
        lists of _format_cleanup_item dicts ("failed" entries carry "error"),
        "not_found" a list of keys. "skipped" holds items already in the wanted
        state (already trashed when trashing, not in the trash when restoring).
        """
        keys = list(dict.fromkeys(k.strip().upper() for k in item_keys if k and k.strip()))
        if len(keys) > self.TRASH_BATCH_MAX:
            raise ZoteroError(f"At most {self.TRASH_BATCH_MAX} item keys per call (got {len(keys)}).")
        result = {"changed": [], "skipped": [], "not_found": [], "failed": []}
        to_change = []
        for key in keys:
            raw = self.get_item(key)
            if not raw:
                result["not_found"].append(key)
                continue
            info = self._format_cleanup_item(raw)
            if info["deleted"] == deleted:
                result["skipped"].append(info)
            else:
                to_change.append(info)
        if not to_change:
            return result
        payload = [
            {"key": info["key"], "version": info["version"], "deleted": 1 if deleted else 0}
            for info in to_change
        ]
        op = "trash_items" if deleted else "restore_items"
        resp = self._call_zotero(op, self.zot.create_items, payload) or {}
        failed = resp.get("failed", {}) or {}
        for idx, info in enumerate(to_change):
            err = failed.get(str(idx)) or failed.get(idx)
            if err:
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                code = err.get("code", "") if isinstance(err, dict) else ""
                result["failed"].append({**info, "error": f"{code} {msg}".strip()})
            else:
                result["changed"].append({**info, "deleted": deleted})
        logger.info(
            "Zotero %s: %d changed, %d skipped, %d not found, %d failed", op,
            len(result["changed"]), len(result["skipped"]), len(result["not_found"]), len(result["failed"]),
        )
        return result

    def trash_items(self, item_keys: list[str]) -> dict:
        """Move items to the Zotero trash (recoverable; sets `deleted: 1`). See _set_deleted_flag."""
        return self._set_deleted_flag(item_keys, True)

    def restore_items(self, item_keys: list[str]) -> dict:
        """Take items out of the Zotero trash (sets `deleted: 0`). See _set_deleted_flag."""
        return self._set_deleted_flag(item_keys, False)

    def list_trash(self, limit: int = 50) -> list[dict]:
        """Items in the trash (GET /items/trash), most recently modified first."""
        items = self._call_zotero(
            "list_trash", self.zot.trash,
            limit=limit, sort="dateModified", direction="desc",
        )
        return [self._format_cleanup_item(item) for item in items]

    def list_unfiled_items(
        self, limit: int = 50, include_trashed: bool = False, scan_cap: int | None = None,
    ) -> dict:
        """Top-level items that belong to no collection.

        The Web API has no unfiled filter, so this pages GET /items/top
        (newest dateAdded first, UNFILED_SCAN_PAGE per request) and keeps items
        whose `collections` is empty, stopping at `limit` matches or after
        `scan_cap` scanned items. Returns {"items", "scanned", "cap_hit"}.
        /items/top excludes trashed items unless include_trashed.
        """
        cap = scan_cap or self.UNFILED_SCAN_CAP
        found: list[dict] = []
        scanned = 0
        cap_hit = False
        while len(found) < limit:
            if scanned >= cap:
                cap_hit = True
                break
            page_size = min(self.UNFILED_SCAN_PAGE, cap - scanned)
            params = {"limit": page_size, "start": scanned, "sort": "dateAdded", "direction": "desc"}
            if include_trashed:
                params["includeTrashed"] = 1
            page = self._call_zotero("list_unfiled_items", self.zot.top, **params) or []
            scanned += len(page)
            for item in page:
                if not item.get("data", {}).get("collections"):
                    found.append(self._format_cleanup_item(item))
                    if len(found) >= limit:
                        break
            if len(page) < page_size:
                break
        return {"items": found, "scanned": scanned, "cap_hit": cap_hit}

    def _raw_get(self, operation_name: str, path: str, params: dict | None = None) -> tuple:
        """GET `/{users|groups}/{id}{path}` and return (parsed JSON, {"total", "version"}).

        Goes through pyzotero's `_retrieve_data` (backoff wait + error_handler) but skips
        its `@retrieve` post-processing, which drops tag `meta` and treats any URL that
        contains "tags" as a tag listing. A non-2xx response that error_handler did not
        raise on (a 429 carrying Backoff/Retry-After) is raised here as ZoteroError.
        """
        z = self.zot
        url_path = f"/{z.library_type}/{z.library_id}{path}"
        query = {"format": "json", **(params or {})}

        def fetch():
            z.url_params = None
            resp = z._retrieve_data(url_path, params=dict(query))
            if resp.status_code >= 300:
                raise ZoteroError(
                    f"Zotero returned HTTP {resp.status_code} for {path}"
                    + (" (rate-limited; retry shortly)" if resp.status_code == 429 else "")
                )
            total = resp.headers.get("Total-Results")
            version = resp.headers.get("Last-Modified-Version")
            meta = {
                "total": int(total) if total not in (None, "") else None,
                "version": int(version) if version not in (None, "") else None,
            }
            return resp.json(), meta

        return self._call_zotero(operation_name, fetch)

    def _raw_get_all(self, operation_name: str, path: str, params: dict | None, cap: int) -> tuple:
        """Page a multi-object endpoint (100 per request) up to `cap` objects.

        Returns (objects, total_or_None, capped, library_version_or_None). `capped` is
        True when the server reports more results than were read, or when the
        total is unknown and the last page was full at the cap.
        """
        out: list = []
        total = None
        version = None
        start = 0
        last_full = False
        while len(out) < cap:
            page_limit = min(100, cap - len(out))
            data, meta = self._raw_get(
                operation_name, path, {**(params or {}), "limit": page_limit, "start": start},
            )
            if meta["total"] is not None:
                total = meta["total"]
            if version is None:
                version = meta["version"]
            data = data or []
            out.extend(data)
            start += len(data)
            last_full = len(data) >= page_limit
            if not last_full or (total is not None and start >= total):
                break
        capped = (total > len(out)) if total is not None else (last_full and len(out) >= cap)
        return out, total, capped, version

    @staticmethod
    def _write_error(operation: str, e: ZoteroError) -> ZoteroError:
        """Translate version-precondition failures from a write into actionable errors."""
        cause = type(e.__cause__).__name__ if e.__cause__ is not None else ""
        text = str(e)
        if cause == "PreConditionFailedError" or "Code: 412" in text:
            return ZoteroError(
                f"{operation}: the library changed in Zotero since it was read (HTTP 412, "
                "stale version). Nothing was written; retry to use the current version."
            )
        if cause == "PreConditionRequiredError" or "Code: 428" in text:
            return ZoteroError(
                f"{operation}: Zotero requires a version precondition (HTTP 428) and none "
                "was sent. Nothing was written."
            )
        return e

    def count_results(self, path: str, params: dict | None = None) -> int | None:
        """Return the Total-Results count for a multi-object endpoint (one limit=1 request)."""
        _, meta = self._raw_get("count_results", path, {**(params or {}), "limit": 1})
        return meta["total"]

    def advanced_search(
        self,
        query: str = "",
        qmode: str = "titleCreatorYear",
        tags: list[str] | None = None,
        item_type: str = "",
        sort: str = "dateModified",
        direction: str = "desc",
        include_trashed: bool = False,
        limit: int = 25,
        start: int = 0,
        top_level: bool = True,
    ) -> tuple:
        """Search items with Zotero's full parameter set. Returns (formatted items, total)."""
        params: dict = {"sort": sort, "direction": direction, "limit": limit, "start": start}
        if query:
            params["q"] = query
            params["qmode"] = qmode
        if tags:
            params["tag"] = list(tags)
        if item_type:
            params["itemType"] = item_type
        if include_trashed:
            params["includeTrashed"] = 1
        path = "/items/top" if top_level else "/items"
        data, meta = self._raw_get("advanced_search", path, params)
        return [self._format_item(i) for i in data or []], meta["total"]

    def get_items_by_keys(self, keys: list[str]) -> list[dict]:
        """Fetch raw items by key, 50 keys per request (the API's itemKey maximum)."""
        out: list[dict] = []
        for i in range(0, len(keys), 50):
            chunk = keys[i:i + 50]
            data, _ = self._raw_get(
                "get_items_by_keys", "/items", {"itemKey": ",".join(chunk), "limit": 50},
            )
            out.extend(data or [])
        return out

    def get_recent_changes(self, since_version: int | None, limit: int = 25) -> dict:
        """Library changes for incremental sync.

        Without `since_version`: {"library_version", "recent"} where `recent` is the
        `limit` most recently modified top-level items (formatted). With it:
        {"library_version", "items" (key -> version), "collections" (key -> version),
        "deleted" (the /deleted payload)}.
        """
        if since_version is None:
            data, meta = self._raw_get(
                "recent_items", "/items/top",
                {"sort": "dateModified", "direction": "desc", "limit": limit},
            )
            return {
                "library_version": meta["version"],
                "recent": [self._format_item(i) for i in data or []],
            }
        items, meta = self._raw_get("item_versions", "/items", {"since": since_version, "format": "versions"})
        colls, _ = self._raw_get("collection_versions", "/collections", {"since": since_version, "format": "versions"})
        deleted, _ = self._raw_get("deleted", "/deleted", {"since": since_version})
        return {
            "library_version": meta["version"],
            "items": items or {},
            "collections": colls or {},
            "deleted": deleted or {},
        }

    def list_all_collections(self, cap: int = 5000) -> tuple:
        """All collections (paged), as (list of {key, name, parent_key, num_items, version}, library_version)."""
        raw, _, _, version = self._raw_get_all("list_all_collections", "/collections", None, cap)
        result = []
        for c in raw:
            data = c.get("data", {})
            result.append({
                "key": data.get("key", ""),
                "name": data.get("name", ""),
                "parent_key": data.get("parentCollection") or "",
                "num_items": c.get("meta", {}).get("numItems", 0),
                "version": data.get("version", c.get("version")),
            })
        return result, version

    def get_collection_raw(self, collection_key: str) -> dict | None:
        """Return the raw collection object (with `data` and `version`), or None on 404."""
        try:
            data, _ = self._raw_get("get_collection", f"/collections/{collection_key}")
        except ZoteroError as e:
            if type(e.__cause__).__name__ == "ResourceNotFoundError" or "Code: 404" in str(e):
                return None
            raise
        return data

    def create_collection_checked(self, name: str, parent_key: str = "", library_version: int | None = None) -> dict:
        """Create a collection and re-read it to confirm it exists. Returns its data.

        `library_version` (from the listing used for the duplicate check) is sent as
        If-Unmodified-Since-Version, so a concurrent change surfaces as HTTP 412.
        """
        payload = {"name": name, "parentCollection": parent_key or False}
        try:
            resp = self._call_zotero(
                "create_collection", self.zot.create_collections, [payload], library_version,
            )
        except ZoteroError as e:
            raise self._write_error("create collection", e) from e
        successful = (resp or {}).get("successful", {}) if isinstance(resp, dict) else {}
        if not successful:
            raise ZoteroError(f"Zotero did not create the collection: {resp}")
        key = successful.get("0", {}).get("key") or next(iter(successful.values()), {}).get("key")
        after = self.get_collection_raw(key) if key else None
        data = (after or {}).get("data", {})
        if not after or data.get("name") != name or (data.get("parentCollection") or "") != (parent_key or ""):
            raise ZoteroError(
                f"Create reported success but collection '{name}' could not be read back "
                "(possibly rate-limited). Check Zotero before retrying."
            )
        logger.info("Created Zotero collection %s (%s)", key, name)
        return data

    def update_collection_checked(self, collection_key: str, changes: dict) -> dict:
        """Apply `changes` (name / parentCollection) with a versioned PUT, then verify.

        pyzotero's update_collection returns True even when a 429 with Backoff was
        swallowed, so the collection is re-read and compared; a mismatch raises.
        """
        current = self.get_collection_raw(collection_key)
        if not current:
            raise ZoteroError(f"Collection {collection_key} no longer exists.")
        data = dict(current.get("data", {}))
        data.update(changes)
        if "version" not in data:
            data["version"] = current.get("version")
        try:
            self._call_zotero("update_collection", self.zot.update_collection, data)
        except ZoteroError as e:
            raise self._write_error("update collection", e) from e
        after = self.get_collection_raw(collection_key)
        after_data = (after or {}).get("data", {})

        def norm(v):
            return v or ""

        if not after or any(norm(after_data.get(k)) != norm(v) for k, v in changes.items()):
            raise ZoteroError(
                "Zotero accepted the request but the change is not visible on re-read "
                "(likely rate-limited: HTTP 429 with Backoff). Nothing changed; retry later."
            )
        logger.info("Updated Zotero collection %s: %s", collection_key, sorted(changes))
        return after_data

    def list_tags(self, filter_text: str = "", limit: int = 100) -> tuple:
        """Tags sorted by item count, as ([{tag, num_items, type}], total, capped)."""
        params: dict = {"sort": "numItems", "direction": "desc"}
        if filter_text:
            params["q"] = filter_text
            params["qmode"] = "contains"
        raw, total, capped, _ = self._raw_get_all("list_tags", "/tags", params, limit)
        tags = [
            {
                "tag": t.get("tag", ""),
                "num_items": t.get("meta", {}).get("numItems"),
                "type": t.get("meta", {}).get("type", 0),
            }
            for t in raw
        ]
        if filter_text:
            needle = filter_text.lower()
            tags = [t for t in tags if needle in t["tag"].lower()]
        tags.sort(key=lambda t: -(t["num_items"] or 0))
        return tags, total, capped

    def scan_top_items(self, cap: int) -> tuple:
        """Read up to `cap` top-level items (raw). Returns (items, total, capped)."""
        raw, total, capped, _ = self._raw_get_all(
            "scan_top_items", "/items/top", {"sort": "dateAdded", "direction": "asc"}, cap,
        )
        return raw, total, capped

    def _query_items(self, operation_name: str, **params) -> list[dict]:
        """GET `/items` with `params` via `_raw_get`, so a query containing "tags" is not misparsed."""
        items, _meta = self._raw_get(operation_name, "/items", params)
        return items if isinstance(items, list) else []

    def search_items(self, query: str, limit: int = 20) -> list[dict]:
        """Search the user's Zotero library. Returns formatted item list."""
        items = self._query_items("search_items", q=query, limit=limit, sort="date", direction="desc")
        logger.info("Zotero search for '%s': %d results", query, len(items))
        return [self._format_item(item) for item in items]

    def get_collection_items(self, collection_key: str, limit: int = 50) -> list[dict]:
        """Get items in a specific collection. Returns formatted item list."""
        items = self._call_zotero(
            "get_collection_items",
            self.zot.collection_items,
            collection_key,
            limit=limit,
        )
        return [self._format_item(item) for item in items]


    def check_duplicate(self, metadata: dict) -> dict:
        """Multi-signal deconfliction before saving.

        Checks in priority order:
        1. DOI match (exact)
        2. ISBN match (exact)
        3. Title + author match (fuzzy)

        Returns dict with: is_duplicate, existing_key, match_type,
        existing_item_summary.
        """
        result = {
            "is_duplicate": False,
            "existing_key": None,
            "match_type": None,
            "existing_item_summary": None,
        }

        doi = metadata.get("doi", "")
        if doi:
            try:
                items = self._query_items("check_dup_doi", q=doi, limit=5)
                for item in items:
                    data = item.get("data", {})
                    if (data.get("DOI") or "").strip().lower() == doi.strip().lower():
                        formatted = self._format_item(item)
                        result["is_duplicate"] = True
                        result["existing_key"] = data.get("key", "")
                        result["match_type"] = "DOI"
                        result["existing_item_summary"] = self.format_item_summary(formatted)
                        return result
            except ZoteroError:
                logger.warning("DOI duplicate check failed, continuing")

        isbn = metadata.get("isbn", "")
        if isbn:
            try:
                items = self._query_items("check_dup_isbn", q=isbn, limit=5)
                for item in items:
                    data = item.get("data", {})
                    if (data.get("ISBN") or "").replace("-", "") == isbn.replace("-", ""):
                        formatted = self._format_item(item)
                        result["is_duplicate"] = True
                        result["existing_key"] = data.get("key", "")
                        result["match_type"] = "ISBN"
                        result["existing_item_summary"] = self.format_item_summary(formatted)
                        return result
            except ZoteroError:
                logger.warning("ISBN duplicate check failed, continuing")

        title = metadata.get("title", "")
        if title:
            try:
                items = self._query_items("check_dup_title", q=title[:100], limit=10)
                authors = metadata.get("authors") or metadata.get("creators", [])
                first_author_last = self._extract_last_name(authors[0] if authors else "")

                for item in items:
                    data = item.get("data", {})
                    existing_title = data.get("title") or ""
                    similarity = self._title_similarity(title, existing_title)

                    existing_creators = data.get("creators", [])
                    existing_first_last = ""
                    if existing_creators:
                        existing_first_last = existing_creators[0].get("lastName") or ""

                    author_match = (
                        first_author_last.lower() == existing_first_last.lower()
                        if first_author_last and existing_first_last
                        else False
                    )

                    if similarity > 0.85 and author_match:
                        formatted = self._format_item(item)
                        result["is_duplicate"] = True
                        result["existing_key"] = data.get("key", "")
                        result["match_type"] = "title+author"
                        result["existing_item_summary"] = self.format_item_summary(formatted)
                        return result
            except ZoteroError:
                logger.warning("Title+author duplicate check failed, continuing")

        return result

    @staticmethod
    def _extract_last_name(author_str: str) -> str:
        """Extract last name from an author string."""
        if not author_str:
            return ""
        if "," in author_str:
            return author_str.split(",")[0].strip()
        parts = author_str.strip().split()
        return parts[-1] if parts else ""

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        """Compute normalized title similarity (case-insensitive, stripped punctuation)."""
        def _normalize(s: str) -> str:
            s = s.lower()
            s = re.sub(r'[^\w\s]', '', s)
            s = re.sub(r'\s+', ' ', s).strip()
            return s

        na, nb = _normalize(a), _normalize(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0

        tokens_a = set(na.split())
        tokens_b = set(nb.split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)
