"""Unit tests for the Zotero module."""

from unittest.mock import MagicMock, patch, PropertyMock
import time

import pytest

from lib.config import ServerConfig
from lib.retry import CircuitBreaker
from lib import zotero as zotero_mod
from lib.zotero import ZoteroClient, ZoteroError, download_pdf, fetch_zotero_item_type_fields


@pytest.fixture
def zot_config():
    return ServerConfig(
        zotero_api_key="test_api_key",
        zotero_user_id="12345",
        circuit_breaker_threshold=5,
        circuit_breaker_timeout=60.0,
    )


@pytest.fixture
def mock_pyzotero():
    """Mock pyzotero.Zotero instance."""
    with patch("lib.zotero.ZoteroClient.zot", new_callable=PropertyMock) as mock_zot:
        mock_instance = MagicMock()
        mock_zot.return_value = mock_instance
        yield mock_instance


ZOTERO_FIELDS_2026_11_15 = {
    "document": ["title", "abstractNote", "type", "date", "publisher", "place", "DOI", "citationKey",
                 "url", "accessDate", "archive", "archiveLocation", "shortTitle", "language",
                 "libraryCatalog", "callNumber", "rights", "extra"],
    "preprint": ["title", "abstractNote", "genre", "repository", "archiveID", "place", "date", "series",
                 "seriesNumber", "DOI", "citationKey", "url", "accessDate", "archive", "archiveLocation",
                 "shortTitle", "language", "libraryCatalog", "callNumber", "rights", "extra"],
    "journalArticle": ["title", "abstractNote", "publicationTitle", "publisher", "place", "date", "volume",
                       "issue", "section", "partNumber", "partTitle", "pages", "series", "seriesTitle",
                       "seriesText", "journalAbbreviation", "DOI", "citationKey", "url", "accessDate",
                       "PMID", "PMCID", "ISSN", "archive", "archiveLocation", "shortTitle", "language",
                       "libraryCatalog", "callNumber", "rights", "extra"],
    "book": ["title", "abstractNote", "series", "seriesNumber", "volume", "numberOfVolumes", "edition",
             "date", "publisher", "place", "originalDate", "originalPublisher", "originalPlace", "format",
             "numPages", "ISBN", "DOI", "citationKey", "url", "accessDate", "ISSN", "archive",
             "archiveLocation", "shortTitle", "language", "libraryCatalog", "callNumber", "rights", "extra"],
}


@pytest.fixture(autouse=True)
def zotero_schema():
    """Serve item-type fields from a snapshot of api.zotero.org/itemTypeFields (fetched 2026-11-15)."""
    def fake(item_type):
        fields = ZOTERO_FIELDS_2026_11_15.get(item_type)
        return frozenset(fields) if fields else None
    with patch("lib.zotero.fetch_zotero_item_type_fields", side_effect=fake) as m:
        yield m


@pytest.fixture
def zot_client(zot_config, mock_pyzotero):
    client = ZoteroClient(zot_config)
    client._zot = mock_pyzotero
    return client


class TestParseAuthorName:
    def test_parse_author_last_comma_first(self):
        result = ZoteroClient._parse_author_name("Smith, John")
        assert result["lastName"] == "Smith"
        assert result["firstName"] == "John"
        assert result["creatorType"] == "author"

    def test_parse_author_first_last(self):
        result = ZoteroClient._parse_author_name("John Smith")
        assert result["lastName"] == "Smith"
        assert result["firstName"] == "John"

    def test_parse_author_single_name(self):
        result = ZoteroClient._parse_author_name("Aristotle")
        assert result["lastName"] == "Aristotle"
        assert result["firstName"] == ""


