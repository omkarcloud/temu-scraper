"""Offline tests for the Temu parsers, reference resolvers and value helpers.

    python -m pytest temu/test_parsers.py -q

Fixtures are real www.temu.com responses captured 2026-10-24 (temu/fixtures/,
see temu/parsers.py's docstring for what each one is): server-rendered
product / search / category pages fetched over curl with a minted US guest
identity, and the signed-call JSON a Windows-box browser captured. No network.
"""
import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from temu import parsers as P, refs  # noqa: E402
from temu.fetch import _Ids, oak_mp_inf  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def js(name):
    return json.loads(raw(name))


def store(name):
    return P.extract_store(raw(name))


@pytest.fixture(scope="module")
def earbuds():
    html = raw("product_earbuds.html")
    return P.parse_product(P.extract_store(html), "606384619891066", html)


@pytest.fixture(scope="module")
def sweater():
    html = raw("product_sweater.html")
    return P.parse_product(P.extract_store(html), "606668674965811", html)


# ---- refs -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("601099513224343", "601099513224343"),
    (" 601099513224343 ", "601099513224343"),
    ("https://www.temu.com/-g-601099513224343.html", "601099513224343"),
    ("https://www.temu.com/uk/some-thing-g-601099513224343.html?_oak_mp_inf=x", "601099513224343"),
    ("https://www.temu.com/goods.html?goods_id=601099513224343&refer_page_sn=10005", "601099513224343"),
    ("www.temu.com/x-g-601099513224343.html", "601099513224343"),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value,message", [
    ("abc", "goods id"),
    ("12345", "goods id"),
    ("https://example.com/x-g-601099513224343.html", "temu.com link"),
    ("https://share.temu.com/AbCdEf", "Share links"),
    ("https://www.temu.com/electronics-o3-248.html", "product link"),
])
def test_resolve_product_rejects(value, message):
    with pytest.raises(ValueError, match=message):
        refs.resolve_product(value)


