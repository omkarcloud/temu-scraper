"""Temu transport: curl_cffi with a guest identity minted on the browser box
(recipes/temu.py), replayed on the SAME sticky exit; the browser box again
(recipes/temu_pages.py) for what only the page's own signed calls return.

Why (research + box/pod tests 2026-10-23/24):
  * Every catalogue JSON call (/api/poppy/*, /api/oak/*, /api/bg/engels/*)
    carries an `anti-content` header Temu's scripts compute in the page;
    curl without it is refused (40001 / 40003) whatever the cookies.
  * The PAGES are server-rendered (window.rawData) for a guest identity
    Temu trusts: product, search and category pages over plain curl_cffi,
    with the identity's cookies + UA on the exit it was minted on. Without
    an identity they are an empty client-side shell.
  * A product page needs the click-style query the site adds when a card
    is clicked (_oak_mp_inf = protobuf {2: goods id, 3: list id, 4: ms};
    unsigned, a random list id is accepted) plus refer_page_* /
    _x_sessn_id; a bare goods.html?goods_id= is refused (54001) even for a
    trusted identity. Searches use search_method=shade (the suggested-word
    entry): US guests' typed searches (search_method=user) are refused.
  * One identity serves about six product pages and six listing pages, then
    Temu answers it with its captcha (54001) for good; the budget follows the
    cookies, not the IP. Temu also falls back to the client shell when the
    same identity arrives on a NEW connection, so each identity keeps ONE
    keep-alive curl session for its whole life.

Identity model: identities are per THREAD (threading.local), one per market,
each owning its curl session — a curl handle is never shared across threads,
and an identity's requests stay on one connection. An identity is retired
after TEMU_PRODUCT_PAGES / TEMU_LISTING_PAGES pages of that kind, after
TEMU_IDENTITY_MAX_AGE, or on the first refusal; the next request on that
thread mints a new one on a fresh sticky exit. Mints are rate-limited
process-wide (TEMU_MINTS_PER_MINUTE) so a block storm cannot burn exits in a
loop. The pod never contacts Temu from its own IP for these pages (the
identity lives on its exit).

The browser-box pages (search / category page N > 1, product and store
reviews) go through browser_client.fetch("temu-pages") on sticky exits from an ExitPool
per market; a refusal rotates that exit.

Store reviews: the store page's own review calls in a box browser (first
page only: a guest gets Temu's sign-in modal on the store page). Temu's open
SEO review JSON (/api/seo/get_seo_mall_reviews) is not used: it masks words
in the review text ("No, los   ya" for "No, los necesito ya") and was
refused (40001) on every tier from the pod for minutes at a time
(2026-10-24).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TemuUpstreamError  transport failure / 5xx                       — retryable
  TemuBoxDown        browser box down / busy / mint budget spent   — fails at once
  TemuBlocked        captcha / refused / client shell              — retryable on a new identity
  TemuBadRequest     upstream 400                                  — never retried
  TemuNotFound       unknown product / category                    — never retried
"""
import base64
import json
import os
import random
import string
import sys
import threading
import time
from collections import deque
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
from browser_client import BoxRefused, BoxUnavailable
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from temu import parsers
from temu.refs import DEFAULT_MARKET, MARKETS, SITE, category_page_path

BOX_SITE = "temu"                 # recipes/temu.py   (identity mint)
PAGES_SITE = "temu-pages"         # recipes/temu_pages.py (signed calls in the page)
PAGE_TIMEOUT = 40                 # product pages 0.4-1.8 MB, search pages ~1.4 MB
JSON_TIMEOUT = 20
BOX_ATTEMPTS = 4                  # browser-box page calls: fresh exit per refusal (warm-ups meet
                                  # Temu's captcha on some exits, 2026-10-24)
LISTING_PAGE_SIZE = 40            # Temu's own search / category page size
REVIEWS_PAGE_SIZE = 10            # the reviews modal loads 10 per page

ACCEPT_HTML = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8")

SEARCH_CALL = "/api/poppy/v1/search?"      # not /search_suggest
CATEGORY_CALL = "/api/poppy/v1/opt?"       # not /opt_list
REVIEWS_LIST_CALL = "/api/bg/engels/reviews/list?"
REVIEWS_INFO_CALL = "/api/bg/engels/reviews/info?"
STORE_REVIEWS_LIST_CALL = "/api/bg/engels/reviews/mall/list?"
STORE_REVIEWS_INFO_CALL = "/api/bg/engels/reviews/mall/info?"


class TemuUpstreamError(UpstreamError):
    """Transport failure / 5xx — retryable."""