class TestMetadataToZoteroItem:
    def test_metadata_to_zotero_article(self, zot_client):
        metadata = {
            "title": "Deep Learning",
            "authors": ["Smith, John"],
            "date": "2023",
            "resource_type": "article",
            "source": "Nature",
            "doi": "10.1000/test",
            "volume": "1",
            "issue": "2",
            "spage": "10",
            "epage": "25",
            "isbn": "",
            "issn": "1234-5678",
            "record_id": "rec_001",
            "publisher": "",
            "pages": "",
        }
        item = zot_client.metadata_to_zotero_item(metadata)
        assert item["itemType"] == "journalArticle"
        assert item["title"] == "Deep Learning"
        assert item["publicationTitle"] == "Nature"

    def test_metadata_to_zotero_book(self, zot_client):
        metadata = {
            "title": "Machine Learning",
            "authors": ["Murphy, Kevin"],
            "date": "2012",
            "resource_type": "book",
            "publisher": "MIT Press",
            "isbn": "9780262018029",
            "source": "",
            "doi": "",
            "volume": "",
            "issue": "",
            "spage": "",
            "epage": "",
            "issn": "",
            "record_id": "rec_002",
            "pages": "",
        }
        item = zot_client.metadata_to_zotero_item(metadata)
        assert item["itemType"] == "book"
        assert item["publisher"] == "MIT Press"

    def test_metadata_to_zotero_other(self, zot_client):
        metadata = {
            "title": "A Document",
            "authors": [],
            "date": "2020",
            "resource_type": "other",
            "source": "",
            "doi": "",
            "volume": "",
            "issue": "",
            "spage": "",
            "epage": "",
            "isbn": "",
            "issn": "",
            "record_id": "",
            "publisher": "",
            "pages": "",
        }
        item = zot_client.metadata_to_zotero_item(metadata)
        assert item["itemType"] == "document"

    def test_metadata_to_zotero_pages_combined(self, zot_client):
        metadata = {
            "title": "Test",
            "authors": [],
            "date": "",
            "resource_type": "article",
            "source": "",
            "doi": "",
            "volume": "",
            "issue": "",
            "spage": "10",
            "epage": "25",
            "pages": "",
            "isbn": "",
            "issn": "",
            "record_id": "",
            "publisher": "",
        }
        item = zot_client.metadata_to_zotero_item(metadata)
        assert item["pages"] == "10-25"

    def test_metadata_to_zotero_record_id_extra(self, zot_client):
        metadata = {
            "title": "Test",
            "authors": [],
            "date": "",
            "resource_type": "article",
            "source": "",
            "doi": "",
            "volume": "",
            "issue": "",
            "spage": "",
            "epage": "",
            "pages": "",
            "isbn": "",
            "issn": "",
            "record_id": "https://openalex.org/W123",
            "publisher": "",
        }
        item = zot_client.metadata_to_zotero_item(metadata)
        assert "https://openalex.org/W123" in item["extra"]


class TestInvalidFieldFiltering:
    """Regression: `'ISSN' is not a valid field for type 'document'` (seen 2026-11-14)."""

    def test_document_drops_issn_and_journal_fields(self, zot_client):
        item = zot_client.metadata_to_zotero_item({
            "title": "Some Report", "authors": ["Doe, Jane"], "resource_type": "other",
            "issn": "1234-5678", "volume": "3", "issue": "2", "pages": "1-9",
            "source": "Somewhere", "doi": "10.1/abc",
        })
        assert item["itemType"] == "document"
        for bad in ("ISSN", "ISBN", "volume", "issue", "pages", "publicationTitle"):
            assert bad not in item
        assert item["DOI"] == "10.1/abc"
        assert item["creators"][0]["lastName"] == "Doe"

    def test_openalex_preprint_maps_to_zotero_preprint(self, zot_client):
        item = zot_client.metadata_to_zotero_item({
            "title": "Bridging Dense and Sparse MIPS", "authors": ["Chen, Tao"],
            "resource_type": "preprint", "source": "arXiv (Cornell University)",
            "issn": "2331-8422", "volume": "", "doi": "10.48550/arxiv.2501.00001",
        })
        assert item["itemType"] == "preprint"
        assert item["repository"] == "arXiv (Cornell University)"
        assert "ISSN" not in item and "volume" not in item

    def test_journal_article_keeps_issn(self, zot_client):
        item = zot_client.metadata_to_zotero_item({
            "title": "Deep Learning", "resource_type": "article", "source": "Nature",
            "issn": "0028-0836", "volume": "521",
        })
        assert item["ISSN"] == "0028-0836"
        assert item["volume"] == "521"
        assert "ISBN" not in item

    def test_explicit_zotero_item_type_overrides_resource_type(self, zot_client):
        item = zot_client.metadata_to_zotero_item({
            "title": "GRIP", "resource_type": "article", "zotero_item_type": "preprint",
            "source": "arXiv (Cornell University)", "issn": "2331-8422",
        })
        assert item["itemType"] == "preprint"
        assert item["repository"] == "arXiv (Cornell University)"
        assert "ISSN" not in item and "publicationTitle" not in item

    def test_schema_unavailable_drops_only_empty_fields(self, zot_client, zotero_schema):
        zotero_schema.side_effect = lambda item_type: None
        item = zot_client.metadata_to_zotero_item({
            "title": "X", "resource_type": "other", "issn": "", "doi": "10.1/x",
        })
        assert "ISSN" not in item
        assert item["DOI"] == "10.1/x"


