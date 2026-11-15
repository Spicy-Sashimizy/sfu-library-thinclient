"""Unit tests for the Zotero library tools: advanced search, recent changes,
collection management, library stats, duplicate report, and tag listing.

A real ZoteroClient runs over an in-memory stand-in for pyzotero (no network).
"""

from unittest.mock import patch

import pytest
from pyzotero.errors import PreConditionFailedError, PreConditionRequiredError, ResourceNotFoundError

from lib.config import ServerConfig
from lib.tools import TOOL_DEFINITIONS, handle_tool_call
from lib.zotero import ZoteroClient, ZoteroError

NEW_TOOLS = (
    "advanced_search_zotero", "get_zotero_recent_changes", "manage_zotero_collection",
    "get_zotero_library_stats", "find_zotero_duplicates", "list_zotero_tags",
)


class FakeResp:
    def __init__(self, body, status=200, total=None, version=None):
        self._body = body
        self.status_code = status
        self.headers = {}
        if total is not None:
            self.headers["Total-Results"] = str(total)
        if version is not None:
            self.headers["Last-Modified-Version"] = str(version)

    def json(self):
        return self._body


def _item(key, title, item_type="journalArticle", children=0, **data):
    return {"key": key, "data": {"key": key, "title": title, "itemType": item_type, **data},
            "meta": {"numChildren": children}}


class FakeZot:
    """Enough of pyzotero.Zotero for ZoteroClient: _retrieve_data plus collection writes."""

    library_type = "users"
    library_id = "12345"

    def __init__(self):
        self.url_params = None
        self.calls = []
        self.version = 100
        self.items = []
        self.tags = []
        self.colls = {}
        self.write_mode = "ok"
        self.routes = {}

    def add_coll(self, key, name, parent=False, num_items=0):
        self.colls[key] = {"data": {"key": key, "name": name, "parentCollection": parent,
                                    "relations": {}, "version": 5},
                           "meta": {"numItems": num_items}, "version": 5}

    def _page(self, objs, params):
        start = int(params.get("start", 0))
        limit = int(params.get("limit", 100))
        return FakeResp(objs[start:start + limit], total=len(objs), version=self.version)

    def _retrieve_data(self, path, params=None):
        params = params or {}
        self.calls.append((path, dict(params)))
        rel = path.split("/12345", 1)[1]
        if rel in self.routes:
            return self.routes[rel](params)
        if rel == "/collections":
            return self._page(list(self.colls.values()), params)
        if rel.startswith("/collections/"):
            key = rel.rsplit("/", 1)[1]
            if key not in self.colls:
                raise ResourceNotFoundError("\nCode: 404\n")
            return FakeResp(self.colls[key])
        if rel == "/items/top":
            return self._page(self.items, params)
        if rel == "/tags":
            return self._page(self.tags, params)
        if rel in ("/items", "/items/trash"):
            return FakeResp([], total=7, version=self.version)
        raise AssertionError(f"unrouted {rel}")

    def update_collection(self, payload, last_modified=None):
        if self.write_mode == "silent429":
            return True
        if self.write_mode == "412":
            raise PreConditionFailedError("\nCode: 412\n")
        if self.write_mode == "428":
            raise PreConditionRequiredError("\nCode: 428\n")
        current = self.colls[payload["key"]]
        assert payload["version"] == current["version"]
        assert "relations" in payload
        current["data"] = {**payload, "version": current["version"] + 1}
        current["version"] += 1
        return True

    def create_collections(self, payload, last_modified=None):
        if last_modified is not None and last_modified != self.version:
            raise PreConditionFailedError("\nCode: 412\n")
        if self.write_mode == "lost":
            return {"successful": {"0": {"key": "NEWKEY"}}, "failed": {}}
        self.add_coll("NEWKEY", payload[0]["name"], payload[0]["parentCollection"])
        return {"successful": {"0": {"key": "NEWKEY", "data": {}}}, "failed": {}}


@pytest.fixture
def fake():
    return FakeZot()


