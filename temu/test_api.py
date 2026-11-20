"""temu/api.py search by image: page N drops what earlier pages showed, and the
end of the list is an empty page, not an error. No network, no box.

    python -m pytest temu/test_api.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from temu import api, fetch  # noqa: E402


def body(ids, has_more=True):
    return {"success": True, "result": {"has_more": has_more, "data": {"goods_list": [
        {"goods_id": i, "title": f"item {i}", "price_info": {"price": 199, "currency": "USD"}} for i in ids]}}}


def test_page_two_drops_cards_page_one_showed(monkeypatch):
    monkeypatch.setattr(fetch, "search_picture", lambda link: "B64")
    seen = {}

    def fake(picture, page, market):
        seen.update(picture=picture, page=page, market=market)
        return body([3, 4, 5]), [body([1, 2, 3])]
    monkeypatch.setattr(fetch, "fetch_image_search", fake)
    out = api._search_by_image("https://example.com/a.jpg", "us", 2)
    assert seen == {"picture": "B64", "page": 2, "market": "us"}
    assert [card["id"] for card in out["results"]] == ["4", "5"]
    assert out["results"][0]["price"] == 1.99 and out["image"] == "https://example.com/a.jpg"
    assert out["pagination"] == {"page": 2, "items_per_page": 20, "has_next": True, "total_pages": None,
                                 "total_count": None}


def test_past_the_end_is_an_empty_page_and_the_last_page_has_no_next(monkeypatch):
    monkeypatch.setattr(fetch, "search_picture", lambda link: "B64")
    monkeypatch.setattr(fetch, "fetch_image_search", lambda picture, page, market: (None, [body([1], False)]))
    out = api._search_by_image("https://example.com/a.jpg", "us", 3)
    assert out["results"] == [] and out["pagination"]["has_next"] is False
    monkeypatch.setattr(fetch, "fetch_image_search", lambda picture, page, market: (body([9]), []))
    out = api._search_by_image("https://example.com/a.jpg", "us", api.MAX_IMAGE_SEARCH_PAGE)
    assert out["pagination"]["has_next"] is False                      # the page param's own cap


def test_an_empty_first_page_is_not_cached(monkeypatch):
    monkeypatch.setattr(fetch, "search_picture", lambda link: "B64")
    monkeypatch.setattr(fetch, "fetch_image_search", lambda picture, page, market: (body([], False), []))
    out = api._search_by_image("https://example.com/a.jpg", "us", 1)
    assert isinstance(out, api.DontCache) and out.data["results"] == []