class TemuBoxDown(TemuUpstreamError):
    """The browser box is down / busy, or the mint budget is spent: fail at
    once (a retry would only wait on the box again)."""


class TemuBlocked(TemuUpstreamError, Blocked):
    """Temu's captcha, a refused render or the client-side shell —
    retryable on a fresh identity."""


class TemuBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class TemuNotFound(NotFound):
    """Unknown product / category — never retried."""


# ---- click-style ids ------------------------------------------------------------------

def _rid(n=10):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _varint(n):
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def oak_mp_inf(goods_id, list_id):
    """The click-tracking token the site puts on product links: protobuf
    {2: goods id, 3: list id, 4: unix ms}, base64. Not signed."""
    raw = (b"\x10" + _varint(int(goods_id)) + b"\x1a" + _varint(len(list_id)) + list_id.encode()
           + b"\x20" + _varint(int(time.time() * 1000)))
    return base64.b64encode(raw).decode()


class _Ids:
    """One visit's click-style ids (a home page id, a session id, a list id)."""

    def __init__(self):
        self.sessn = _rid()
        self.page_id = f"10005_{int(time.time() * 1000)}_{_rid()}"
        self.list_id = os.urandom(16).hex()

    def product_url(self, goods_id):
        return f"{SITE}/goods.html?goods_id={goods_id}&" + urlencode({
            "_oak_mp_inf": oak_mp_inf(goods_id, self.list_id), "refer_page_sn": "10005",
            "freesia_scene": "1", "_oak_freesia_scene": "1", "refer_page_el_sn": "200024",
            "refer_page_name": "home", "refer_page_id": self.page_id, "_x_sessn_id": self.sessn})

    def search_url(self, query, filter_items=""):
        params = {"search_key": query, "search_method": "shade", "refer_page_el_sn": "200010",
                  "srch_enter_source": "top_search_entrance_10005", "refer_page_name": "home",
                  "refer_page_id": self.page_id, "refer_page_sn": "10005", "_x_sessn_id": self.sessn}
        if filter_items:
            params["filter_items"] = filter_items
        return f"{SITE}/search_result.html?" + urlencode(params)

    @staticmethod
    def category_url(opt_id, filter_items=""):
        url = SITE + category_page_path(opt_id)
        return url + ("?" + urlencode({"filter_items": filter_items}) if filter_items else "")


# ---- identities ---------------------------------------------------------------------

class _Identity:
    def __init__(self, market, proxy, box_ident):
        from curl_cffi import requests as curl_requests
        self.market = market
        self.proxy = proxy
        self.user_agent = box_ident.get("user_agent")
        self.exit_ip = box_ident.get("exit_ip")
        self.minted_at = time.monotonic()
        self.uses = {"product": 0, "listing": 0}
        self.dead = False
        self.ids = _Ids()
        self.session = curl_requests.Session(impersonate=browser_client.impersonation_for(box_ident))
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        for c in box_ident.get("cookies") or []:
            if c.get("name"):
                self.session.cookies.set(c["name"], c.get("value", ""), domain=c.get("domain") or ".temu.com",
                                         path=c.get("path") or "/")

    def spent(self, kind):
        limit = config.TEMU_PRODUCT_PAGES if kind == "product" else config.TEMU_LISTING_PAGES
        return (self.dead or self.uses[kind] >= limit
                or time.monotonic() - self.minted_at > config.TEMU_IDENTITY_MAX_AGE)

    def retire(self):
        self.dead = True
        try:
            self.session.close()
        except Exception:
            pass


_local = threading.local()
_mint_lock = threading.Lock()
_mint_times = deque()


def _charge_mint_budget():
    with _mint_lock:
        now = time.monotonic()
        while _mint_times and _mint_times[0] < now - 60:
            _mint_times.popleft()
        if len(_mint_times) >= config.TEMU_MINTS_PER_MINUTE:
            raise TemuBoxDown(f"identity mint budget spent ({config.TEMU_MINTS_PER_MINUTE}/min); retry shortly")
        _mint_times.append(now)


def _mint(market):
    """A trusted guest identity for `market` on a fresh sticky exit (the box
    verifies trust before answering); TEMU_MINT_ATTEMPTS exits."""
    last = None
    for attempt in range(1, config.TEMU_MINT_ATTEMPTS + 1):
        # None = this machine's own IP, valid only where the browser runs on
        # the same machine as this code (the open-source kit); GKE always
        # sends a sticky exit (config.TEMU_EXIT), since the box's IP is not
        # the pod's
        proxy = config.temu_proxy(market)
        _charge_mint_budget()
        try:
            ident = browser_client.mint(BOX_SITE, proxy=proxy, variant=market)
        except BoxUnavailable as e:
            raise TemuBoxDown(f"browser box unavailable for the identity mint: {e}")
        except BoxRefused as e:
            last = e
            continue
        if not ident.get("cookies") or not ident.get("user_agent"):
            last = RuntimeError("the box answered without cookies / user agent")
            continue
        return _Identity(market, proxy, ident)
    raise TemuBlocked(f"no trusted identity after {config.TEMU_MINT_ATTEMPTS} exits (last: {last})")