@pytest.fixture
def client(fake):
    c = ZoteroClient(ServerConfig(zotero_api_key="k", zotero_user_id="12345"))
    c._zot = fake
    with patch("lib.tools._ensure_zotero_auth", return_value=None), \
         patch("lib.tools._get_zotero_client", return_value=c), \
         patch("lib.tools._get_features", return_value={}):
        yield c


async def call(name, args):
    result = await handle_tool_call(name, args)
    return result[0].text


def test_tools_registered_with_schemas():
    by_name = {t.name: t for t in TOOL_DEFINITIONS}
    for name in NEW_TOOLS:
        assert name in by_name
        assert by_name[name].inputSchema["type"] == "object"
    assert by_name["manage_zotero_collection"].inputSchema["properties"]["action"]["enum"] == ["create", "rename", "move"]
    assert by_name["manage_zotero_collection"].inputSchema["required"] == ["action", "collection_name"]


@pytest.mark.asyncio
async def test_auth_error_short_circuits():
    with patch("lib.tools._ensure_zotero_auth", return_value=[type("T", (), {"text": "nope"})()]):
        for name in NEW_TOOLS:
            assert await call(name, {}) == "nope"


class TestRawGet:
    def test_429_with_backoff_is_an_error(self, client, fake):
        fake.routes["/items/top"] = lambda p: FakeResp("rate limited", status=429)
        with pytest.raises(ZoteroError, match="429"):
            client.scan_top_items(10)

    def test_pagination_stops_at_total(self, client, fake):
        fake.items = [_item(f"K{i}", f"T{i}") for i in range(250)]
        items, total, capped = client.scan_top_items(1000)
        assert (len(items), total, capped) == (250, 250, False)
        assert [c[1]["start"] for c in fake.calls] == [0, 100, 200]
        assert all(c[1]["limit"] <= 100 for c in fake.calls)

    def test_pagination_caps(self, client, fake):
        fake.items = [_item(f"K{i}", f"T{i}") for i in range(250)]
        items, total, capped = client.scan_top_items(150)
        assert (len(items), total, capped) == (150, 250, True)
        assert [c[1]["limit"] for c in fake.calls] == [100, 50]

    def test_get_items_by_keys_chunks_50(self, client, fake):
        fake.routes["/items"] = lambda p: FakeResp([{"data": {"key": k}} for k in p["itemKey"].split(",")])
        out = client.get_items_by_keys([f"K{i}" for i in range(120)])
        assert len(out) == 120
        assert [len(c[1]["itemKey"].split(",")) for c in fake.calls] == [50, 50, 20]