@pytest.mark.parametrize("value,expected", [
    ("248", "248"),
    ("https://www.temu.com/electronics-o3-248.html?opt_level=1", "248"),
    ("https://www.temu.com/category.html?opt_id=355&opt_level=2", "355"),
    ("https://www.temu.com/ca/headphones-o3-355.html", "355"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("634418229064892", "634418229064892"),
    ("45456903367", "45456903367"),          # older stores have 10-13 digit ids
    ("https://www.temu.com/mall.html?mall_id=3722343564", "3722343564"),
    ("https://www.temu.com/mall.html?mall_id=634418229064892&tag_code=Reviews", "634418229064892"),
    ("https://www.temu.com/some-store-m-634418229064892.html", "634418229064892"),
])
def test_resolve_store(value, expected):
    assert refs.resolve_store(value) == expected


def test_resolve_store_rejects_product_link():
    with pytest.raises(ValueError, match="store link"):
        refs.resolve_store("https://www.temu.com/x-g-601099513224343.html")


def test_filter_items_joins_with_pipe():
    assert refs.filter_items() == ""
    assert refs.filter_items(sort="relevance") == ""
    assert refs.filter_items(sort="top_sales", min_price=5, max_price=10.5) == "1:1|104:5,10.50"
    assert refs.filter_items(min_price=None, max_price=20) == "104:-1,20"
    assert refs.filter_items(sort="price_low_to_high", min_rating="4", category="355", local_warehouse=True) == \
        "2:0|101:355|300:4|400:1"


def test_click_token_round_trips():
    token = oak_mp_inf(606384619891066, "ab" * 16)
    data = base64.b64decode(token)
    assert data[0] == 0x10 and b"ab" * 16 in data
    url = _Ids().product_url("606384619891066")
    assert url.startswith("https://www.temu.com/goods.html?goods_id=606384619891066&_oak_mp_inf=")
    for key in ("refer_page_id=10005_", "_x_sessn_id=", "refer_page_name=home"):
        assert key in url
    search = _Ids().search_url("wireless earbuds", "1:1|104:5,10")
    assert "search_method=shade" in search and "filter_items=1%3A1%7C104%3A5%2C10" in search


# ---- page plumbing ----------------------------------------------------------------------

def test_shell_page_has_no_store():
    html = raw("product_shell.html")
    assert P.extract_store(html) is None
    assert P.doc_source(html) == "csrPath"
    assert P.product_state(None) == "empty"


@pytest.mark.parametrize("name,state", [
    ("product_earbuds.html", "ok"),
    ("product_sweater.html", "ok"),
    ("product_not_found.html", "not_found"),
    ("product_refused.html", "refused"),
    ("product_shell.html", "empty"),
    ("product_unavailable_gb.html", "ok"),
])
def test_product_state(name, state):
    assert P.product_state(store(name)) == state


def test_not_found_and_refused_errors():
    assert P.page_error(store("product_not_found.html")) == {"code": 49001, "message": "GOODS_NOT_EXIST"}
    assert P.page_error(store("product_refused.html"))["code"] == 54001


# ---- product ------------------------------------------------------------------------------

def test_product_identity_and_pricing(earbuds):
    assert earbuds["id"] == "606384619891066"
    assert earbuds["name"].startswith("[HTC Official Flagship] HTC NE79 MINI")
    assert earbuds["link"].endswith("-g-606384619891066.html")
    assert earbuds["item_number"] == "91M7355V94"
    assert earbuds["brand"] == "HTC"
    assert earbuds["is_available"] is True
    assert earbuds["pricing"] == {"price": 7.21, "max_price": 7.87, "list_price": 7.86,
                                  "discount_percent": 8, "currency": "USD"}
    assert earbuds["sold_count"] == 39000
    assert earbuds["rating"] == 4.8 and earbuds["review_count"] == 1272


def test_product_category_ranking_media(earbuds):
    assert earbuds["category"]["id"] == "355"
    assert [c["id"] for c in earbuds["category"]["path"]] == ["248", "355"]
    assert earbuds["ranking"] == {"type": "Top rated", "rank": 3, "category_id": "355",
                                  "category_name": "Headphones, Earbuds & Accessories"}
    assert earbuds["images"][0]["link"].startswith("https://img.kwcdn.com/")
    assert earbuds["video"]["link"].endswith(".mp4")
    assert earbuds["description_images"]
    assert any(d["languages"] == ["English"] for d in earbuds["documents"])
    assert {"name": "Material", "values": ["Plastic"]} in earbuds["attributes"]


def test_product_variants(earbuds):
    assert earbuds["variants_count"] == 3
    assert earbuds["options"] == [{"name": "Color", "values": ["Classic Black", "Retro Blue Brown", "Charm Black Orange"]}]
    cheapest = next(v for v in earbuds["variants"] if v["price"] == 7.21)
    assert cheapest["list_price"] == 7.86 and cheapest["discount_percent"] == 8
    assert cheapest["sold_count"] == 15503 and cheapest["stock"] is not None
    assert cheapest["options"] == [{"name": "Color", "value": "Charm Black Orange"}]


def test_product_store_shipping_returns_reviews(earbuds):
    assert earbuds["store"] == {
        "id": "634418226161321", "name": "HearHere",
        "link": "https://www.temu.com/mall.html?mall_id=634418226161321",
        "logo": earbuds["store"]["logo"], "rating": 4.8, "review_count": 1754, "items_count": 14,
        "sold_count": 81000, "follower_count": 154, "badge": "Star store"}
    option = earbuds["shipping"]["options"][0]
    assert option["cost"] == "Free on all orders" and option["delivery_time"]
    assert option["delivery_days_distribution"][0] == {"days": "≤7 days", "share_percent": 6.0}
    assert earbuds["returns"]["summary"] == "Free returns within 90 days of purchase"
    assert earbuds["review_tags"][0] == {"name": "Great Sound", "count": 50}
    review = earbuds["reviews"][0]
    assert review["date"] == "2026-10-06" and review["author_country"] == "United States"
    assert review["variant"] == [{"name": "Color", "value": "Charm Black Orange"}]


def test_product_many_variants(sweater):
    assert sweater["variants_count"] == 50
    assert [o["name"] for o in sweater["options"]] == ["Color", "Size"]
    first = sweater["variants"][0]
    assert first["options"] == [{"name": "Color", "value": "Beige Color"}, {"name": "Size", "value": "S"}]
    assert first["size_details"] == ["Chest: 35.5 inch, Length: 22.1 inch"]
    assert sweater["shipping"]["is_local_warehouse"] is True
    assert sweater["ranking"]["type"] == "Best sellers" and sweater["ranking"]["rank"] == 2
    assert sweater["pricing"]["max_price"] is None          # one price for every variant


def test_product_not_sold_in_the_market():
    html = raw("product_unavailable_gb.html")
    s = P.extract_store(html)
    assert P.product_state(s) == "ok"
    rec = P.parse_product(s, "601099527403355", html)
    assert rec["name"] is None and rec["is_available"] is False
    assert rec["link"].startswith("https://www.temu.com/uk/compact-wireless-speaker")
    assert rec["pricing"] == {"price": None, "max_price": None, "list_price": None, "discount_percent": None,
                              "currency": "GBP"}
    assert rec["images"][0]["link"].startswith("https://commimg-eu.kwcdn.com/")
    assert rec["category"]["id"] == "1433" and rec["variants"] == []


def test_sparse_product_never_crashes():
    rec = P.parse_product({"goods": {"goodsName": "x", "goodsId": 1}}, "1")
    assert rec["id"] == "1" and rec["variants"] == [] and rec["store"] is None
    assert rec["pricing"]["price"] is None and rec["category"] is None and rec["returns"] is None


# ---- search -------------------------------------------------------------------------------

def test_search_page_renders_20_since_2026_11():
    # a US search renders 20 cards (store pageSize still 40, totalPage 9 of
    # those): a page is Temu's own page, so 360 results are 18 pages of 20
    page = P.parse_search_page(store("search_desk_organizer.html"))
    assert len(page["results"]) == 20 and page["page_size"] == 20
    assert page["total_pages"] == 18 and page["total_count"] is None
    assert page["count_text"] == "1000+" and page["has_next"] is True
    assert all(c["id"] and c["price"] and c["currency"] == "USD" for c in page["results"])


def test_uk_search_pages_by_24():
    # the UK storefront renders (and loads per "See more") 24 (2026-11-07)
    cards = [{"data": {"goodsId": 601099500000000 + i, "title": "x", "priceInfo": {"price": 100}}} for i in range(24)]
    page = P.parse_search_page({"goodsList": cards, "goodsNumAdv": "1000+", "totalPage": 9, "hasMore": True,
                                "pageSize": 40})
    assert page["page_size"] == 24 and page["total_pages"] == 15 and page["has_next"] is True


def test_search_page():
    # the 2026-10-24 capture, when Temu rendered and loaded 40 per page
    page = P.parse_search_page(store("search_wireless_earbuds.html"))
    assert len(page["results"]) == 40 and page["page_size"] == 40
    assert page["total_pages"] == 9 and page["total_count"] is None
    assert page["count_text"] == "1000+" and page["has_next"] is True
    assert page["related_searches"][:2] == ["bluetooth earbuds", "noise cancellation earbuds"]
    card = page["results"][0]
    assert card == {
        "id": "601103128290560", "name": card["name"], "link": card["link"], "image": card["image"],
        "video": None, "price": 6.45, "list_price": 59.99, "discount_percent": 89, "currency": "USD",
        "sold_count": 100000, "rating": 4.7, "review_count": 20104, "store_id": "634418215797445",
        "category_id": "366", "tags": ["BEST-SELLING ITEM in Headphones, Earbuds & Accessories",
                                        "Lowest price in 30 days"], "is_sponsored": True}
    assert "?" not in card["link"] and card["link"].endswith("-g-601103128290560.html")


def test_search_no_results_is_a_real_empty_page():
    s = store("search_no_results.html")
    assert P.search_is_empty(s)
    page = P.parse_search_page(s)
    assert page["results"] == [] and page["total_pages"] == 0 and page["has_next"] is False
    assert page["total_count"] == 0
    assert P.search_is_empty(store("search_wireless_earbuds.html")) is False


@pytest.mark.parametrize("name", ["search_page2.json", "category_page2.json"])
def test_signed_listing_pages(name):
    page = P.parse_search_api(js(name))
    assert len(page["results"]) == 40 and page["has_next"] is True
    assert all(c["id"] and c["price"] and c["currency"] == "USD" for c in page["results"])


def test_small_search_counts_its_own_pages():
    # 53 results: Temu says totalPage 1 with hasMore true (2026-10-24); an
    # exact count decides the pages, in pages of what Temu renders (20)
    cards = [{"data": {"goodsId": 601099500000000 + i, "title": "x", "priceInfo": {"price": 100}}} for i in range(20)]
    small = P.parse_search_page({"goodsList": cards, "goodsNumAdv": "53", "totalPage": 1, "hasMore": True,
                                 "pageSize": 40})
    assert small["total_pages"] == 3 and small["total_count"] == 53 and small["has_next"] is True
    one = P.parse_search_page({"goodsList": cards[:18], "goodsNumAdv": "18", "totalPage": 1, "hasMore": True,
                               "pageSize": 40})
    assert one["total_pages"] == 1 and one["total_count"] == 18 and one["has_next"] is False


def test_sparse_listings():
    assert P.parse_search_page({})["results"] == []
    assert P.parse_search_api({}) == {"results": [], "has_next": False}
    assert P.parse_card({"data": {}}) is None


# ---- categories --------------------------------------------------------------------------

def test_category_page():
    page = P.parse_category_page(store("category_headphones.html"), "355")
    assert page["category"]["id"] == "355" and page["category"]["name"] == "Headphones, Earbuds & Accessories"
    assert [c["id"] for c in page["category"]["path"]] == ["248", "355"]
    assert len(page["results"]) == 40 and page["has_next"] is True


def test_category_sorted_page():
    page = P.parse_category_page(store("category_electronics_top_sales.html"), "248")
    sold = [c["sold_count"] for c in page["results"][:5]]
    assert sold == sorted(sold, reverse=True)


def test_unknown_category():
    assert P.category_is_unknown(store("category_unknown.html"))
    assert not P.category_is_unknown(store("category_headphones.html"))


def test_top_categories_and_subcategories():
    electronics = P.parse_category_page(store("category_electronics_top_sales.html"), "248")
    top = electronics["top_categories"]
    assert len(top) == 34 and top[0] == {
        "id": "36", "name": "Home & Kitchen", "link": "https://www.temu.com/category.html?opt_id=36", "image": top[0]["image"]}
    assert top[0]["image"].startswith("https://img.kwcdn.com/") and all(c["id"] != "-13" for c in top)
    subs = electronics["subcategories"]
    assert len(subs) == 15 and subs[1] == {
        "id": "355", "name": "Headphones, Earbuds & Accessories",
        "link": "https://www.temu.com/category.html?opt_id=355", "image": None}
    leaf = P.parse_category_page(store("category_headphones.html"), "355")
    assert leaf["subcategories"] == [] and len(leaf["top_categories"]) == 34
    assert P.parse_subcategories({}) == [] and P.parse_top_categories({}) == []


# ---- reviews ------------------------------------------------------------------------------

def test_product_reviews_pages():
    one = P.parse_reviews_list(js("reviews_list.json"))
    three = P.parse_reviews_list(js("reviews_list_page3.json"))
    assert len(one["results"]) == 10 and len(three["results"]) == 10 and one["max_reviews"] == 200
    assert not {r["id"] for r in one["results"]} & {r["id"] for r in three["results"]}
    review = one["results"][0]
    assert review["rating"] == 5 and review["date"] == "2026-10-19" and review["fit"] == "Small"
    assert review["variant"] == [{"name": "Color", "value": "Burgundy"}, {"name": "Size", "value": "Label size: XXL"}]


def test_product_reviews_summary():
    info = P.parse_reviews_info(js("reviews_info.json"))
    assert info["review_count"] == 200
    assert info["rating_breakdown"][0] == {"stars": 5, "percent": 88.0}
    assert [f["fit"] for f in info["fit_breakdown"]] == ["Small", "True to size", "Large"]
    assert {"name": "Bought again", "count": 46} in info["tags"]


def test_store_reviews():
    reviews = P.parse_store_reviews(js("store_reviews_list.json"))
    assert len(reviews) == 10
    assert all(r["product"] and r["product"]["id"] and r["product"]["link"] for r in reviews)
    info = P.parse_store_reviews_info(js("store_reviews_info.json"))
    assert info["rating"] == 4.7 and info["review_count"] == 1742 and len(info["rating_breakdown"]) == 5


def test_unknown_store_reviews_are_empty():
    assert P.parse_store_reviews(js("store_reviews_unknown_list.json")) == []
    assert P.parse_store_reviews_info(js("store_reviews_unknown_info.json"))["review_count"] == 0


# ---- helpers ------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("100K+", 100000), ("6.1K+ sold", 6100), ("1.2M+", 1200000), ("20,104", 20104), ("894 sold", 894),
    (None, None), ("", None), (37, 37),
])
def test_count_from_text(text, expected):
    assert P.count_from_text(text) == expected