class TestFetchItemTypeFields:
    def test_fetch_caches_and_falls_back(self, monkeypatch):
        monkeypatch.setattr(zotero_mod, "_item_type_fields_cache", {})
        resp = MagicMock()
        resp.json.return_value = [{"field": "title"}, {"field": "DOI"}]
        with patch("lib.zotero.requests.get", return_value=resp) as get:
            assert fetch_zotero_item_type_fields("document") == frozenset({"title", "DOI"})
            assert fetch_zotero_item_type_fields("document") == frozenset({"title", "DOI"})
            assert get.call_count == 1
        with patch("lib.zotero.requests.get", side_effect=OSError("offline")):
            assert fetch_zotero_item_type_fields("preprint") is None
            monkeypatch.setattr(zotero_mod, "_ITEM_TYPES_TTL", -1)
            assert fetch_zotero_item_type_fields("document") == frozenset({"title", "DOI"})


class TestPdfAttachment:
    def _resp(self, chunks):
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.iter_content.return_value = chunks
        return resp

    def test_download_rewrites_arxiv_abs(self, tmp_path):
        dest = tmp_path / "a.pdf"
        with patch("lib.zotero.requests.get", return_value=self._resp([b"%PDF-1.7", b" rest"])) as get:
            assert download_pdf("https://arxiv.org/abs/2610.30425v1", str(dest)) == 13
        assert get.call_args.args[0] == "https://arxiv.org/pdf/2610.30425v1"

    def test_download_rejects_html_and_removes_partial(self, tmp_path):
        dest = tmp_path / "a.pdf"
        with patch("lib.zotero.requests.get", return_value=self._resp([b"<html>login</html>"])):
            with pytest.raises(ZoteroError, match="not a PDF"):
                download_pdf("https://example.org/paper", str(dest))
        assert not dest.exists()

    def test_download_enforces_size_cap(self, tmp_path):
        dest = tmp_path / "a.pdf"
        with patch("lib.zotero.requests.get", return_value=self._resp([b"%PDF-" + b"x" * 20])):
            with pytest.raises(ZoteroError, match="limit"):
                download_pdf("https://example.org/a.pdf", str(dest), max_bytes=10)
        assert not dest.exists()

    def test_download_rejects_non_http(self, tmp_path):
        with pytest.raises(ZoteroError, match="http"):
            download_pdf("file:///etc/passwd", str(tmp_path / "a.pdf"))

    def test_pdf_attachments_filters_children(self, zot_client, mock_pyzotero):
        mock_pyzotero.children.return_value = [
            {"data": {"key": "A1", "itemType": "attachment", "contentType": "application/pdf"}},
            {"data": {"key": "A2", "itemType": "attachment", "contentType": "text/html"}},
            {"data": {"key": "N1", "itemType": "note"}},
        ]
        assert [a["key"] for a in zot_client.get_pdf_attachments("K1")] == ["A1"]

    def test_attach_file_raises_on_failure(self, zot_client, mock_pyzotero):
        mock_pyzotero.attachment_simple.return_value = {"success": [], "failure": [{"key": "x"}], "unchanged": []}
        with pytest.raises(ZoteroError, match="upload failed"):
            zot_client.attach_file("K1", "/tmp/a.pdf")
        mock_pyzotero.attachment_simple.assert_called_once_with(["/tmp/a.pdf"], "K1")

    def test_get_item_missing_returns_none(self, zot_client, mock_pyzotero):
        class ResourceNotFoundError(Exception):
            pass
        mock_pyzotero.item.side_effect = ResourceNotFoundError("Code: 404")
        assert zot_client.get_item("NOPE") is None