class TestAdvancedSearch:
    @pytest.mark.asyncio
    async def test_requires_a_filter(self, client, fake):
        assert await call("advanced_search_zotero", {"limit": 5}) == "Provide at least one of query, tags, or item_types."
        assert fake.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("args,msg", [
        ({"query": "x", "qmode": "fulltext"}, "qmode must be"),
        ({"query": "x", "sort": "relevance"}, "sort must be one of"),
        ({"query": "x", "direction": "up"}, "direction must be"),
        ({"item_types": ["book", "-note"]}, "exactly one '-type'"),
        ({"item_types": ["-book", "-note"]}, "exactly one '-type'"),
    ])
    async def test_validation(self, client, fake, args, msg):
        assert msg in await call("advanced_search_zotero", args)
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_params_and_total(self, client, fake):
        fake.routes["/items/top"] = lambda p: FakeResp([_item("AB12CD34", "Dense retrieval")], total=42)
        text = await call("advanced_search_zotero", {
            "query": "retrieval", "qmode": "everything", "tags": ["ml || ir", "-old"],
            "item_types": ["journalArticle", "book"], "sort": "title", "direction": "asc",
            "include_trashed": True, "limit": 500, "start": 10,
        })
        path, params = fake.calls[0]
        assert path == "/users/12345/items/top"
        assert params["q"] == "retrieval" and params["qmode"] == "everything"
        assert params["tag"] == ["ml || ir", "-old"]
        assert params["itemType"] == "journalArticle || book"
        assert (params["sort"], params["direction"], params["limit"], params["start"]) == ("title", "asc", 100, 10)
        assert params["includeTrashed"] == 1
        assert "results 11-11 of 42" in text
        assert "Dense retrieval" in text and "Zotero Key: AB12CD34" in text
        assert "start=11" in text

    @pytest.mark.asyncio
    async def test_query_containing_tags_word_is_not_misparsed(self, client, fake):
        fake.routes["/items/top"] = lambda p: FakeResp([_item("K1", "Tags and folksonomies")], total=1)
        text = await call("advanced_search_zotero", {"query": "tags"})
        assert "Tags and folksonomies" in text

    @pytest.mark.asyncio
    async def test_exclusion_and_child_types(self, client, fake):
        fake.routes["/items/top"] = lambda p: FakeResp([], total=0)
        fake.routes["/items"] = lambda p: FakeResp([], total=0)
        assert "No Zotero items match" in await call("advanced_search_zotero", {"item_types": ["-book"]})
        assert fake.calls[0][1]["itemType"] == "-book" and fake.calls[0][0].endswith("/items/top")
        await call("advanced_search_zotero", {"item_types": ["note"]})
        assert fake.calls[1][0].endswith("/items")

    @pytest.mark.asyncio
    async def test_api_error(self, client, fake):
        fake.routes["/items/top"] = lambda p: FakeResp("slow down", status=429)
        assert "Zotero search error" in await call("advanced_search_zotero", {"query": "x"})


class TestRecentChanges:
    @pytest.mark.asyncio
    async def test_without_since(self, client, fake):
        fake.items = [_item("K1", "Newest paper")]
        text = await call("get_zotero_recent_changes", {"limit": 3})
        assert fake.calls[0][1]["sort"] == "dateModified" and fake.calls[0][1]["limit"] == 3
        assert "Current library version: 100" in text and "since_version=100" in text
        assert "Newest paper" in text

    @pytest.mark.asyncio
    async def test_bad_since(self, client, fake):
        assert "integer" in await call("get_zotero_recent_changes", {"since_version": "abc"})
        assert ">= 0" in await call("get_zotero_recent_changes", {"since_version": -1})
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_with_since(self, client, fake):
        versions = {f"K{i:03d}": 50 + i for i in range(60)}

        def items_route(p):
            if p.get("format") == "versions":
                assert p["since"] == 40
                return FakeResp(versions, version=120)
            keys = p["itemKey"].split(",")
            return FakeResp([{"data": {"key": k, "title": f"title {k}", "itemType": "book"}} for k in keys])

        fake.routes["/items"] = items_route
        fake.routes["/deleted"] = lambda p: FakeResp({"items": ["GONE1"], "collections": ["CGONE"], "tags": []})
        fake.add_coll("C1", "Retrieval")
        orig = fake._retrieve_data

        def retrieve(path, params=None):
            if path.endswith("/collections") and (params or {}).get("format") == "versions":
                fake.calls.append((path, dict(params)))
                return FakeResp({"C1": 9})
            return orig(path, params)

        fake._retrieve_data = retrieve
        text = await call("get_zotero_recent_changes", {"since_version": 40, "limit": 100})
        assert "New library version: 120" in text
        assert "Changed items: 60 (showing the 50 newest)" in text
        assert "title K059" in text and "title K009" not in text
        key_calls = [c for c in fake.calls if "itemKey" in c[1]]
        assert len(key_calls) == 1 and len(key_calls[0][1]["itemKey"].split(",")) == 50
        assert "Retrieval (key C1, v9)" in text
        assert "Deleted items (1): GONE1" in text and "Deleted collections (1): CGONE" in text

    @pytest.mark.asyncio
    async def test_no_changes(self, client, fake):
        fake.routes["/items"] = lambda p: FakeResp({}, version=100)
        fake.routes["/deleted"] = lambda p: FakeResp({"items": [], "collections": []})
        orig = fake._retrieve_data
        fake._retrieve_data = lambda path, params=None: (
            FakeResp({}) if path.endswith("/collections") else orig(path, params))
        text = await call("get_zotero_recent_changes", {"since_version": 100})
        assert "No changes." in text