def test_value_helpers():
    assert P.money(645) == 6.45 and P.money(0) is None and P.money("x") is None
    assert P.discount_percent(6.45, 59.99) == 89 and P.discount_percent(5, None) is None
    assert P.iso_date(1792450584926) == P.iso_date(1792450584) == "2026-10-19"
    assert P.snake({"goodsId": 1, "HWRatio": 2, "priceInfo": {"marketPrice": 3}}) == \
        {"goods_id": 1, "hw_ratio": 2, "price_info": {"market_price": 3}}
    assert P.total_pages_for(200, 10) == 20 and P.total_pages_for(0, 10) == 0


def test_image_search_answer_parses_like_search():
    """A real POST /api/poppy/v1/find_sim answer (box 2026-11-20: our own 500 px
    photo of earbuds) has the search API's shape: 20 cards, more to load."""
    page = P.parse_search_api(js("image_search_page1.json"))
    assert len(page["results"]) == 20 and page["has_next"] is True
    first = page["results"][0]
    assert first["id"] == "601104548227368" and first["price"] == 5.39 and first["list_price"] == 49.99
    assert first["currency"] == "USD" and first["is_sponsored"] is True
    assert first["link"].startswith("https://www.temu.com/") and first["image"].startswith("https://img.kwcdn.com/")
    assert all(card["name"] and card["price"] for card in page["results"])