class TestDuplicateDetection:
    def test_check_duplicate_doi_match(self, zot_client, mock_pyzotero):
        mock_pyzotero.items.return_value = [
            {"data": {"key": "ABC123", "DOI": "10.1000/test", "title": "Test", "creators": [], "collections": [], "tags": []}}
        ]
        metadata = {"doi": "10.1000/test", "isbn": "", "title": "Test", "authors": []}
        result = zot_client.check_duplicate(metadata)
        assert result["is_duplicate"] is True
        assert result["match_type"] == "DOI"
        assert result["existing_key"] == "ABC123"

    def test_check_duplicate_isbn_match(self, zot_client, mock_pyzotero):
        mock_pyzotero.items.side_effect = [
            [{"data": {"key": "DEF456", "ISBN": "9780262018029", "title": "ML Book", "creators": [], "collections": [], "tags": []}}],
        ]
        metadata = {"doi": "", "isbn": "9780262018029", "title": "ML Book", "authors": []}
        result = zot_client.check_duplicate(metadata)
        assert result["is_duplicate"] is True
        assert result["match_type"] == "ISBN"

    def test_check_duplicate_title_author_match(self, zot_client, mock_pyzotero):
        mock_pyzotero.items.side_effect = [
            [{"data": {
                "key": "GHI789",
                "title": "Machine Learning: A Probabilistic Perspective",
                "creators": [{"lastName": "Murphy", "firstName": "Kevin"}],
                "DOI": "",
                "ISBN": "",
                "collections": [],
                "tags": [],
            }}],
        ]
        metadata = {
            "doi": "",
            "isbn": "",
            "title": "Machine Learning: A Probabilistic Perspective",
            "authors": ["Murphy, Kevin P."],
        }
        result = zot_client.check_duplicate(metadata)
        assert result["is_duplicate"] is True
        assert result["match_type"] == "title+author"

    def test_check_duplicate_title_similar_diff_author(self, zot_client, mock_pyzotero):
        mock_pyzotero.items.side_effect = [
            [{"data": {
                "key": "JKL012",
                "title": "Machine Learning: A Probabilistic Perspective",
                "creators": [{"lastName": "Bishop", "firstName": "Christopher"}],
                "DOI": "",
                "ISBN": "",
                "collections": [],
                "tags": [],
            }}],
        ]
        metadata = {
            "doi": "",
            "isbn": "",
            "title": "Machine Learning: A Probabilistic Perspective",
            "authors": ["Murphy, Kevin P."],
        }
        result = zot_client.check_duplicate(metadata)
        assert result["is_duplicate"] is False

    def test_check_duplicate_no_match(self, zot_client, mock_pyzotero):
        mock_pyzotero.items.return_value = []
        metadata = {"doi": "10.9999/new", "isbn": "", "title": "Brand New Paper", "authors": ["New, Author"]}
        result = zot_client.check_duplicate(metadata)
        assert result["is_duplicate"] is False

    def test_check_duplicate_no_doi_no_isbn(self, zot_client, mock_pyzotero):
        """Without DOI or ISBN, should fall through to title+author check."""
        mock_pyzotero.items.return_value = []
        metadata = {"doi": "", "isbn": "", "title": "Some Paper", "authors": ["Author, Test"]}
        result = zot_client.check_duplicate(metadata)
        assert result["is_duplicate"] is False
        assert mock_pyzotero.items.call_count >= 1


class TestCollections:
    def test_find_collection_by_name(self, zot_client, mock_pyzotero):
        mock_pyzotero.collections.return_value = [
            {"data": {"key": "COL1", "name": "ML Research", "parentCollection": ""}, "meta": {"numItems": 5}},
            {"data": {"key": "COL2", "name": "Biology", "parentCollection": ""}, "meta": {"numItems": 3}},
        ]
        result = zot_client.find_collection_by_name("ml research")
        assert result == "COL1"

    def test_find_collection_not_found(self, zot_client, mock_pyzotero):
        mock_pyzotero.collections.return_value = [
            {"data": {"key": "COL1", "name": "ML Research", "parentCollection": ""}, "meta": {"numItems": 5}},
        ]
        result = zot_client.find_collection_by_name("Nonexistent")
        assert result is None

    def test_find_or_create_existing(self, zot_client, mock_pyzotero):
        mock_pyzotero.collections.return_value = [
            {"data": {"key": "COL1", "name": "ML Research", "parentCollection": ""}, "meta": {"numItems": 5}},
        ]
        result = zot_client.find_or_create_collection("ML Research")
        assert result == "COL1"
        mock_pyzotero.create_collections.assert_not_called()

    def test_find_or_create_new(self, zot_client, mock_pyzotero):
        mock_pyzotero.collections.return_value = []
        mock_pyzotero.create_collections.return_value = {
            "successful": {"0": {"key": "NEW1"}},
            "failed": {},
        }
        result = zot_client.find_or_create_collection("New Collection")
        assert result == "NEW1"

    def test_list_collections_formatting(self, zot_client, mock_pyzotero):
        mock_pyzotero.collections.return_value = [
            {"data": {"key": "COL1", "name": "Research", "parentCollection": ""}, "meta": {"numItems": 10}},
        ]
        result = zot_client.list_collections()
        assert len(result) == 1
        assert result[0]["key"] == "COL1"
        assert result[0]["name"] == "Research"
        assert result[0]["num_items"] == 10