class TestManageCollection:
    @pytest.fixture
    def tree(self, fake):
        fake.add_coll("AAAA1111", "Thesis")
        fake.add_coll("BBBB2222", "Chapter 1", "AAAA1111")
        fake.add_coll("CCCC3333", "Drafts", "BBBB2222")
        fake.add_coll("DDDD4444", "Reading")
        fake.add_coll("EEEE5555", "Drafts", "DDDD4444")
        return fake

    @pytest.mark.asyncio
    @pytest.mark.parametrize("args,msg", [
        ({"action": "delete", "collection_name": "Thesis"}, "deletion is not supported"),
        ({"action": "create"}, "No collection_name"),
        ({"action": "rename", "collection_name": "Thesis"}, "rename needs new_name"),
        ({"action": "move", "collection_name": "Thesis"}, "move needs parent_collection"),
    ])
    async def test_validation(self, client, tree, args, msg):
        assert msg in await call("manage_zotero_collection", args)
        assert tree.calls == []

    @pytest.mark.asyncio
    async def test_create_top_level_sends_library_version(self, client, tree):
        text = await call("manage_zotero_collection", {"action": "create", "collection_name": "New Topic"})
        assert text == "Created collection 'New Topic' at the top level (key NEWKEY)."
        assert tree.colls["NEWKEY"]["data"]["parentCollection"] is False

    @pytest.mark.asyncio
    async def test_create_under_parent(self, client, tree):
        text = await call("manage_zotero_collection",
                          {"action": "create", "collection_name": "Notes", "parent_collection": "Chapter 1"})
        assert "at Thesis / Chapter 1" in text
        assert tree.colls["NEWKEY"]["data"]["parentCollection"] == "BBBB2222"

    @pytest.mark.asyncio
    async def test_create_refuses_duplicate_sibling(self, client, tree):
        text = await call("manage_zotero_collection",
                          {"action": "create", "collection_name": "drafts", "parent_collection": "Chapter 1"})
        assert "already exists" in text and "Nothing created" in text
        assert "NEWKEY" not in tree.colls

    @pytest.mark.asyncio
    async def test_create_stale_library_is_412(self, client, tree):
        orig = tree.create_collections
        tree.create_collections = lambda payload, last_modified=None: orig(payload, (last_modified or 0) - 1)
        text = await call("manage_zotero_collection", {"action": "create", "collection_name": "X"})
        assert "HTTP 412" in text and "retry" in text

    @pytest.mark.asyncio
    async def test_create_not_readable_back(self, client, tree):
        tree.write_mode = "lost"
        text = await call("manage_zotero_collection", {"action": "create", "collection_name": "X"})
        assert "could not be read back" in text

    @pytest.mark.asyncio
    async def test_parent_missing_or_ambiguous(self, client, tree):
        assert "Parent: Collection 'Nope' not found" in await call(
            "manage_zotero_collection", {"action": "create", "collection_name": "X", "parent_collection": "Nope"})
        text = await call("manage_zotero_collection", {"action": "rename", "collection_name": "Drafts", "new_name": "D"})
        assert "ambiguous" in text and "Thesis / Chapter 1 / Drafts (key CCCC3333)" in text

    @pytest.mark.asyncio
    async def test_rename_by_key_verified(self, client, tree):
        text = await call("manage_zotero_collection",
                          {"action": "rename", "collection_name": "CCCC3333", "new_name": "Old drafts"})
        assert text == "Renamed 'Thesis / Chapter 1 / Drafts' to 'Old drafts' (key CCCC3333)."
        assert tree.colls["CCCC3333"]["data"]["name"] == "Old drafts"
        assert tree.colls["CCCC3333"]["data"]["parentCollection"] == "BBBB2222"

    @pytest.mark.asyncio
    async def test_rename_missing_and_clash(self, client, tree):
        assert "not found" in await call("manage_zotero_collection",
                                         {"action": "rename", "collection_name": "Nope", "new_name": "X"})
        text = await call("manage_zotero_collection",
                          {"action": "rename", "collection_name": "Thesis", "new_name": "reading"})
        assert "already exists" in text and tree.colls["AAAA1111"]["data"]["name"] == "Thesis"

    @pytest.mark.asyncio
    async def test_rename_silent_429_is_reported(self, client, tree):
        tree.write_mode = "silent429"
        text = await call("manage_zotero_collection",
                          {"action": "rename", "collection_name": "Thesis", "new_name": "Dissertation"})
        assert "not visible on re-read" in text and "429" in text
        assert not text.startswith("Renamed")

    @pytest.mark.asyncio
    async def test_rename_412_and_428(self, client, tree):
        tree.write_mode = "412"
        text = await call("manage_zotero_collection",
                          {"action": "rename", "collection_name": "Thesis", "new_name": "Dissertation"})
        assert "changed in Zotero since it was read (HTTP 412" in text
        tree.write_mode = "428"
        text = await call("manage_zotero_collection",
                          {"action": "rename", "collection_name": "Thesis", "new_name": "Dissertation"})
        assert "HTTP 428" in text

    @pytest.mark.asyncio
    async def test_move_to_top_level_and_under(self, client, tree):
        text = await call("manage_zotero_collection",
                          {"action": "move", "collection_name": "Chapter 1", "parent_collection": ""})
        assert text == "Moved 'Thesis / Chapter 1' to the top level (key BBBB2222)."
        assert tree.colls["BBBB2222"]["data"]["parentCollection"] is False
        text = await call("manage_zotero_collection",
                          {"action": "move", "collection_name": "Chapter 1", "parent_collection": "Reading"})
        assert "Moved 'Chapter 1' to Reading" in text
        assert tree.colls["BBBB2222"]["data"]["parentCollection"] == "DDDD4444"

    @pytest.mark.asyncio
    async def test_move_refusals(self, client, tree):
        assert "under itself" in await call("manage_zotero_collection",
                                            {"action": "move", "collection_name": "Thesis", "parent_collection": "Thesis"})
        assert "under itself" in await call("manage_zotero_collection",
                                            {"action": "move", "collection_name": "Thesis", "parent_collection": "CCCC3333"})
        assert "already at" in await call("manage_zotero_collection",
                                          {"action": "move", "collection_name": "Chapter 1", "parent_collection": "Thesis"})
        text = await call("manage_zotero_collection",
                          {"action": "move", "collection_name": "CCCC3333", "parent_collection": "Reading"})
        assert "already has a collection named 'Drafts'" in text
        assert tree.colls["CCCC3333"]["data"]["parentCollection"] == "BBBB2222"

    @pytest.mark.asyncio
    async def test_move_silent_429(self, client, tree):
        tree.write_mode = "silent429"
        text = await call("manage_zotero_collection",
                          {"action": "move", "collection_name": "Chapter 1", "parent_collection": ""})
        assert "Collection move failed" in text and "not visible on re-read" in text


