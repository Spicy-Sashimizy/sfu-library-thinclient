"""Unit tests for the Zotero reading tools: annotations, notes, and indexed full text."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from lib.config import ServerConfig
from lib.tools import handle_tool_call
from lib.zotero import ZoteroClient, ZoteroError


def _child(**data):
    return {"key": data.get("key", ""), "data": data}


PARENT = {"key": "P1", "itemType": "journalArticle", "title": "SPLADE v2"}
PDF = {"key": "A1", "itemType": "attachment", "parentItem": "P1", "contentType": "application/pdf",
       "filename": "splade.pdf", "linkMode": "imported_file"}
LINK = {"key": "L1", "itemType": "attachment", "parentItem": "P1", "contentType": "text/html",
        "title": "Publisher page", "linkMode": "linked_url"}
HIGHLIGHT_P2 = {"key": "N2", "itemType": "annotation", "parentItem": "A1", "annotationType": "highlight",
                "annotationText": "sparse lexical expansion", "annotationComment": "key idea",
                "annotationPageLabel": "2", "annotationColor": "#ffd400",
                "annotationSortIndex": "00001|000200|00100", "tags": [{"tag": "method"}]}
NOTE_P1 = {"key": "N1", "itemType": "annotation", "parentItem": "A1", "annotationType": "note",
           "annotationComment": "read first", "annotationPageLabel": "1",
           "annotationSortIndex": "00000|000010|00050", "tags": []}


@pytest.fixture
def client():
    config = ServerConfig(zotero_api_key="k", zotero_user_id="1",
                          circuit_breaker_threshold=5, circuit_breaker_timeout=60.0)
    with patch("lib.zotero.ZoteroClient.zot", new_callable=PropertyMock) as prop:
        pyz = MagicMock()
        prop.return_value = pyz
        yield ZoteroClient(config), pyz


class TestClientReading:
    def test_list_children_pages_until_short_page(self, client):
        zc, pyz = client
        full = [_child(key=f"K{i}", itemType="annotation") for i in range(100)]
        pyz.children.side_effect = [full, [_child(key="K100", itemType="note")]]
        out = zc.list_children("A1", "annotation")
        assert len(out) == 100
        assert pyz.children.call_args_list[1].kwargs == {"limit": 100, "start": 100}

    def test_resolve_parent_excludes_linked_urls(self, client):
        zc, pyz = client
        pyz.item.return_value = {"data": PARENT}
        pyz.children.return_value = [_child(**PDF), _child(**LINK), _child(key="N9", itemType="note")]
        data, atts = zc.resolve_reading_attachments("P1")
        assert data["title"] == "SPLADE v2"
        assert [a["key"] for a in atts] == ["A1"]

    def test_resolve_attachment_key_is_itself(self, client):
        zc, pyz = client
        pyz.item.return_value = {"data": PDF}
        data, atts = zc.resolve_reading_attachments("A1")
        assert atts == [PDF]
        pyz.children.assert_not_called()

    def test_resolve_missing_item(self, client):
        zc, pyz = client

        class ResourceNotFoundError(Exception):
            pass
        pyz.item.side_effect = ResourceNotFoundError("Code: 404")
        assert zc.resolve_reading_attachments("NOPE") is None

    def test_annotations_sorted_by_sort_index(self, client):
        zc, pyz = client
        pyz.children.return_value = [_child(**HIGHLIGHT_P2), _child(**NOTE_P1)]
        assert [a["key"] for a in zc.get_annotations("A1")] == ["N1", "N2"]

    def test_fulltext_404_means_not_indexed(self, client):
        zc, pyz = client

        class ResourceNotFoundError(Exception):
            pass
        pyz.fulltext_item.side_effect = ResourceNotFoundError("Code: 404")
        assert zc.get_fulltext("A1") is None

    def test_fulltext_other_errors_raise(self, client):
        zc, pyz = client
        pyz.fulltext_item.side_effect = RuntimeError("Code: 500")
        with pytest.raises(ZoteroError):
            zc.get_fulltext("A1")

    def test_fulltext_returns_payload(self, client):
        zc, pyz = client
        pyz.fulltext_item.return_value = {"content": "abc", "indexedPages": 3, "totalPages": 3}
        assert zc.get_fulltext("A1")["totalPages"] == 3


class TestNoteHtmlToText:
    def test_paragraphs_lists_entities(self):
        html = ('<div data-schema-version="9"><h1>Summary</h1><p>Uses <strong>sparse</strong> '
                'vectors &amp; expansion.<br>Second line</p><ul><li>one</li><li>two</li></ul>'
                '<script>bad()</script></div>')
        text = ZoteroClient.note_html_to_text(html)
        assert text == "Summary\n\nUses sparse vectors & expansion.\nSecond line\n\n- one\n- two"

    def test_empty(self):
        assert ZoteroClient.note_html_to_text("") == ""


@pytest.fixture
def zot():
    client = MagicMock()
    with patch("lib.tools._ensure_zotero_auth", return_value=None), \
         patch("lib.tools._get_zotero_client", return_value=client), \
         patch("lib.tools._get_features", return_value={}):
        yield client


class TestAnnotationsTool:
    @pytest.mark.asyncio
    async def test_parent_key_groups_by_attachment(self, zot):
        zot.resolve_reading_attachments.return_value = (PARENT, [PDF])
        zot.get_annotations.return_value = [NOTE_P1, HIGHLIGHT_P2]
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "P1"}))[0].text
        assert "ZOTERO ANNOTATIONS: SPLADE v2" in text
        assert "## splade.pdf (application/pdf, key A1): 2 annotations" in text
        assert '[p. 2] highlight (#ffd400): "sparse lexical expansion"' in text
        assert "  Comment: key idea" in text and "  Tags: method" in text
        assert text.index("read first") < text.index("sparse lexical")
        zot.get_annotations.assert_called_once_with("A1")

    @pytest.mark.asyncio
    async def test_attachment_key(self, zot):
        zot.resolve_reading_attachments.return_value = (PDF, [PDF])
        zot.get_annotations.return_value = [HIGHLIGHT_P2]
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "A1"}))[0].text
        assert "1 annotations" in text

    @pytest.mark.asyncio
    async def test_limit_truncates(self, zot):
        zot.resolve_reading_attachments.return_value = (PARENT, [PDF])
        zot.get_annotations.return_value = [NOTE_P1, HIGHLIGHT_P2]
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "P1", "limit": 1}))[0].text
        assert "read first" in text and "sparse lexical" not in text
        assert "Stopped at limit=1" in text

    @pytest.mark.asyncio
    async def test_no_attachments(self, zot):
        zot.resolve_reading_attachments.return_value = (PARENT, [])
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "P1"}))[0].text
        assert text == "'SPLADE v2' has no file attachments, so no annotations."

    @pytest.mark.asyncio
    async def test_no_annotations(self, zot):
        zot.resolve_reading_attachments.return_value = (PARENT, [PDF])
        zot.get_annotations.return_value = []
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "P1"}))[0].text
        assert "No annotations found" in text

    @pytest.mark.asyncio
    async def test_missing_item_and_key(self, zot):
        zot.resolve_reading_attachments.return_value = None
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "X"}))[0].text
        assert text == "No Zotero item with key 'X'."
        text = (await handle_tool_call("get_zotero_annotations", {}))[0].text
        assert text == "No item_key provided."

    @pytest.mark.asyncio
    async def test_zotero_error(self, zot):
        zot.resolve_reading_attachments.side_effect = ZoteroError("boom")
        text = (await handle_tool_call("get_zotero_annotations", {"item_key": "P1"}))[0].text
        assert text == "Zotero error: boom"


class TestNotesTool:
    @pytest.mark.asyncio
    async def test_parent_notes_as_text(self, zot):
        zot.get_item.return_value = {"data": PARENT}
        zot.get_child_notes.return_value = [
            {"key": "T1", "note": "<p>My <em>takeaway</em></p>", "dateModified": "2026-11-01",
             "tags": [{"tag": "thesis"}]},
        ]
        text = (await handle_tool_call("get_zotero_notes", {"item_key": "P1"}))[0].text
        assert "ZOTERO NOTES: SPLADE v2 (1)" in text
        assert "## Note 1 (key T1, modified 2026-11-01)" in text
        assert "My takeaway" in text and "<p>" not in text
        assert "Tags: thesis" in text
        zot.get_child_notes.assert_called_once_with("P1")

    @pytest.mark.asyncio
    async def test_attachment_key_uses_parent_notes(self, zot):
        zot.get_item.return_value = {"data": PDF}
        zot.get_child_notes.return_value = [{"key": "T1", "note": "<p>x</p>"}]
        text = (await handle_tool_call("get_zotero_notes", {"item_key": "A1"}))[0].text
        zot.get_child_notes.assert_called_once_with("P1")
        assert "(1)" in text

    @pytest.mark.asyncio
    async def test_note_key_returns_itself(self, zot):
        zot.get_item.return_value = {"data": {"key": "T2", "itemType": "note", "note": "<p>standalone</p>"}}
        text = (await handle_tool_call("get_zotero_notes", {"item_key": "T2"}))[0].text
        assert "standalone" in text
        zot.get_child_notes.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_notes(self, zot):
        zot.get_item.return_value = {"data": PARENT}
        zot.get_child_notes.return_value = []
        text = (await handle_tool_call("get_zotero_notes", {"item_key": "P1"}))[0].text
        assert text == "'SPLADE v2' has no notes."

    @pytest.mark.asyncio
    async def test_missing_item(self, zot):
        zot.get_item.return_value = None
        text = (await handle_tool_call("get_zotero_notes", {"item_key": "X"}))[0].text
        assert text == "No Zotero item with key 'X'."


class TestFulltextTool:
    @pytest.mark.asyncio
    async def test_parent_key_uses_first_indexed_attachment(self, zot):
        other = dict(PDF, key="A0", filename="supplement.pdf")
        zot.resolve_reading_attachments.return_value = (PARENT, [other, PDF])
        zot.get_fulltext.side_effect = [None, {"content": "x" * 50, "indexedPages": 4, "totalPages": 5}]
        text = (await handle_tool_call("get_zotero_fulltext", {"item_key": "P1"}))[0].text
        assert "Attachment: splade.pdf" in text
        assert "Indexed pages: 4 of 5" in text
        assert "Characters 0-50 of 50" in text and "More text" not in text

    @pytest.mark.asyncio
    async def test_paging(self, zot):
        zot.resolve_reading_attachments.return_value = (PDF, [PDF])
        content = "".join(str(i % 10) for i in range(100))
        zot.get_fulltext.return_value = {"content": content, "indexedChars": 100, "totalChars": 100}
        text = (await handle_tool_call("get_zotero_fulltext",
                                       {"item_key": "A1", "offset": 10, "max_chars": 20}))[0].text
        assert "Indexed chars: 100 of 100" in text
        assert "Characters 10-30 of 100" in text
        assert "call again with offset=30" in text
        assert text.endswith(content[10:30])

    @pytest.mark.asyncio
    async def test_offset_past_end(self, zot):
        zot.resolve_reading_attachments.return_value = (PDF, [PDF])
        zot.get_fulltext.return_value = {"content": "abc"}
        text = (await handle_tool_call("get_zotero_fulltext", {"item_key": "A1", "offset": 3}))[0].text
        assert text == "offset 3 is past the end of the text (3 characters)."

    @pytest.mark.asyncio
    async def test_max_chars_capped(self, zot):
        zot.resolve_reading_attachments.return_value = (PDF, [PDF])
        zot.get_fulltext.return_value = {"content": "y" * 150000, "indexedPages": 1, "totalPages": 1}
        text = (await handle_tool_call("get_zotero_fulltext",
                                       {"item_key": "A1", "max_chars": 10 ** 9}))[0].text
        assert "Characters 0-100000 of 150000" in text

    @pytest.mark.asyncio
    async def test_nothing_indexed(self, zot):
        zot.resolve_reading_attachments.return_value = (PARENT, [PDF])
        zot.get_fulltext.return_value = None
        text = (await handle_tool_call("get_zotero_fulltext", {"item_key": "P1"}))[0].text
        assert text.startswith("No full text is indexed for 'SPLADE v2'.")
        assert "splade.pdf" in text and "Zotero desktop" in text

    @pytest.mark.asyncio
    async def test_no_attachments(self, zot):
        zot.resolve_reading_attachments.return_value = (PARENT, [])
        text = (await handle_tool_call("get_zotero_fulltext", {"item_key": "P1"}))[0].text
        assert text == "'SPLADE v2' has no file attachments, so no full text."
        zot.get_fulltext.assert_not_called()

    @pytest.mark.asyncio
    async def test_note_key_redirects(self, zot):
        zot.resolve_reading_attachments.return_value = ({"itemType": "note"}, [])
        text = (await handle_tool_call("get_zotero_fulltext", {"item_key": "T1"}))[0].text
        assert "use get_zotero_notes" in text

    @pytest.mark.asyncio
    async def test_bad_offset(self, zot):
        text = (await handle_tool_call("get_zotero_fulltext", {"item_key": "A1", "offset": "abc"}))[0].text
        assert text == "offset and max_chars must be integers."