class TestReadItems:
    def test_search_items_formats_results(self, zot_client, mock_pyzotero):
        mock_pyzotero.items.return_value = [
            {"data": {"key": "K1", "title": "HNSW", "creators": [{"lastName": "Malkov", "firstName": "Yu"}],
                      "itemType": "journalArticle", "DOI": "10.1/x", "tags": [{"tag": "ann"}]}},
        ]
        result = zot_client.search_items("hnsw", 5)
        mock_pyzotero.items.assert_called_once_with(q="hnsw", limit=5, sort="date", direction="desc")
        assert result[0]["key"] == "K1"
        assert result[0]["authors"] == ["Malkov, Yu"]
        assert result[0]["tags"] == ["ann"]

    def test_get_collection_items(self, zot_client, mock_pyzotero):
        mock_pyzotero.collection_items.return_value = [{"data": {"key": "K2", "title": "SPLADE"}}]
        result = zot_client.get_collection_items("COL1", 10)
        mock_pyzotero.collection_items.assert_called_once_with("COL1", limit=10)
        assert result[0]["title"] == "SPLADE"


class TestSubcollections:
    def test_find_collection_by_name_with_parent(self, zot_client, mock_pyzotero):
        """Should only match collections under the specified parent."""
        mock_pyzotero.collections.return_value = [
            {"data": {"key": "COL1", "name": "Papers", "parentCollection": ""}, "meta": {"numItems": 5}},
            {"data": {"key": "COL2", "name": "Papers", "parentCollection": "PARENT1"}, "meta": {"numItems": 3}},
        ]
        result = zot_client.find_collection_by_name("Papers")
        assert result == "COL1"

        result = zot_client.find_collection_by_name("Papers", parent_key="PARENT1")
        assert result == "COL2"

    def test_find_collection_by_name_parent_not_matched(self, zot_client, mock_pyzotero):
        """Should return None if no collection matches under the given parent."""
        mock_pyzotero.collections.return_value = [
            {"data": {"key": "COL1", "name": "Papers", "parentCollection": ""}, "meta": {"numItems": 5}},
        ]
        result = zot_client.find_collection_by_name("Papers", parent_key="NONEXISTENT")
        assert result is None

    def test_create_collection_with_parent(self, zot_client, mock_pyzotero):
        """create_collection with parent_key should include parentCollection in payload."""
        mock_pyzotero.create_collections.return_value = {
            "successful": {"0": {"key": "SUB1"}},
            "failed": {},
        }
        result = zot_client.create_collection("Sub Papers", parent_key="PARENT1")
        assert result == "SUB1"
        call_args = mock_pyzotero.create_collections.call_args[0][0]
        assert call_args[0]["parentCollection"] == "PARENT1"

    def test_create_collection_without_parent(self, zot_client, mock_pyzotero):
        """create_collection without parent_key should not include parentCollection."""
        mock_pyzotero.create_collections.return_value = {
            "successful": {"0": {"key": "TOP1"}},
            "failed": {},
        }
        result = zot_client.create_collection("Top Level")
        assert result == "TOP1"
        call_args = mock_pyzotero.create_collections.call_args[0][0]
        assert "parentCollection" not in call_args[0]

    def test_find_or_create_with_parent(self, zot_client, mock_pyzotero):
        """find_or_create_collection should pass parent_key through."""
        mock_pyzotero.collections.return_value = []
        mock_pyzotero.create_collections.return_value = {
            "successful": {"0": {"key": "NEW_SUB"}},
            "failed": {},
        }
        result = zot_client.find_or_create_collection("New Sub", parent_key="PARENT1")
        assert result == "NEW_SUB"
        call_args = mock_pyzotero.create_collections.call_args[0][0]
        assert call_args[0]["parentCollection"] == "PARENT1"