class TestLibraryStats:
    @pytest.mark.asyncio
    async def test_stats_with_cap(self, client, fake):
        fake.items = ([_item(f"J{i}", f"t{i}") for i in range(700)]
                      + [_item(f"B{i}", f"b{i}", "book") for i in range(500)])
        fake.add_coll("AAAA1111", "Thesis", num_items=12)
        fake.add_coll("BBBB2222", "Chapter 1", "AAAA1111", num_items=3)
        fake.tags = [{"tag": "ml", "meta": {"numItems": 9, "type": 0}},
                     {"tag": "ir", "meta": {"numItems": 4, "type": 0}}]
        text = await call("get_zotero_library_stats", {})
        assert "Top-level items: 1200" in text
        assert "Attachments: 7" in text and "In trash: 7" in text
        assert "first 1000 of 1200 top-level items, capped" in text
        assert "journalArticle: 700" in text and "book: 300" in text
        assert "Thesis / Chapter 1: 3 items" in text and "Thesis: 12 items" in text
        assert "ml: 9 items" in text and "(of 2 distinct)" in text
        attach_call = [c for c in fake.calls if c[1].get("itemType") == "attachment"]
        assert attach_call and attach_call[0][1]["limit"] == 1
        assert sum(1 for c in fake.calls if c[0].endswith("/items/top")) == 10

    @pytest.mark.asyncio
    async def test_stats_error(self, client, fake):
        fake.routes["/items/top"] = lambda p: FakeResp("x", status=500)
        assert "Zotero error" in await call("get_zotero_library_stats", {})


