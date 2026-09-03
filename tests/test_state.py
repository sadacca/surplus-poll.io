import json
import time

from poller.models import Listing
from poller.state import SeenStore


def make_listing(listing_id="1", price=100.0, bid_count=2):
    return Listing(
        site="publicsurplus",
        listing_id=listing_id,
        title="GPU",
        url="http://x",
        price=price,
        bid_count=bid_count,
    )


def test_missing_file_treated_as_empty(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    assert store.is_new(make_listing())


def test_mark_seen_then_not_new(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    listing = make_listing()
    assert store.is_new(listing)
    store.mark_seen(listing, "gpu-search")
    assert not store.is_new(listing)


def test_round_trip_save_and_reload(tmp_path):
    path = str(tmp_path / "seen.json")
    store = SeenStore(path)
    listing = make_listing()
    store.mark_seen(listing, "gpu-search")
    store.save()

    reloaded = SeenStore(path)
    assert not reloaded.is_new(listing)
    record = reloaded.get(listing)
    assert record.last_price == 100.0
    assert record.matched_query_ids == ["gpu-search"]


def test_save_is_noop_when_not_dirty(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(str(path))
    store.save()
    assert not path.exists()


def test_save_is_atomic_no_leftover_tmp_files(tmp_path):
    path = str(tmp_path / "seen.json")
    store = SeenStore(path)
    store.mark_seen(make_listing(), "q1")
    store.save()
    leftovers = [p for p in tmp_path.iterdir() if p.name != "seen.json"]
    assert leftovers == []


def test_prune_drops_stale_entries(tmp_path):
    path = str(tmp_path / "seen.json")
    store = SeenStore(path, prune_after_days=1)
    listing = make_listing()
    store.mark_seen(listing, "q1")
    store.save()

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    key = f"{listing.site}:{listing.listing_id}"
    old_time = time.time() - 2 * 86400
    data["listings"][key]["last_seen"] = old_time
    data["listings"][key]["first_seen"] = old_time
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    store2 = SeenStore(path, prune_after_days=1)
    pruned = store2.prune()
    assert pruned == 1
    assert store2.is_new(listing)


def test_repeat_mark_seen_updates_price_and_appends_query(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    listing = make_listing(price=100.0)
    store.mark_seen(listing, "q1")
    listing2 = make_listing(price=90.0)
    store.mark_seen(listing2, "q2")
    record = store.get(listing2)
    assert record.last_price == 90.0
    assert record.matched_query_ids == ["q1", "q2"]


def test_corrupt_json_file_treated_as_empty(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = SeenStore(str(path))
    assert store.is_new(make_listing())
