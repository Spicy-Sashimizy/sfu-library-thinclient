"""Unit tests for the Zotero write tools: notes, item edits, collections, tags.

No network: pyzotero is a MagicMock and the item-type field lists are patched.
"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from pyzotero.errors import PreConditionFailedError

from lib.config import ServerConfig
from lib.tools import TOOL_DEFINITIONS, handle_tool_call
from lib.zotero import ZoteroClient

FIELDS = {
    "journalArticle": frozenset({
        "title", "abstractNote", "publicationTitle", "volume", "issue", "pages", "date",
        "DOI", "ISSN", "url", "extra",
    }),
    "book": frozenset({"title", "abstractNote", "publisher", "place", "date", "ISBN", "url", "extra"}),
}


def _item(key="ABCD1234", version=7, **data):
    base = {
        "key": key, "version": version, "itemType": "journalArticle", "title": "Old Title",
        "creators": [{"creatorType": "author", "lastName": "Doe", "firstName": "Jane"}],
        "publicationTitle": "J. Things", "ISSN": "1234-5678", "date": "2020",
        "tags": [{"tag": "keep"}, {"tag": "old", "type": 1}], "collections": ["COLL0001"], "relations": {},
    }
    base.update(data)
    return {"key": key, "version": version, "library": {}, "links": {}, "meta": {}, "data": base}


@pytest.fixture
def pyzot():
    with patch("lib.zotero.ZoteroClient.zot", new_callable=PropertyMock) as prop:
        inst = MagicMock()
        prop.return_value = inst
        yield inst


@pytest.fixture
def client(pyzot):
    c = ZoteroClient(ServerConfig(zotero_api_key="k", zotero_user_id="1"))
    with patch("lib.tools._ensure_zotero_auth", return_value=None), \
         patch("lib.tools._get_zotero_client", return_value=c), \
         patch("lib.tools._get_features", return_value={}), \
         patch("lib.zotero.fetch_zotero_item_type_fields", side_effect=lambda t: FIELDS.get(t)), \
         patch("lib.zotero.fetch_zotero_item_types", return_value=list(FIELDS)):
        yield c


def _text(result):
    return result[0].text


def test_tools_registered():
    names = {t.name for t in TOOL_DEFINITIONS}
    assert {"add_zotero_note", "update_zotero_item", "modify_zotero_collections", "modify_zotero_tags"} <= names
    assert not any("delete" in n or "empty_trash" in n for n in names)


class TestNoteHtml:
    def test_escapes_user_html(self):
        html = ZoteroClient.note_to_html('<script>alert("x")</script> & co')
        assert "<script>" not in html
        assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; co" in html
        assert html.startswith("<p>") and html.endswith("</p>")

    def test_markdown_subset(self):
        md = "# Heading\n\nLine one\nline **two** and *it*\n\n- a\n- `<b>`\n\n1. first\n2. second"
        html = ZoteroClient.note_to_html(md)
        assert "<h1>Heading</h1>" in html
        assert "<p>Line one<br>line <strong>two</strong> and <em>it</em></p>" in html
        assert "<ul><li>a</li><li><code>&lt;b&gt;</code></li></ul>" in html
        assert "<ol><li>first</li><li>second</li></ol>" in html

    def test_links_only_http_and_attribute_safe(self):
        html = ZoteroClient.note_to_html('[ok](https://x.org/a?b=1&c=2) [bad](javascript:alert(1)) [q](https://x.org/"onmouseover=1)')
        assert '<a href="https://x.org/a?b=1&amp;c=2">ok</a>' in html
        assert 'href="javascript' not in html
        assert '"onmouseover' not in html


class TestAddNote:
    @pytest.mark.asyncio
    async def test_creates_child_note(self, client, pyzot):
        pyzot.item.return_value = _item()
        pyzot.create_items.return_value = {"successful": {"0": {"key": "NOTE0001"}}, "failed": {}}
        result = await handle_tool_call("add_zotero_note", {
            "item_key": "ABCD1234", "note": "Read <this> **now**", "tags": ["todo", "todo"],
        })
        assert "Note Key: NOTE0001" in _text(result)
        sent = pyzot.create_items.call_args[0][0][0]
        assert sent["itemType"] == "note"
        assert sent["parentItem"] == "ABCD1234"
        assert sent["note"] == "<p>Read &lt;this&gt; <strong>now</strong></p>"
        assert sent["tags"] == [{"tag": "todo"}]

    @pytest.mark.asyncio
    async def test_refuses_note_parent(self, client, pyzot):
        pyzot.item.return_value = _item(itemType="note")
        result = await handle_tool_call("add_zotero_note", {"item_key": "ABCD1234", "note": "x"})
        assert "is a note" in _text(result)
        pyzot.create_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_note(self, client, pyzot):
        result = await handle_tool_call("add_zotero_note", {"item_key": "ABCD1234", "note": "  "})
        assert _text(result) == "No note text provided."


class TestUpdateItem:
    @pytest.mark.asyncio
    async def test_refuses_unknown_fields(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("update_zotero_item", {
            "item_key": "ABCD1234", "fields": {"title": "New", "ISBN": "x", "bogus": "y"},
        })
        text = _text(result)
        assert "not valid for item type 'journalArticle': ISBN, bogus" in text
        assert "Nothing was written" in text
        pyzot.update_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_fields_and_creators_with_version(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("update_zotero_item", {
            "item_key": "ABCD1234", "fields": {"title": "New Title", "date": "2020"},
            "creators": ["Smith, John", "Ada Lovelace"],
        })
        text = _text(result)
        assert "title: Old Title -> New Title" in text
        assert "creators: Doe, Jane -> Smith, John; Lovelace, Ada" in text
        assert "date:" not in text
        payload = pyzot.update_item.call_args[0][0]
        assert payload["key"] == "ABCD1234" and payload["version"] == 7
        assert payload["title"] == "New Title"
        assert "date" not in payload
        assert payload["creators"][1] == {"creatorType": "author", "lastName": "Lovelace", "firstName": "Ada"}

    @pytest.mark.asyncio
    async def test_type_change_drops_invalid_fields(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("update_zotero_item", {
            "item_key": "ABCD1234", "item_type": "book", "fields": {"publisher": "MIT Press"},
        })
        text = _text(result)
        assert "itemType: journalArticle -> book" in text
        assert "publisher: (empty) -> MIT Press" in text
        assert "Dropped (not valid for book):" in text
        assert "publicationTitle: J. Things" in text and "ISSN: 1234-5678" in text
        payload = pyzot.update_item.call_args[0][0]
        assert payload["itemType"] == "book"
        assert "ISSN" not in payload and "publicationTitle" not in payload

    @pytest.mark.asyncio
    async def test_type_change_validates_against_new_type(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("update_zotero_item", {
            "item_key": "ABCD1234", "item_type": "book", "fields": {"volume": "3"},
        })
        assert "not valid for item type 'book': volume" in _text(result)
        pyzot.update_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_item_type(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("update_zotero_item", {"item_key": "ABCD1234", "item_type": "blogg"})
        assert "Unknown Zotero item type 'blogg'" in _text(result)

    @pytest.mark.asyncio
    async def test_version_conflict(self, client, pyzot):
        pyzot.item.return_value = _item()
        pyzot.update_item.side_effect = PreConditionFailedError("\nCode: 412\n")
        result = await handle_tool_call("update_zotero_item", {"item_key": "ABCD1234", "fields": {"title": "X"}})
        text = _text(result)
        assert "changed in Zotero since it was read" in text
        assert "Retry" in text

    @pytest.mark.asyncio
    async def test_refuses_attachment(self, client, pyzot):
        pyzot.item.return_value = _item(itemType="attachment")
        result = await handle_tool_call("update_zotero_item", {"item_key": "ABCD1234", "fields": {"title": "X"}})
        assert "is a attachment" in _text(result)
        pyzot.update_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_op(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("update_zotero_item", {"item_key": "ABCD1234", "fields": {"title": "Old Title"}})
        assert "No changes" in _text(result)
        pyzot.update_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_item(self, client, pyzot):
        pyzot.item.side_effect = Exception("Code: 404 not found")
        result = await handle_tool_call("update_zotero_item", {"item_key": "NOPE", "fields": {"title": "X"}})
        assert "No Zotero item with key 'NOPE'" in _text(result)


class TestCollections:
    @pytest.mark.asyncio
    async def test_add_creates_collection_and_skips_present(self, client, pyzot):
        pyzot.collections.return_value = []
        pyzot.create_collections.return_value = {"successful": {"0": {"key": "NEWCOLL1"}}}
        items = {
            "AAAA0001": _item("AAAA0001", collections=[]),
            "BBBB0002": _item("BBBB0002", collections=["NEWCOLL1"]),
            "CCCC0003": _item("CCCC0003", itemType="note", parentItem="AAAA0001", collections=[]),
        }
        pyzot.item.side_effect = lambda k: items[k]
        result = await handle_tool_call("modify_zotero_collections", {
            "item_keys": list(items), "collection_name": "Reading", "action": "add",
        })
        text = _text(result)
        assert "[added] AAAA0001" in text
        assert "[unchanged] BBBB0002" in text
        assert "[skipped] CCCC0003" in text
        pyzot.addto_collection.assert_called_once()
        coll, payload = pyzot.addto_collection.call_args[0]
        assert coll == "NEWCOLL1" and payload["key"] == "AAAA0001" and payload["version"] == 7

    @pytest.mark.asyncio
    async def test_remove_does_not_create(self, client, pyzot):
        pyzot.collections.return_value = [{"data": {"key": "COLL0001", "name": "Reading"}, "meta": {}}]
        pyzot.item.return_value = _item()
        result = await handle_tool_call("modify_zotero_collections", {
            "item_keys": ["ABCD1234"], "collection_name": "reading", "action": "remove",
        })
        assert "[removed] ABCD1234" in _text(result)
        pyzot.deletefrom_collection.assert_called_once()
        pyzot.create_collections.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_missing_collection(self, client, pyzot):
        pyzot.collections.return_value = []
        result = await handle_tool_call("modify_zotero_collections", {
            "item_keys": ["ABCD1234"], "collection_name": "Nope", "action": "remove",
        })
        assert _text(result) == "Collection 'Nope' not found in Zotero."
        pyzot.create_collections.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_without_create(self, client, pyzot):
        pyzot.collections.return_value = []
        result = await handle_tool_call("modify_zotero_collections", {
            "item_keys": ["ABCD1234"], "collection_name": "Nope", "action": "add", "create_if_missing": False,
        })
        assert "not found" in _text(result)
        pyzot.create_collections.assert_not_called()

    @pytest.mark.asyncio
    async def test_conflict_reported_per_item(self, client, pyzot):
        pyzot.collections.return_value = [{"data": {"key": "COLL0002", "name": "Reading"}, "meta": {}}]
        pyzot.item.return_value = _item()
        pyzot.addto_collection.side_effect = PreConditionFailedError("Code: 412")
        result = await handle_tool_call("modify_zotero_collections", {
            "item_keys": ["ABCD1234"], "collection_name": "Reading", "action": "add",
        })
        assert "[conflict] ABCD1234" in _text(result)

    @pytest.mark.asyncio
    async def test_batch_limit(self, client, pyzot):
        result = await handle_tool_call("modify_zotero_collections", {
            "item_keys": [f"K{i:07d}" for i in range(51)], "collection_name": "X", "action": "add",
        })
        assert "max 50" in _text(result)
        pyzot.item.assert_not_called()


class TestTags:
    @pytest.mark.asyncio
    async def test_add_and_remove(self, client, pyzot):
        pyzot.item.return_value = _item()
        result = await handle_tool_call("modify_zotero_tags", {
            "item_keys": ["ABCD1234"], "add": ["new", "keep"], "remove": ["old"],
        })
        text = _text(result)
        assert "[updated] ABCD1234" in text and "+new" in text and "-old" in text
        payload = pyzot.update_item.call_args[0][0]
        assert payload == {"key": "ABCD1234", "version": 7, "tags": [{"tag": "keep"}, {"tag": "new"}]}

    @pytest.mark.asyncio
    async def test_unchanged_and_not_found(self, client, pyzot):
        def fetch(k):
            if k == "MISSING1":
                raise Exception("Code: 404")
            return _item(k)
        pyzot.item.side_effect = fetch
        result = await handle_tool_call("modify_zotero_tags", {
            "item_keys": ["ABCD1234", "MISSING1"], "add": ["keep"],
        })
        text = _text(result)
        assert "[unchanged] ABCD1234" in text
        assert "[not_found] MISSING1" in text
        pyzot.update_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_conflict(self, client, pyzot):
        pyzot.item.return_value = _item()
        pyzot.update_item.side_effect = PreConditionFailedError("Code: 412")
        result = await handle_tool_call("modify_zotero_tags", {"item_keys": ["ABCD1234"], "add": ["x"]})
        assert "[conflict] ABCD1234" in _text(result)
        assert "+x" not in _text(result)

    @pytest.mark.asyncio
    async def test_validation(self, client, pyzot):
        assert "at least one" in _text(await handle_tool_call("modify_zotero_tags", {"item_keys": ["A"]}))
        both = await handle_tool_call("modify_zotero_tags", {"item_keys": ["A"], "add": ["t"], "remove": ["t"]})
        assert "both add and remove: t" in _text(both)
        pyzot.item.assert_not_called()
