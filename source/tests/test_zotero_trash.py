"""Zotero library-cleanup tools: trash, restore, list trash, list unfiled (mocks only)."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from lib.config import ServerConfig
from lib.tools import TOOL_DEFINITIONS, handle_tool_call
from lib.zotero import ZoteroClient, ZoteroError


def _raw(key, title="T", deleted=False, collections=None, parent="", children=0, version=7, item_type="webpage"):
    data = {
        "key": key, "version": version, "title": title, "itemType": item_type,
        "collections": collections or [], "dateModified": "2026-11-15T00:00:00Z",
    }
    if deleted:
        data["deleted"] = 1
    if parent:
        data["parentItem"] = parent
    return {"key": key, "version": version, "data": data, "meta": {"numChildren": children}}


@pytest.fixture
def client():
    cfg = ServerConfig(zotero_api_key="k", zotero_user_id="1",
                       circuit_breaker_threshold=5, circuit_breaker_timeout=60.0)
    with patch("lib.zotero.ZoteroClient.zot", new_callable=PropertyMock) as prop:
        inst = MagicMock()
        prop.return_value = inst
        c = ZoteroClient(cfg)
        c.pz = inst
        yield c


class TestTrashClient:
    def test_trash_posts_deleted_flag_with_version(self, client):
        items = {"AAAA1111": _raw("AAAA1111", "(1) Instagram • Messages", children=2, version=42)}
        client.pz.item.side_effect = lambda k: items[k]
        client.pz.create_items.return_value = {"successful": {"0": {}}, "success": {"0": "AAAA1111"},
                                               "unchanged": {}, "failed": {}}
        result = client.trash_items(["aaaa1111"])
        client.pz.create_items.assert_called_once_with([{"key": "AAAA1111", "version": 42, "deleted": 1}])
        assert [i["title"] for i in result["changed"]] == ["(1) Instagram • Messages"]
        assert result["changed"][0]["num_children"] == 2
        client.pz.update_item.assert_not_called()
        client.pz.delete_item.assert_not_called()

    def test_already_trashed_and_missing_not_posted(self, client):
        from pyzotero.errors import ResourceNotFoundError

        def item(k):
            if k == "GONE0000":
                raise ResourceNotFoundError("404 not found")
            return _raw(k, deleted=True)
        client.pz.item.side_effect = item
        result = client.trash_items(["TRSH0000", "GONE0000", "TRSH0000"])
        assert [i["key"] for i in result["skipped"]] == ["TRSH0000"]
        assert result["not_found"] == ["GONE0000"]
        client.pz.create_items.assert_not_called()

    def test_restore_sets_deleted_zero(self, client):
        client.pz.item.side_effect = lambda k: _raw(k, deleted=True, version=9)
        client.pz.create_items.return_value = {"failed": {}}
        result = client.restore_items(["BBBB2222"])
        client.pz.create_items.assert_called_once_with([{"key": "BBBB2222", "version": 9, "deleted": 0}])
        assert result["changed"][0]["deleted"] is False

    def test_restore_skips_items_not_in_trash(self, client):
        client.pz.item.side_effect = lambda k: _raw(k)
        result = client.restore_items(["CCCC3333"])
        assert [i["key"] for i in result["skipped"]] == ["CCCC3333"]
        client.pz.create_items.assert_not_called()

    def test_per_item_failure_reported(self, client):
        client.pz.item.side_effect = lambda k: _raw(k)
        client.pz.create_items.return_value = {
            "failed": {"1": {"code": 412, "message": "Item has been modified"}}}
        result = client.trash_items(["AAAA1111", "BBBB2222"])
        assert [i["key"] for i in result["changed"]] == ["AAAA1111"]
        assert result["failed"][0]["key"] == "BBBB2222"
        assert "412" in result["failed"][0]["error"]

    def test_more_than_50_keys_refused(self, client):
        with pytest.raises(ZoteroError):
            client.trash_items([f"K{i:07d}" for i in range(51)])
        client.pz.item.assert_not_called()

    def test_list_trash(self, client):
        client.pz.trash.return_value = [_raw("TRSH0000", "Old", deleted=True)]
        items = client.list_trash(30)
        client.pz.trash.assert_called_once_with(limit=30, sort="dateModified", direction="desc")
        assert items[0]["deleted"] is True
        assert items[0]["date_modified"] == "2026-11-15T00:00:00Z"


class TestUnfiledClient:
    def test_filters_items_with_collections(self, client):
        client.pz.top.return_value = [_raw("FILE0000", collections=["C1"]), _raw("UNF00000", "Stray")]
        result = client.list_unfiled_items(limit=50)
        assert [i["key"] for i in result["items"]] == ["UNF00000"]
        assert result["scanned"] == 2 and result["cap_hit"] is False
        kwargs = client.pz.top.call_args.kwargs
        assert "includeTrashed" not in kwargs
        assert kwargs["start"] == 0 and kwargs["limit"] == 100

    def test_include_trashed_passes_param(self, client):
        client.pz.top.return_value = [_raw("UNF00000", deleted=True)]
        result = client.list_unfiled_items(limit=5, include_trashed=True)
        assert client.pz.top.call_args.kwargs["includeTrashed"] == 1
        assert result["items"][0]["deleted"] is True

    def test_pages_until_cap(self, client):
        def top(**kw):
            return [_raw(f"F{kw['start'] + i:07d}", collections=["C1"]) for i in range(kw["limit"])]
        client.pz.top.side_effect = top
        result = client.list_unfiled_items(limit=50, scan_cap=250)
        assert result["scanned"] == 250 and result["cap_hit"] is True
        assert [c.kwargs["start"] for c in client.pz.top.call_args_list] == [0, 100, 200]
        assert client.pz.top.call_args_list[-1].kwargs["limit"] == 50

    def test_stops_at_limit(self, client):
        client.pz.top.return_value = [_raw(f"U{i:07d}") for i in range(100)]
        result = client.list_unfiled_items(limit=3)
        assert len(result["items"]) == 3 and result["cap_hit"] is False
        assert client.pz.top.call_count == 1


class TestCleanupTools:
    @pytest.fixture
    def zot(self):
        c = MagicMock()
        with patch("lib.tools._ensure_zotero_auth", return_value=None), \
             patch("lib.tools._get_zotero_client", return_value=c), \
             patch("lib.tools._get_features", return_value={}):
            yield c

    def test_definitions_registered_without_permanent_delete(self):
        names = {t.name for t in TOOL_DEFINITIONS}
        assert {"trash_zotero_item", "restore_zotero_item", "list_zotero_trash",
                "list_unfiled_zotero_items"} <= names
        assert not any("empty" in n or n.startswith("delete_zotero") for n in names)
        schema = next(t for t in TOOL_DEFINITIONS if t.name == "trash_zotero_item").inputSchema
        assert schema["properties"]["item_keys"]["maxItems"] == 50

    @pytest.mark.asyncio
    async def test_trash_reports_titles(self, zot):
        zot.trash_items.return_value = {
            "changed": [{"key": "AAAA1111", "title": "(1) Instagram • Messages", "item_type": "webpage",
                         "num_children": 1}],
            "skipped": [{"key": "TRSH0000", "title": "Old", "item_type": "book"}],
            "not_found": ["GONE0000"], "failed": [],
        }
        text = (await handle_tool_call("trash_zotero_item", {"item_keys": ["AAAA1111", "TRSH0000", "GONE0000"]}))[0].text
        zot.trash_items.assert_called_once_with(["AAAA1111", "TRSH0000", "GONE0000"])
        assert "Moved to trash (1)" in text and "(1) Instagram • Messages" in text
        assert "Already in the trash, left unchanged (1)" in text
        assert "Not found in the library (1): GONE0000" in text
        assert "restore_zotero_item" in text

    @pytest.mark.asyncio
    async def test_trash_requires_keys_and_cap(self, zot):
        assert (await handle_tool_call("trash_zotero_item", {}))[0].text == "No item_keys provided."
        text = (await handle_tool_call("trash_zotero_item", {"item_keys": [f"K{i}" for i in range(51)]}))[0].text
        assert "At most 50" in text
        zot.trash_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore(self, zot):
        zot.restore_items.return_value = {
            "changed": [{"key": "BBBB2222", "title": "Back", "item_type": "book"}],
            "skipped": [{"key": "CHLD0000", "title": "note", "item_type": "note", "parent_item": "PPPP0000"}],
            "not_found": [], "failed": [],
        }
        text = (await handle_tool_call("restore_zotero_item", {"item_keys": ["BBBB2222", "CHLD0000"]}))[0].text
        assert "Restored (1)" in text and "Back" in text
        assert "Not in the trash, left unchanged (1)" in text
        assert "restore the parent key" in text

    @pytest.mark.asyncio
    async def test_zotero_error(self, zot):
        zot.trash_items.side_effect = ZoteroError("boom")
        text = (await handle_tool_call("trash_zotero_item", {"item_keys": ["AAAA1111"]}))[0].text
        assert text == "Zotero error: boom"

    @pytest.mark.asyncio
    async def test_list_trash_caps_limit(self, zot):
        zot.list_trash.return_value = [{"key": "TRSH0000", "title": "Old", "item_type": "book",
                                        "date_modified": "2026-11-01T00:00:00Z"}]
        text = (await handle_tool_call("list_zotero_trash", {"limit": 500}))[0].text
        zot.list_trash.assert_called_once_with(100)
        assert "ZOTERO TRASH (1 items)" in text and "TRSH0000" in text and "2026-11-01" in text

    @pytest.mark.asyncio
    async def test_list_trash_empty(self, zot):
        zot.list_trash.return_value = []
        text = (await handle_tool_call("list_zotero_trash", {}))[0].text
        zot.list_trash.assert_called_once_with(50)
        assert text == "The Zotero trash is empty."

    @pytest.mark.asyncio
    async def test_list_unfiled_reports_cap(self, zot):
        zot.list_unfiled_items.return_value = {
            "items": [{"key": "UNF00000", "title": "(1) Instagram • Messages", "item_type": "webpage"}],
            "scanned": 1000, "cap_hit": True,
        }
        text = (await handle_tool_call("list_unfiled_zotero_items", {}))[0].text
        zot.list_unfiled_items.assert_called_once_with(50, False)
        assert "(1) Instagram • Messages" in text and "excluding trashed" in text
        assert "Scan cap of 1000 items reached" in text

    @pytest.mark.asyncio
    async def test_list_unfiled_include_trashed_marks_items(self, zot):
        zot.list_unfiled_items.return_value = {
            "items": [{"key": "UNF00000", "title": "x", "item_type": "webpage", "deleted": True}],
            "scanned": 1, "cap_hit": False,
        }
        text = (await handle_tool_call("list_unfiled_zotero_items", {"include_trashed": True}))[0].text
        zot.list_unfiled_items.assert_called_once_with(50, True)
        assert "IN TRASH" in text and "Scan cap" not in text