def _identity(market, kind):
    store = getattr(_local, "identities", None)
    if store is None:
        store = _local.identities = {}
    ident = store.get(market)
    if ident is None or ident.spent(kind):
        if ident is not None:
            ident.retire()
        ident = store[market] = _mint(market)
    return ident


def _drop_identity(market):
    store = getattr(_local, "identities", None) or {}
    ident = store.pop(market, None)
    if ident is not None:
        ident.retire()


def _headers(ident, accept, referer):
    return {"user-agent": ident.user_agent, "accept": accept,
            "accept-language": MARKETS[ident.market]["language"], "referer": referer,
            "upgrade-insecure-requests": "1"}


def _get_page(market, kind, build_url, referer=SITE + "/"):
    """GET one server-rendered page through this thread's identity ->
    (html, store). build_url(ids) makes the URL with the identity's ids."""
    ident = _identity(market, kind)
    ident.uses[kind] += 1
    url = build_url(ident.ids)
    try:
        resp = ident.session.get(url, headers=_headers(ident, ACCEPT_HTML, referer), timeout=PAGE_TIMEOUT)
    except Exception as e:
        _drop_identity(market)
        raise TemuUpstreamError(f"request failed: {type(e).__name__}: {e}")
    if resp.status_code in (403, 429):
        _drop_identity(market)
        raise TemuBlocked(f"HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise TemuNotFound("page not found")
    if resp.status_code == 400:
        raise TemuBadRequest(resp.text[:200])
    if resp.status_code != 200:
        raise TemuUpstreamError(f"HTTP {resp.status_code}")
    html = resp.text or ""
    if any(p in str(resp.url) for p in ("bgn_verification", "/login.html")):
        _drop_identity(market)
        raise TemuBlocked("Temu redirected the identity to its captcha / login page")
    return html, parsers.extract_store(html)


def _retrying(fn):
    """config.MAX_RETRIES attempts. A block already dropped the identity, so
    the retry mints a new one on a fresh exit at once; transport errors back
    off. NotFound / BadRequest / BoxDown surface immediately."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except TemuBoxDown:
            raise
        except TemuBlocked as e:
            last = e
        except TemuUpstreamError as e:
            last = e
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


# ---- server-rendered pages ----------------------------------------------------------

def fetch_product(goods_id, market=DEFAULT_MARKET):
    """The product page -> (store, html). 49001 -> TemuNotFound."""
    def once():
        html, store = _get_page(market, "product", lambda ids: ids.product_url(goods_id))
        state = parsers.product_state(store)
        if state == "ok":
            return store, html
        if state == "not_found":
            raise TemuNotFound(f"product {goods_id} not found")
        _drop_identity(market)
        if state == "refused":
            raise TemuBlocked(f"Temu refused the product page ({(parsers.page_error(store) or {}).get('code')})")
        raise TemuBlocked(f"Temu served the client-side shell ({parsers.doc_source(html) or 'no data'})")
    return _retrying(once)


def fetch_search(query, filter_items="", market=DEFAULT_MARKET):
    """Search page 1 (server-rendered) -> store."""
    def once():
        html, store = _get_page(market, "listing", lambda ids: ids.search_url(query, filter_items))
        if store and (store.get("goodsList") or parsers.search_is_empty(store)):
            return store
        _drop_identity(market)
        raise TemuBlocked(f"Temu did not render the search ({parsers.doc_source(html) or 'no data'})")
    return _retrying(once)


def fetch_category(opt_id, filter_items="", market=DEFAULT_MARKET):
    """Category page 1 (server-rendered) -> store."""
    def once():
        html, store = _get_page(market, "listing", lambda ids: ids.category_url(opt_id, filter_items))
        if store and store.get("goodsList"):
            return store
        if store and parsers.category_is_unknown(store):
            raise TemuNotFound(f"category {opt_id} not found")
        if store and store.get("crumbOptList") and store.get("hasResult") is False:
            return store       # a real category with nothing in it (or nothing left after the filters)
        _drop_identity(market)
        raise TemuBlocked(f"Temu did not render the category ({parsers.doc_source(html) or 'no data'})")
    return _retrying(once)


# ---- browser-box pages ----------------------------------------------------------------

_exit_pools = {}
_exit_pools_lock = threading.Lock()


def _pool(market):
    with _exit_pools_lock:
        pool = _exit_pools.get(market)
        if pool is None:
            pool = _exit_pools[market] = browser_client.ExitPool(
                PAGES_SITE, lambda m=market: config.temu_proxy(m), size=lambda: config.TEMU_PAGES_SESSIONS)
        return pool


def _box_capture(url, market, capture, action, times):
    """Navigate `url` in a trusted box browser, run the action plan and
    return the captured responses [{url, status, method, post, body}]."""
    pool = _pool(market)
    plan = json.dumps({"capture": capture, "action": action, "times": times})
    last = None
    for _ in range(BOX_ATTEMPTS):
        try:
            # every exit of the market is offered; the box hands over a free browser
            _, out = pool.fetch_any(PAGES_SITE, market, url=url, method="GET", body=plan,
                                    variant=market, headers={"referer": SITE + "/"})
        except BoxUnavailable as e:
            raise TemuBoxDown(f"browser box unavailable: {e}")
        except BoxRefused as e:
            last = e
            if e.candidate is not None:
                pool.rotate(e.proxy, market)
            continue
        try:
            return json.loads(out.get("body") or "{}").get("captured") or []
        except ValueError:
            raise TemuUpstreamError("browser box answered a non-JSON capture")
    raise TemuBlocked(f"the browser box could not load the page on {BOX_ATTEMPTS} exits (last: {last})")


def _json_body(item):
    if not item or item.get("status") != 200 or not item.get("body"):
        return None
    try:
        return json.loads(item["body"])
    except ValueError:
        return None


def _post_offset(item):
    try:
        return int(json.loads(item.get("post") or "{}").get("offset", -1))
    except (ValueError, TypeError, AttributeError):
        return -1


def fetch_listing_page(kind, ref, page, filter_items="", market=DEFAULT_MARKET):
    """Search (kind "search", ref = query) or category (kind "category",
    ref = opt id) page N > 1: the browser box clicks "See more" N-1 times ->
    (the JSON body of Temu's own call for offset (N-1)*40 or None when the
    listing ended before that page, the bodies of the pages the box loaded
    on the way)."""
    ids = _Ids()
    url = ids.search_url(ref, filter_items) if kind == "search" else ids.category_url(ref, filter_items)
    call = SEARCH_CALL if kind == "search" else CATEGORY_CALL
    captured = _box_capture(url, market, [call], "more", page - 1)
    want = (page - 1) * LISTING_PAGE_SIZE
    body, earlier = None, []
    for item in captured:
        if call not in item.get("url", ""):
            continue
        offset = _post_offset(item)
        if offset == want and body is None:
            body = _json_body(item)
            if body is None or body.get("success") is False:
                raise TemuBlocked(f"Temu refused the page-{page} call ({(body or {}).get('error_code')})")
        elif 0 < offset < want:
            earlier.append(_json_body(item) or {})
    return body, earlier


def fetch_reviews(goods_id, page, market=DEFAULT_MARKET):
    """Product reviews page N: the browser box opens the product page,
    clicks "See all reviews" and scrolls the modal N-1 times ->
    (list body for page N or None, info body or None)."""
    ids = _Ids()
    captured = _box_capture(ids.product_url(goods_id), market, [REVIEWS_LIST_CALL, REVIEWS_INFO_CALL],
                            "reviews", page)
    listing = info = None
    for item in captured:
        link = item.get("url", "")
        if REVIEWS_INFO_CALL in link and info is None:
            info = _json_body(item)
        if REVIEWS_LIST_CALL in link:
            qs = parse_qs(urlparse(link).query)
            if (qs.get("page") or ["0"])[0] == str(page):
                listing = _json_body(item)
    return listing, info


def fetch_store_reviews(mall_id, market=DEFAULT_MARKET):
    """The store's Reviews tab in a box browser -> (list body or None, info
    body or None): the first 10 reviews and the store's review summary."""
    url = f"{SITE}/mall.html?" + urlencode({"mall_id": mall_id, "tag_code": "Reviews", "sticky_type": "2"})
    captured = _box_capture(url, market, [STORE_REVIEWS_LIST_CALL, STORE_REVIEWS_INFO_CALL], "", 0)
    listing = info = None
    for item in captured:
        link = item.get("url", "")
        if STORE_REVIEWS_LIST_CALL in link and listing is None:
            listing = _json_body(item)
        elif STORE_REVIEWS_INFO_CALL in link and info is None:
            info = _json_body(item)
    return listing, info

