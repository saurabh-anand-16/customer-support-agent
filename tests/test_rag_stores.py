"""
Tests for the vector stores (agent/rag/stores).

The same contract tests run on every registered store: the in-memory one and ChromaDB. The
ChromaDB runs skip when the `chromadb` package is not installed. Every test builds its own
config from tests/rag_helpers.py and a temporary folder; none reads config/rag.toml.
"""
import pytest

from agent.rag.registry import names
from agent.rag.stores import Record, get_store

from .rag_helpers import make_config

try:
    import chromadb   # noqa: F401
    HAVE_CHROMA = True
except ImportError:
    HAVE_CHROMA = False


@pytest.fixture(params=names("store"))
def kind(request):
    if request.param == "chroma" and not HAVE_CHROMA:
        pytest.skip("chromadb is not installed (pip install -r requirements-rag.txt)")
    return request.param


def open_store(tmp_path, kind, distance="cosine"):
    cfg = make_config(tmp_path, store={"kind": kind, "distance": distance, "collection": "contract_test"})
    return get_store(cfg, path=tmp_path / "store"), cfg


def rec(chunk_id, vector, text=None, **metadata):
    return Record(chunk_id, vector, text or f"text of {chunk_id}", metadata)


def test_both_stores_are_registered():
    assert names("store") == ["chroma", "memory"]


def test_add_then_count_and_ids(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    assert store.count() == 0 and store.ids() == []
    store.add([rec("b", [0, 1]), rec("a", [1, 0])])
    assert store.count() == 2 and store.ids() == ["a", "b"]


def test_adding_an_existing_id_replaces_it_and_never_duplicates(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("a", [1, 0], "old text", page="x")])
    store.add([rec("a", [0, 1], "new text", page="y")])
    assert store.count() == 1
    hit = store.query([0, 1], 1)[0]
    assert (hit.chunk_id, hit.text, hit.metadata) == ("a", "new text", {"page": "y"})


def test_query_returns_the_nearest_first_and_at_most_k(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("far", [0, 1]), rec("near", [1, 0.1]), rec("middle", [1, 1])])
    assert [m.chunk_id for m in store.query([1, 0], 3)] == ["near", "middle", "far"]
    assert [m.chunk_id for m in store.query([1, 0], 2)] == ["near", "middle"]
    assert len(store.query([1, 0], 10)) == 3                       # asking for more than exist is fine


def test_scores_are_higher_for_closer_matches_and_one_for_an_identical_vector(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("same", [1, 0]), rec("other", [0, 1])])
    same, other = store.query([1, 0], 2)
    assert same.chunk_id == "same" and abs(same.score - 1.0) < 1e-4 and same.score > other.score


def test_query_on_an_empty_store_returns_nothing(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    assert store.query([1, 0], 5) == []


def test_a_metadata_filter_keeps_only_matching_records(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("a", [1, 0], in_scope=True, page="p1"), rec("b", [1, 0.1], in_scope=False, page="p1"),
               rec("c", [1, 0.2], in_scope=True, page="p2")])
    assert [m.chunk_id for m in store.query([1, 0], 5, where={"in_scope": True})] == ["a", "c"]
    assert [m.chunk_id for m in store.query([1, 0], 5, where={"in_scope": True, "page": "p2"})] == ["c"]
    assert store.query([1, 0], 5, where={"page": "nothing"}) == []


def test_delete_removes_ids_and_ignores_ids_that_are_not_there(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("a", [1, 0]), rec("b", [0, 1])])
    store.delete(["a", "not-there"])
    store.delete([])
    assert store.ids() == ["b"] and [m.chunk_id for m in store.query([1, 0], 5)] == ["b"]


def test_meta_can_be_saved_and_read_back_and_replaced(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    assert store.get_meta() == {}
    store.set_meta({"fingerprint": "abc", "chunks": 3})
    assert store.get_meta() == {"fingerprint": "abc", "chunks": 3}
    store.set_meta({"fingerprint": "def"})
    assert store.get_meta() == {"fingerprint": "def"}


def test_reset_removes_records_and_meta_but_the_store_still_works(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("a", [1, 0])])
    store.set_meta({"fingerprint": "abc"})
    store.reset()
    assert store.count() == 0 and store.get_meta() == {}
    store.add([rec("z", [1, 0, 0])])                               # even a different vector size is accepted after reset
    assert store.ids() == ["z"]


def test_a_vector_of_the_wrong_size_is_refused(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec("a", [1, 0])])
    with pytest.raises(Exception):
        store.add([rec("b", [1, 0, 0])])


def test_the_configured_distance_decides_what_is_nearest(tmp_path, kind):
    # Query (10, 0). By angle "a" (1, 0) is the closest; by straight-line distance "b" (9, 5) is.
    for distance, expected in [("cosine", "a"), ("l2", "b")]:
        folder = tmp_path / distance
        folder.mkdir()
        store, _ = open_store(folder, kind, distance)
        store.add([rec("a", [1, 0]), rec("b", [9, 5])])
        assert store.query([10, 0], 1)[0].chunk_id == expected, distance


def test_the_same_query_gives_the_same_order_every_time(tmp_path, kind):
    store, _ = open_store(tmp_path, kind)
    store.add([rec(f"id{i}", [1, 0]) for i in range(6)])           # all tied: order must still be fixed
    first = [m.chunk_id for m in store.query([1, 0], 6)]
    assert first == [m.chunk_id for m in store.query([1, 0], 6)] == sorted(first)


@pytest.mark.skipif(not HAVE_CHROMA, reason="chromadb is not installed")
def test_chroma_data_is_still_there_after_the_store_is_opened_again(tmp_path):
    store, cfg = open_store(tmp_path, "chroma")
    store.add([rec("a", [1, 0], "kept", page="p")])
    store.set_meta({"fingerprint": "abc"})
    del store
    again = get_store(cfg, path=tmp_path / "store")
    assert again.ids() == ["a"] and again.get_meta() == {"fingerprint": "abc"}
    assert again.query([1, 0], 1)[0].text == "kept"


@pytest.mark.skipif(not HAVE_CHROMA, reason="chromadb is not installed")
def test_chroma_uses_the_folder_and_collection_name_given_by_the_config(tmp_path):
    cfg = make_config(tmp_path, store={"kind": "chroma", "collection": "my_own_collection"})
    store = get_store(cfg, path=tmp_path / "chosen_folder")
    store.add([rec("a", [1, 0])])
    assert (tmp_path / "chosen_folder").is_dir()
    assert [c.name for c in store._client.list_collections()] == ["my_own_collection"]


def test_an_unknown_store_kind_fails_and_lists_the_real_ones(tmp_path):
    cfg = make_config(tmp_path, store={"kind": "nope"})
    with pytest.raises(KeyError, match="No store named 'nope'.*chroma, memory"):
        get_store(cfg)


def test_the_default_store_folder_comes_from_the_config(tmp_path):
    cfg = make_config(tmp_path, store={"kind": "memory", "path": "some/where"})
    assert get_store(cfg).path == cfg.root / "some/where"
