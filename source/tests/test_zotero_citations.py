"""Tests for export_zotero_citations and ZoteroClient.export_citations (mocks only, no live API)."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

import httpx
import pytest

from lib.config import ServerConfig
from lib.tools import TOOL_DEFINITIONS, handle_tool_call
from lib.zotero import ZoteroClient, ZoteroError


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
    with patch("lib.zotero.ZoteroClient.zot", new_callable=PropertyMock) as mock_zot:
        mock_instance = MagicMock()
        mock_instance.processors = {"bibtex": "BIBTEX_PROC"}
        mock_zot.return_value = mock_instance
        yield mock_instance


IEEE_BIB = (
    '<?xml version="1.0"?>\n<div class="csl-bib-body" style="line-height: 1.35; ">\n'
    '  <div class="csl-entry" style="clear: left; ">\n'
    '    <div class="csl-left-margin" style="float: left;">[1]</div>'
    '<div class="csl-right-inline">J. Smith and A. Lee, &#x201C;Fast ANN &amp; you,&#x201D; '
    '<i>Proc. VLDB</i>, 2020.</div>\n  </div>\n'
    '  <div class="csl-entry" style="clear: left; ">\n'
    '    <div class="csl-left-margin" style="float: left;">[2]</div>'
    '<div class="csl-right-inline">B. Zhou, &#x201C;Sparse retrieval,&#x201D; 2021.</div>\n  </div>\n'
    '</div>'
)


class TestClientExportCitations:
    def test_bib_uses_format_bib_and_parses_entries(self, zot_config, mock_pyzotero):
        mock_pyzotero.items.return_value = IEEE_BIB.encode()
        client = ZoteroClient(zot_config)
        entries = client.export_citations(item_keys=["AAAA1111", "BBBB2222"], fmt="bib", style="ieee")
        mock_pyzotero.items.assert_called_once_with(
            format="bib", style="ieee", locale="en-US", itemKey="AAAA1111,BBBB2222",
        )
        assert entries == [
            "[1] J. Smith and A. Lee, “Fast ANN & you,” Proc. VLDB, 2020.",
            "[2] B. Zhou, “Sparse retrieval,” 2021.",
        ]

    def test_bib_collection_truncates_to_limit(self, zot_config, mock_pyzotero):
        mock_pyzotero.collection_items.return_value = IEEE_BIB
        client = ZoteroClient(zot_config)
        entries = client.export_citations(collection_key="COLL1", fmt="bib", limit=1)
        args, kwargs = mock_pyzotero.collection_items.call_args
        assert args == ("COLL1",)
        assert kwargs["format"] == "bib"
        assert kwargs["itemType"] == "-attachment || note"
        assert "limit" not in kwargs
        assert len(entries) == 1 and entries[0].startswith("[1] J. Smith")

    def test_citation_strips_html(self, zot_config, mock_pyzotero):
        mock_pyzotero.items.return_value = ["<span>(Smith &amp; Lee, 2020)</span>", "<span></span>"]
        client = ZoteroClient(zot_config)
        entries = client.export_citations(item_keys=["AAAA1111", "BBBB2222"], fmt="citation",
                                          style="apa", locale="fr-FR")
        mock_pyzotero.items.assert_called_once_with(
            content="citation", style="apa", locale="fr-FR", limit=2, itemKey="AAAA1111,BBBB2222",
        )
        assert entries == ["(Smith & Lee, 2020)"]

    @pytest.mark.parametrize("fmt", ["bibtex", "ris"])
    def test_text_exports_use_atom_content(self, zot_config, mock_pyzotero, fmt):
        mock_pyzotero.collection_items.return_value = ["\n@article{smith2020,\n title={X}\n}\n", ""]
        client = ZoteroClient(zot_config)
        entries = client.export_citations(collection_key="COLL1", fmt=fmt, limit=7)
        mock_pyzotero.collection_items.assert_called_once_with(
            "COLL1", content=fmt, limit=7, itemType="-attachment || note",
        )
        assert entries == ["@article{smith2020,\n title={X}\n}"]

    def test_biblatex_registers_missing_processor(self, zot_config, mock_pyzotero):
        mock_pyzotero.items.return_value = ["@article{a,}"]
        client = ZoteroClient(zot_config)
        client.export_citations(item_keys=["AAAA1111"], fmt="biblatex")
        assert mock_pyzotero.processors["biblatex"] == "BIBTEX_PROC"

    def test_csljson_flattens_wrappers(self, zot_config, mock_pyzotero):
        mock_pyzotero.items.return_value = [{"items": [{"id": "1", "title": "A"}]}, {"id": "2", "title": "B"}]
        client = ZoteroClient(zot_config)
        entries = client.export_citations(item_keys=["AAAA1111", "BBBB2222"], fmt="csljson")
        assert [e["id"] for e in entries] == ["1", "2"]

    def test_bibtexparser_database_is_dumped(self):
        import bibtexparser
        db = bibtexparser.loads("@article{smith2020,\n title = {X}\n}\n")
        out = ZoteroClient._export_entries_to_text(db)
        assert len(out) == 1 and "smith2020" in out[0]

    def test_validation(self, zot_config, mock_pyzotero):
        client = ZoteroClient(zot_config)
        with pytest.raises(ZoteroError, match="exactly one"):
            client.export_citations(fmt="bib")
        with pytest.raises(ZoteroError, match="exactly one"):
            client.export_citations(item_keys=["AAAA1111"], collection_key="C", fmt="bib")
        with pytest.raises(ZoteroError, match="Unsupported"):
            client.export_citations(item_keys=["AAAA1111"], fmt="docx")
        with pytest.raises(ZoteroError, match="50"):
            client.export_citations(item_keys=[f"K{i:07d}" for i in range(51)])
        mock_pyzotero.items.assert_not_called()

    def test_api_failure_wrapped(self, zot_config, mock_pyzotero):
        mock_pyzotero.items.side_effect = RuntimeError("HTTP 400 invalid style")
        client = ZoteroClient(zot_config)
        with pytest.raises(ZoteroError, match="export_bibliography"):
            client.export_citations(item_keys=["AAAA1111"], fmt="bib", style="nope")


def _atom_feed(entries_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:zapi="http://zotero.org/ns/api">'
        '<title>Items</title><id>http://zotero.org/users/12345/items</id>'
        f'{entries_xml}</feed>'
    )


def _entry(key: str, content: str, ctype: str = "text") -> str:
    return (
        f'<entry><title>t</title><id>http://zotero.org/users/12345/items/{key}</id>'
        f'<zapi:key>{key}</zapi:key><content type="{ctype}">{content}</content></entry>'
    )


class TestRealPyzoteroParsing:
    """Run real pyzotero 1.10 response processing against a mock HTTP transport."""

    def _client(self, zot_config, responder):
        from pyzotero import zotero
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return responder(request)

        pz = zotero.Zotero("12345", "user", "test_api_key",
                           client=httpx.Client(transport=httpx.MockTransport(handler)))
        client = ZoteroClient(zot_config)
        client._zot = pz
        return client, seen

    def test_format_bib_html_bytes(self, zot_config):
        client, seen = self._client(zot_config, lambda r: httpx.Response(
            200, headers={"Content-Type": "text/html; charset=UTF-8"}, text=IEEE_BIB))
        entries = client.export_citations(item_keys=["AAAA1111", "BBBB2222"], fmt="bib", style="ieee")
        assert len(entries) == 2 and entries[1].startswith("[2] B. Zhou")
        params = seen[0].url.params
        assert params["format"] == "bib" and params["style"] == "ieee"
        assert params["itemKey"] == "AAAA1111,BBBB2222"
        assert "limit" not in params

    def test_content_citation_atom(self, zot_config):
        feed = _atom_feed(
            _entry("AAAA1111", '<span xmlns="http://www.w3.org/1999/xhtml">(Smith, 2020)</span>', "xhtml")
        )
        client, seen = self._client(zot_config, lambda r: httpx.Response(
            200, headers={"Content-Type": "application/atom+xml"}, text=feed))
        entries = client.export_citations(item_keys=["AAAA1111"], fmt="citation")
        assert entries == ["(Smith, 2020)"]
        params = seen[0].url.params
        assert params["content"] == "citation" and params["format"] == "atom"

    @pytest.mark.parametrize("fmt", ["bibtex", "biblatex", "ris"])
    def test_content_export_atom(self, zot_config, fmt):
        feed = _atom_feed(_entry("AAAA1111", "@article{smith2020, title = {X &amp; Y}}"))
        client, seen = self._client(zot_config, lambda r: httpx.Response(
            200, headers={"Content-Type": "application/atom+xml"}, text=feed))
        entries = client.export_citations(item_keys=["AAAA1111"], fmt=fmt)
        assert entries == ["@article{smith2020, title = {X & Y}}"]
        assert seen[0].url.params["content"] == fmt

    def test_content_csljson_atom(self, zot_config):
        payload = json.dumps({"id": "12345/AAAA1111", "type": "article-journal", "title": "X"})
        feed = _atom_feed(_entry("AAAA1111", payload))
        client, _ = self._client(zot_config, lambda r: httpx.Response(
            200, headers={"Content-Type": "application/atom+xml"}, text=feed))
        entries = client.export_citations(item_keys=["AAAA1111"], fmt="csljson")
        assert entries == [{"id": "12345/AAAA1111", "type": "article-journal", "title": "X"}]


class TestExportToolHandler:
    @pytest.fixture
    def zot(self):
        client = MagicMock()
        with patch("lib.tools._ensure_zotero_auth", return_value=None), \
             patch("lib.tools._get_zotero_client", return_value=client), \
             patch("lib.tools._get_features", return_value={}):
            yield client

    def test_tool_registered(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.name == "export_zotero_citations")
        props = tool.inputSchema["properties"]
        assert props["format"]["enum"] == ["bib", "citation", "bibtex", "biblatex", "ris", "csljson"]
        assert props["item_keys"]["maxItems"] == 50

    @pytest.mark.asyncio
    async def test_auth_error_short_circuits(self):
        with patch("lib.tools._ensure_zotero_auth",
                   return_value=[MagicMock(text="Zotero integration is disabled.")]):
            result = await handle_tool_call("export_zotero_citations", {"item_keys": ["AAAA1111"]})
        assert result[0].text == "Zotero integration is disabled."

    @pytest.mark.asyncio
    @pytest.mark.parametrize("args, msg", [
        ({}, "Provide exactly one of item_keys or collection_name."),
        ({"item_keys": ["AAAA1111"], "collection_name": "X"}, "Provide exactly one"),
        ({"item_keys": ["bad"]}, "Invalid Zotero item key: 'bad'"),
        ({"item_keys": 5}, "item_keys must be an array"),
        ({"item_keys": [f"K{i:07d}" for i in range(51)]}, "Too many item keys (51)"),
        ({"item_keys": ["AAAA1111"], "format": "docx"}, "Unsupported format 'docx'"),
        ({"item_keys": ["AAAA1111"], "style": "APA; drop"}, "Invalid style"),
        ({"item_keys": ["AAAA1111"], "locale": "english please"}, "Invalid locale"),
        ({"collection_name": "X", "limit": "lots"}, "limit must be an integer"),
    ])
    async def test_input_validation(self, zot, args, msg):
        result = await handle_tool_call("export_zotero_citations", args)
        assert msg in result[0].text
        zot.export_citations.assert_not_called()

    @pytest.mark.asyncio
    async def test_bib_by_keys(self, zot):
        zot.export_citations.return_value = ["Smith, J. (2020). Fast ANN.", "Zhou, B. (2021). Sparse."]
        result = await handle_tool_call("export_zotero_citations", {
            "item_keys": ["aaaa1111", "BBBB2222", "AAAA1111"], "style": "ieee",
        })
        zot.export_citations.assert_called_once_with(
            item_keys=["AAAA1111", "BBBB2222"], collection_key=None, fmt="bib",
            style="ieee", locale="en-US", limit=50,
        )
        text = result[0].text
        assert "ZOTERO BIBLIOGRAPHY (2 entries)" in text
        assert "Style: ieee | Locale: en-US" in text
        assert "Smith, J. (2020). Fast ANN.\n\nZhou, B. (2021). Sparse." in text

    @pytest.mark.asyncio
    async def test_missing_keys_noted(self, zot):
        zot.export_citations.return_value = ["(Smith, 2020)"]
        result = await handle_tool_call("export_zotero_citations", {
            "item_keys": "AAAA1111, BBBB2222", "format": "citation",
        })
        assert "IN-TEXT CITATIONS (1 entries)" in result[0].text
        assert "1 key(s) produced no entry" in result[0].text

    @pytest.mark.asyncio
    async def test_collection_bibtex(self, zot):
        zot.find_collection_by_name.return_value = "COLL1"
        zot.export_citations.return_value = ["@article{a,}", "@book{b,}"]
        result = await handle_tool_call("export_zotero_citations", {
            "collection_name": "Thesis", "format": "BibTeX", "limit": 500,
        })
        zot.export_citations.assert_called_once_with(
            item_keys=None, collection_key="COLL1", fmt="bibtex",
            style="apa", locale="en-US", limit=100,
        )
        text = result[0].text
        assert "ZOTERO BIBTEX EXPORT (2 entries)" in text
        assert "Source: collection 'Thesis'" in text
        assert "Style:" not in text
        assert text.endswith("@article{a,}\n\n@book{b,}")

    @pytest.mark.asyncio
    async def test_csljson_rendered_as_json_array(self, zot):
        zot.export_citations.return_value = [{"id": "1", "title": "Café"}]
        result = await handle_tool_call("export_zotero_citations", {
            "item_keys": ["AAAA1111"], "format": "csljson",
        })
        body = result[0].text.split("=" * 50 + "\n\n", 1)[1]
        assert json.loads(body) == [{"id": "1", "title": "Café"}]

    @pytest.mark.asyncio
    async def test_collection_not_found(self, zot):
        zot.find_collection_by_name.return_value = None
        result = await handle_tool_call("export_zotero_citations", {"collection_name": "Nope"})
        assert result[0].text == "Collection 'Nope' not found in Zotero."
        zot.export_citations.assert_not_called()

    @pytest.mark.asyncio
    async def test_collection_lookup_error(self, zot):
        zot.find_collection_by_name.side_effect = ZoteroError("breaker open")
        result = await handle_tool_call("export_zotero_citations", {"collection_name": "X"})
        assert result[0].text == "Zotero error: breaker open"

    @pytest.mark.asyncio
    async def test_export_error(self, zot):
        zot.export_citations.side_effect = ZoteroError("HTTP 400 invalid style")
        result = await handle_tool_call("export_zotero_citations", {"item_keys": ["AAAA1111"]})
        assert result[0].text == "Zotero citation export error: HTTP 400 invalid style"

    @pytest.mark.asyncio
    async def test_empty_result(self, zot):
        zot.export_citations.return_value = []
        result = await handle_tool_call("export_zotero_citations", {"item_keys": ["AAAA1111"]})
        assert result[0].text.startswith("Zotero returned no bib output for 1 item key(s).")
