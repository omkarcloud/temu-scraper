"""temu/fetch.py on the identity pool: no network, no box (the mint is faked).
The pool's own rules are tested in tests/test_identity_pool.py.

    python -m pytest temu/test_fetch.py -q
"""
import os

import pytest

import identity_pool
from temu import fetch

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class FakeResponse:
    def __init__(self, status=200, text="", url="https://www.temu.com/x.html"):
        self.status_code, self.text, self.url = status, text, url


class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.closed = False

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return self.responses.pop(0) if self.responses else FakeResponse(text="<html></html>")

    def close(self):
        self.closed = True


@pytest.fixture
def pool(monkeypatch):
    """temu's pool with small budgets and a counting fake mint."""
    monkeypatch.setattr(fetch.config, "TEMU_PRODUCT_PAGES", 2)
    monkeypatch.setattr(fetch.config, "TEMU_LISTING_PAGES", 3)
    monkeypatch.setattr(fetch.config, "TEMU_MINT_AHEAD", False)
    monkeypatch.setattr(fetch.config, "TEMU_MINT_WAIT", 0.3)
    minted = []

    def fake_mint(market, hint=None):
        ident = fetch._Identity(market, None, {"cookies": [{"name": "api_uid", "value": "x"}], "user_agent": "UA"})
        ident.session = FakeSession()
        minted.append(ident)
        return ident

    p = fetch._identities
    p.clear()
    p._mint_times.clear()
    p._mint_fn = fake_mint
    p.minted = minted
    yield p
    p.clear()
    p._mint_times.clear()
    p._mint_fn = fetch._mint


def test_pool_is_exclusive_per_market_with_temu_budgets(pool):
    a = pool.borrow("us", "listing")
    assert pool.mode == "exclusive" and pool.kinds == ("product", "listing")
    assert pool.left(a, "listing") == 2 and pool.left(a, "product") == 2
    pool.give_back(a)
    assert pool.borrow("gb", "listing") is not a and len(pool.minted) == 2


def test_retired_identity_closes_its_session(pool):
    ident = pool.borrow("us", "listing")
    ident.dead = True
    pool.give_back(ident)
    assert ident.closed and ident.session.closed


def test_mint_budget_is_box_down(pool, monkeypatch):
    monkeypatch.setattr(fetch.config, "TEMU_MINTS_PER_MINUTE", 1)
    fetch._page("us", "listing", lambda ids: "u", lambda h, s: s)
    with pytest.raises(fetch.TemuBoxDown):
        fetch._page("gb", "listing", lambda ids: "u", lambda h, s: s)


# ---- _page: what retires an identity ------------------------------------------------------

def test_page_keeps_the_identity_on_success_and_not_found(pool):
    html = open(os.path.join(FIXTURES, "search_desk_organizer.html")).read()
    ident = pool.borrow("us", "listing")
    ident.session = FakeSession([FakeResponse(text=html)])
    pool.give_back(ident)
    store = fetch._page("us", "listing", lambda ids: "https://www.temu.com/x.html", lambda h, s: s)
    assert len(store["goodsList"]) == 20 and not ident.dead
    ident.session.responses = [FakeResponse(status=404)]
    with pytest.raises(fetch.TemuNotFound):
        fetch._page("us", "listing", lambda ids: "u", lambda h, s: s)
    assert not ident.dead and pool.stats("us")["idle"] == 1


@pytest.mark.parametrize("response", [
    FakeResponse(status=403),
    FakeResponse(status=429),
    FakeResponse(url="https://www.temu.com/bgn_verification.html?verifyCode=x"),
])
def test_page_retires_the_identity_when_refused(pool, response):
    ident = pool.borrow("us", "listing")
    ident.session = FakeSession([response])
    pool.give_back(ident)
    with pytest.raises(fetch.TemuBlocked):
        fetch._page("us", "listing", lambda ids: "u", lambda h, s: s)
    assert ident.dead and ident.closed and pool.stats("us")["idle"] == 0


def test_judge_refusal_retires_the_identity(pool):
    def judge(html, store):
        raise fetch.TemuBlocked("client-side shell")
    ident = pool.borrow("us", "listing")
    pool.give_back(ident)
    with pytest.raises(fetch.TemuBlocked):
        fetch._page("us", "listing", lambda ids: "u", judge)
    assert ident.dead and pool.stats("us")["idle"] == 0


def test_fetch_search_reuses_one_identity_across_requests(pool):
    html = open(os.path.join(FIXTURES, "search_desk_organizer.html")).read()
    ident = pool.borrow("us", "listing")
    ident.uses["listing"] = 0
    ident.session = FakeSession([FakeResponse(text=html), FakeResponse(text=html)])
    pool.give_back(ident)
    assert len(fetch.fetch_search("desk organizer")["goodsList"]) == 20
    assert len(fetch.fetch_search("desk organizer")["goodsList"]) == 20
    assert len(pool.minted) == 1 and len(ident.session.calls) == 2


def test_page_size_fallbacks():
    assert fetch.page_size("search") == 20 and fetch.page_size("category") == 40


# ---- listing page N: Temu's (N-1)-th load, whatever its offset ---------------------------

def load(offset, n=3, has_more=True, success=True):
    body = {"success": success, "result": {"has_more": has_more,
                                           "data": {"goods_list": [{"goods_id": offset * 1000 + i} for i in range(n)]}}}
    return {"url": "https://www.temu.com/api/poppy/v1/search?x", "status": 200, "method": "POST",
            "post": '{"offset": %d, "pageSize": 40}' % offset, "body": fetch.json.dumps(body)}


@pytest.fixture
def box(monkeypatch):
    calls = {}

    def fake_capture(url, market, capture, action, times):
        calls.update(url=url, market=market, capture=capture, action=action, times=times)
        return calls["answer"]

    monkeypatch.setattr(fetch, "_box_capture", fake_capture)
    return calls


@pytest.mark.parametrize("step", [20, 24])          # US search, UK search
def test_listing_page_is_the_nth_load_whatever_the_offset(box, step):
    box["answer"] = [load(step), load(2 * step), load(3 * step)]
    body, earlier = fetch.fetch_listing_page("search", "socks", 4)
    assert box["times"] == 3 and box["action"] == "more"
    assert body["result"]["data"]["goods_list"][0]["goods_id"] == 3 * step * 1000
    assert [e["result"]["data"]["goods_list"][0]["goods_id"] for e in earlier] == [step * 1000, 2 * step * 1000]


def test_listing_page_dedupes_a_retried_call(box):
    box["answer"] = [load(20), load(20), load(40)]
    body, earlier = fetch.fetch_listing_page("search", "socks", 3)
    assert body["result"]["data"]["goods_list"][0]["goods_id"] == 40000 and len(earlier) == 1


def test_listing_ended_before_the_page(box):
    box["answer"] = [load(20, has_more=False)]          # page 2 was the last: no "See more" for page 3
    body, earlier = fetch.fetch_listing_page("search", "socks", 3)
    assert body is None and len(earlier) == 1


def test_box_that_loaded_too_few_pages_is_an_error_not_an_empty_page(box):
    box["answer"] = [load(20, has_more=True)]
    with pytest.raises(fetch.TemuBlocked):
        fetch.fetch_listing_page("search", "socks", 3)
    box["answer"] = []
    with pytest.raises(fetch.TemuBlocked):
        fetch.fetch_listing_page("search", "socks", 2)


def test_refused_listing_call(box):
    box["answer"] = [load(20, success=False)]
    with pytest.raises(fetch.TemuBlocked):
        fetch.fetch_listing_page("search", "socks", 2)
