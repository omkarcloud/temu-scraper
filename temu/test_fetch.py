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


# ---- the pause while Temu refuses every new identity -----------------------------------

@pytest.fixture
def refusing_box(monkeypatch):
    """The box refuses every mint; -> the list of mint calls it received."""
    calls = []

    def mint(site, proxy=None, variant=""):
        calls.append(proxy)
        if calls.trusted:
            return {"cookies": [{"name": "api_uid", "value": "x"}], "user_agent": "UA", "exit_ip": "1.2.3.4"}
        raise fetch.BoxRefused("temu/mint: 502 temu: Temu did not server-render the verification search")

    class Calls(list):
        trusted = False
    calls = Calls()
    monkeypatch.setattr(fetch.browser_client, "mint", mint)
    monkeypatch.setattr(fetch.config, "temu_proxy", lambda market="us": "http://exit")
    monkeypatch.setattr(fetch.config, "TEMU_MINT_ATTEMPTS", 4)
    monkeypatch.setattr(fetch.config, "TEMU_MINT_REFUSALS", 8)
    monkeypatch.setattr(fetch.config, "TEMU_MINT_PAUSE", 300)
    monkeypatch.setattr(fetch, "_refusals", {"streak": 0, "next_probe": 0.0})
    return calls


def test_minting_pauses_after_a_run_of_refused_mints(refusing_box):
    for _ in range(2):                                   # two requests' worth: 8 refused mints
        with pytest.raises(fetch.TemuBlocked):
            fetch._mint("us")
    assert len(refusing_box) == 8
    for _ in range(5):                                   # paused: refused at once, the box is not called
        with pytest.raises(fetch.TemuBlocked, match="refusing every new guest identity"):
            fetch._mint("us")
    assert len(refusing_box) == 8


def test_one_probe_mint_per_pause_and_a_trusted_identity_ends_it(refusing_box, monkeypatch):
    for _ in range(2):
        with pytest.raises(fetch.TemuBlocked):
            fetch._mint("us")
    now = fetch.time.time()
    monkeypatch.setattr(fetch.time, "time", lambda: now + 301)
    with pytest.raises(fetch.TemuBlocked):
        fetch._mint("us")
    assert len(refusing_box) == 9                        # one probe, refused: paused again
    monkeypatch.setattr(fetch.time, "time", lambda: now + 602)
    refusing_box.trusted = True
    ident = fetch._mint("us")
    ident.close()
    assert len(refusing_box) == 10 and fetch._refusals["streak"] == 0
    fetch._mint("us").close()                            # minting is back to normal
    assert len(refusing_box) == 11


def test_a_probe_the_box_could_not_run_is_not_spent(refusing_box, monkeypatch):
    for _ in range(2):
        with pytest.raises(fetch.TemuBlocked):
            fetch._mint("us")
    now = fetch.time.time()
    monkeypatch.setattr(fetch.time, "time", lambda: now + 301)

    def box_down(site, proxy=None, variant=""):
        raise fetch.BoxUnavailable("the box is busy")
    monkeypatch.setattr(fetch.browser_client, "mint", box_down)
    with pytest.raises(fetch.TemuBoxDown):               # the probe never reached Temu
        fetch._mint("us")
    monkeypatch.setattr(fetch.browser_client, "mint",
                        lambda site, proxy=None, variant="": {"cookies": [{"name": "api_uid", "value": "x"}],
                                                              "user_agent": "UA", "exit_ip": "1.2.3.4"})
    fetch._mint("us").close()                            # so the next call probes, without another pause
    assert fetch._refusals["streak"] == 0


# ---- search by image ----------------------------------------------------------------------

def sim_load(offset, n=20, has_more=True, success=True):
    body = {"success": success, "result": {"has_more": has_more,
                                           "data": {"goods_list": [{"goods_id": offset * 1000 + i} for i in range(n)]}}}
    post = fetch.json.dumps({"offset": offset, "pageSize": 20, "imgSearchBytes": "AAAA"})
    return {"url": "https://www.temu.com/api/poppy/v1/find_sim?scene=window_find_sim_img", "status": 200,
            "method": "POST", "post": post, "body": fetch.json.dumps(body)}


@pytest.fixture
def image_box(monkeypatch):
    calls = {}

    def fake_capture(url, market, capture, action, times, **extra):
        calls.update(url=url, market=market, capture=capture, action=action, times=times, **extra)
        return calls["answer"]

    monkeypatch.setattr(fetch, "_box_capture", fake_capture)
    return calls


def test_image_search_page_n_is_n_calls_on_one_list_id(image_box):
    image_box["answer"] = [sim_load(40), sim_load(0), sim_load(20), sim_load(20)]     # any order; a retried call
    body, earlier = fetch.fetch_image_search("PICTURE", 3)
    assert image_box["action"] == "post" and image_box["url"] == fetch.SITE + "/"
    assert image_box["picture"] == "PICTURE" and image_box["capture"] == [fetch.IMAGE_SEARCH_CALL]
    calls = image_box["calls"]
    assert [c[1]["offset"] for c in calls] == [0, 20, 40]
    assert len({c[1]["listId"] for c in calls}) == 1 and len(calls[0][1]["listId"]) == 32
    assert all(c[0] == "/api/poppy/v1/find_sim?scene=window_find_sim_img" for c in calls)
    assert all(c[1]["imgSearchBytes"] == "<picture>" and c[1]["scene"] == "window_find_sim_img" for c in calls)
    assert body["result"]["data"]["goods_list"][0]["goods_id"] == 40000
    assert [e["result"]["data"]["goods_list"][0]["goods_id"] for e in earlier] == [0, 20000]


def test_image_search_list_ended_before_the_page(image_box):
    image_box["answer"] = [sim_load(0, n=7, has_more=False)]
    body, earlier = fetch.fetch_image_search("PICTURE", 2)
    assert body is None and len(earlier) == 1


def test_image_search_box_short_or_refused_is_blocked(image_box):
    image_box["answer"] = [sim_load(0)]                                 # has_more, yet page 2 never answered
    with pytest.raises(fetch.TemuBlocked):
        fetch.fetch_image_search("PICTURE", 2)
    image_box["answer"] = [sim_load(0, success=False)]
    with pytest.raises(fetch.TemuBlocked):
        fetch.fetch_image_search("PICTURE", 1)


def test_search_picture_is_temus_own_size(monkeypatch):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (256, 128), (255, 0, 0, 0)).save(buf, "PNG")       # small, transparent
    monkeypatch.setattr(fetch.pictures, "download", lambda link, user_agent=None, max_bytes=None: buf.getvalue())
    jpeg = fetch.base64.b64decode(fetch.search_picture("https://example.com/a.png"))
    im = Image.open(io.BytesIO(jpeg))
    assert im.format == "JPEG" and im.size == (500, 250)               # scaled UP to 500 px wide
    assert im.getpixel((10, 10))[0] > 240 and im.getpixel((10, 10))[1] > 240     # transparency -> white

    def refuse(link, user_agent=None, max_bytes=None):
        raise fetch.pictures.PictureError("image could not be used: its server answered HTTP 404")
    monkeypatch.setattr(fetch.pictures, "download", refuse)
    with pytest.raises(fetch.TemuBadRequest, match="HTTP 404"):
        fetch.search_picture("https://example.com/gone.png")