class TestCircuitBreaker:
    def test_circuit_breaker_opens_after_failures(self, zot_config):
        """5 failures should open the circuit breaker."""
        client = ZoteroClient(zot_config)
        mock_zot = MagicMock()
        client._zot = mock_zot
        mock_zot.collections.side_effect = Exception("API down")

        for _ in range(5):
            with pytest.raises(ZoteroError):
                client._call_zotero("test", mock_zot.collections)

        assert client._breaker.state == CircuitBreaker.OPEN
        with pytest.raises(ZoteroError, match="circuit breaker is OPEN"):
            client._call_zotero("test", mock_zot.collections)

    def test_circuit_breaker_resets_on_success(self, zot_config):
        """Success after failures should close the breaker."""
        client = ZoteroClient(zot_config)
        mock_zot = MagicMock()
        client._zot = mock_zot

        mock_zot.collections.side_effect = Exception("Temporary failure")
        for _ in range(3):
            with pytest.raises(ZoteroError):
                client._call_zotero("test", mock_zot.collections)

        assert client._breaker.failure_count == 3

        mock_zot.collections.side_effect = None
        mock_zot.collections.return_value = []
        client._call_zotero("test", mock_zot.collections)

        assert client._breaker.state == CircuitBreaker.CLOSED
        assert client._breaker.failure_count == 0

    def test_circuit_breaker_half_open_recovery(self, zot_config):
        """After timeout, breaker should allow one test request."""
        client = ZoteroClient(zot_config)
        breaker = client._breaker

        breaker.state = CircuitBreaker.OPEN
        breaker.failure_count = 5
        breaker.last_failure_time = time.time() - 120

        assert breaker.can_proceed() is True
        assert breaker.state == CircuitBreaker.HALF_OPEN

    def test_circuit_breaker_wraps_all_methods(self, zot_client, mock_pyzotero):
        """Verify _call_zotero is used for API calls (breaker records success)."""
        mock_pyzotero.collections.return_value = []
        zot_client.list_collections()

        assert zot_client._breaker.failure_count == 0
        assert zot_client._breaker.state == CircuitBreaker.CLOSED


class TestZoteroAuth:
    def test_verify_credentials_success(self, zot_client, mock_pyzotero):
        """Successful key_info should set _authenticated and return valid."""
        mock_pyzotero.key_info.return_value = {
            "userID": 12345,
            "username": "testuser",
            "access": {
                "user": {
                    "library": True,
                    "files": True,
                    "notes": True,
                    "write": True,
                }
            },
        }
        result = zot_client.verify_credentials()
        assert result["valid"] is True
        assert result["username"] == "testuser"
        assert result["userID"] == 12345
        assert result["access"]["write"] is True
        assert zot_client._authenticated is True
        assert zot_client._auth_info["username"] == "testuser"

    def test_verify_credentials_failure(self, zot_client, mock_pyzotero):
        """Failed key_info should return valid=False."""
        mock_pyzotero.key_info.side_effect = Exception("Forbidden")
        result = zot_client.verify_credentials()
        assert result["valid"] is False
        assert "Forbidden" in result["message"]
        assert zot_client._authenticated is False

    def test_ensure_authenticated_caches(self, zot_client, mock_pyzotero):
        """Second call should not hit API when already authenticated."""
        mock_pyzotero.key_info.return_value = {
            "userID": 12345,
            "username": "testuser",
            "access": {"user": {"library": True, "files": True, "notes": True, "write": True}},
        }
        assert zot_client.ensure_authenticated() is True
        assert mock_pyzotero.key_info.call_count == 1

        assert zot_client.ensure_authenticated() is True
        assert mock_pyzotero.key_info.call_count == 1

    def test_ensure_authenticated_force(self, zot_client, mock_pyzotero):
        """force=True should re-validate even when already authenticated."""
        mock_pyzotero.key_info.return_value = {
            "userID": 12345,
            "username": "testuser",
            "access": {"user": {"library": True, "files": True, "notes": True, "write": True}},
        }
        zot_client.ensure_authenticated()
        assert mock_pyzotero.key_info.call_count == 1

        zot_client.ensure_authenticated(force=True)
        assert mock_pyzotero.key_info.call_count == 2

    def test_ensure_authenticated_no_credentials(self):
        """Empty key/user should return False without API call."""
        config = ServerConfig(zotero_api_key="", zotero_user_id="")
        client = ZoteroClient(config)
        assert client.ensure_authenticated() is False


class TestLazyLoading:
    def test_lazy_load_no_import_until_use(self, zot_config):
        """pyzotero should not be imported at init time."""
        client = ZoteroClient(zot_config)
        assert client._zot is None

    def test_missing_credentials_error(self):
        """No API key should raise clear error."""
        config = ServerConfig(zotero_api_key="", zotero_user_id="")
        client = ZoteroClient(config)
        with pytest.raises(ZoteroError, match="credentials not configured"):
            _ = client.zot