class TestDuplicates:
    @pytest.mark.asyncio
    async def test_groups_by_doi_isbn_title(self, client, fake):
        fake.add_coll("AAAA1111", "Thesis")
        fake.items = [
            _item("D1", "Paper A", DOI="https://doi.org/10.1000/ABC", date="2020", collections=["AAAA1111"]),
            _item("D2", "Paper A (preprint)", "preprint", DOI="10.1000/abc", date="2019"),
            _item("I1", "Some Book", "book", ISBN="0-262-03384-4", date="2009"),
            _item("I2", "Some Book 3rd ed", "book", ISBN="978-0-262-03384-8", date="2009"),
            _item("T1", "Attention Is All You Need!", date="2017-06-12"),
            _item("T2", "attention is all you need", "preprint", date="June 2017"),
            _item("T3", "Attention is all you need", date="2018"),
            _item("X1", "Paper A", date="2020", DOI="10.1000/abc"),
            _item("N1", "note", "note"),
            _item("N2", "note", "note"),
        ]
        text = await call("find_zotero_duplicates", {})
        assert "has no merge operation" in text and "Zotero desktop" in text
        assert "Scanned all 10 top-level items" in text
        assert "same DOI = 10.1000/abc" in text
        assert "same ISBN = 9780262033848" in text
        assert "same title+year = attention is all you need (2017)" in text
        assert "T3:" not in text
        assert "collections=Thesis" in text
        assert "title+year = paper a (2020)" not in text
        assert "3 likely duplicate groups" in text

    @pytest.mark.asyncio
    async def test_cap_reported(self, client, fake):
        fake.items = [_item(f"K{i}", f"unique title {i}") for i in range(2100)]
        text = await call("find_zotero_duplicates", {})
        assert "first 2000 of 2100 top-level items (capped)" in text
        assert "No duplicates found" in text
        assert sum(1 for c in fake.calls if c[0].endswith("/items/top")) == 20


class TestListTags:
    @pytest.mark.asyncio
    async def test_list_with_counts_and_filter(self, client, fake):
        fake.tags = [{"tag": "deep learning", "meta": {"numItems": 3, "type": 0}},
                     {"tag": "Learning to rank", "meta": {"numItems": 8, "type": 1}},
                     {"tag": "other", "meta": {"numItems": 20, "type": 0}}]
        text = await call("list_zotero_tags", {"filter": "learning", "limit": 9999})
        params = fake.calls[0][1]
        assert params["q"] == "learning" and params["sort"] == "numItems" and params["limit"] == 100
        assert "ZOTERO TAGS containing 'learning' (2)" in text
        assert text.index("Learning to rank — 8 items (automatic)") < text.index("deep learning — 3 items")
        assert "other" not in text

    @pytest.mark.asyncio
    async def test_limit_caps(self, client, fake):
        fake.tags = [{"tag": f"t{i}", "meta": {"numItems": 1000 - i}} for i in range(700)]
        text = await call("list_zotero_tags", {"limit": 1000})
        assert "(500 of 700)" in text and "max 500" in text
        assert [c[1]["limit"] for c in fake.calls] == [100] * 5

    @pytest.mark.asyncio
    async def test_empty(self, client, fake):
        assert await call("list_zotero_tags", {"filter": "zzz"}) == "No Zotero tags containing 'zzz'."
