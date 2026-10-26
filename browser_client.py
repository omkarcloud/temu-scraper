"""Earns Temu's trust on THIS machine and drives the pages only a browser can.

Temu server-renders its product, search and category pages only for a guest
it trusts. temu/fetch.py asks this module for such a guest (`mint()`): a real
Google Chrome (patchright, headed) opens the Temu home page, stays a few
seconds while Temu's own scripts run, then proves the guest is trusted with
one search. Its cookies and user agent are handed back, and from then on the
product, search and category pages are plain HTTP on the same connection
(TEMU_PROXY, or your own IP when it is unset).

Search / category pages after the first, product reviews and store reviews
only come from Temu's in-page calls, which carry a token Temu's scripts sign
in the page. For those, `ExitPool.fetch_any()` keeps one warm Chrome per
storefront, opens the page, clicks "See more" / "See all reviews" (or
scrolls the reviews dialog) and returns the raw JSON of those calls.
temu/fetch.py parses it.

Needs Google Chrome installed (patchright drives it). Temu refuses headless
Chrome, so a window opens. When Temu shows your IP its captcha, or the IP is
not in the storefront's country (US for `us`, UK for `gb`, Canada for `ca`),
set TEMU_PROXY to a STICKY proxy in that country.

Same interface as the hosted service's client for its browser servers:
mint(), ExitPool, impersonation_for() and the exception classes."""
import json
import random
import re
import threading
import time
from urllib.parse import urlencode

SITE = "https://www.temu.com"
# storefront -> (home page, Temu's region id in the `region` cookie)
MARKETS = {
    "": (SITE + "/", "211"),
    "us": (SITE + "/", "211"),
    "gb": (SITE + "/uk", "210"),
    "ca": (SITE + "/ca", "37"),
}
# Chrome's JS timezone when a proxy is set (the exit's country, not this machine's)
TIMEZONES = {"": "America/New_York", "us": "America/New_York", "gb": "Europe/London", "ca": "America/Toronto"}
CHALLENGE_PATHS = ("bgn_verification", "/login.html", "bgn_no_access")
DWELL_SECONDS = 12
VERIFY_QUERIES = ("phone case", "socks", "kitchen gadgets", "led lights", "storage box", "notebook",
                  "water bottle", "car accessories", "earrings", "yoga mat")
SEARCH_RESULTS_MARKER = '"hasSearchResults":true'
MORE_TEXT = "See more"
REVIEWS_TEXT = "See all reviews"
WAIT_FOR_CALL = 12          # seconds to wait for the call a click triggers
MAX_TIMES = 10
PAGE_USES = 6               # pages one kept Chrome serves before a fresh guest


class BoxUnavailable(Exception):
    """Chrome could not be started on this machine."""

    def __init__(self, message="", candidate=None):
        super().__init__(message)
        self.candidate = candidate
        self.proxy = None


class BoxRefused(Exception):
    """Temu did not trust the guest (captcha, wrong country, untrusted render)."""

    def __init__(self, message="", candidate=None):
        super().__init__(message)
        self.candidate = candidate
        self.proxy = None


def _market(variant):
    try:
        return MARKETS[variant or ""]
    except KeyError:
        raise BoxRefused(f"temu: unknown storefront {variant!r}; known: us, gb, ca")


def _rid(n=10):
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


def _where(proxy):
    return proxy.rsplit("@", 1)[-1] if proxy else "your own IP"


def _open_chrome(proxy, variant):
    try:
        from chrome_manager import create_scope
        from patchright_driver import PatchrightDriver
        with create_scope():
            # nothing blocked: Temu stops trusting a guest whose browser skips images
            return PatchrightDriver(proxy_url=proxy, headless=False,
                                    timezone=TIMEZONES.get(variant or "") if proxy else None)
    except Exception as e:
        raise BoxUnavailable(f"could not start Google Chrome: {type(e).__name__}: {e}")


def _goto(driver, url, referer, what):
    try:
        driver.call(lambda page: page.goto(url, referer=referer, wait_until="domcontentloaded", timeout=60_000))
    except Exception as e:
        raise BoxRefused(f"temu: the {what} did not load ({type(e).__name__}: {str(e)[:160]})")


def _challenged(url):
    return any(p in (url or "") for p in CHALLENGE_PATHS)


def _wiggle(page, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        page.mouse.move(random.randint(150, 1100), random.randint(150, 650), steps=random.randint(8, 25))
        page.wait_for_timeout(random.randint(350, 900))
        if random.random() < 0.35:
            page.mouse.wheel(0, random.choice([300, 500, -250]))


def _reject_cookie_banner(page):
    """The UK storefront shows a consent banner: decline non-essential cookies."""
    try:
        btn = page.get_by_text("Reject All", exact=True).first
        if btn.is_visible(timeout=800):
            btn.click(timeout=2000)
            page.wait_for_timeout(600)
    except Exception:
        pass


def _warm(driver, variant, proxy):
    """Home page + dwell + one server-rendered search. BoxRefused unless
    Temu trusts this guest in the storefront's country."""
    home, region = _market(variant)
    where = _where(proxy)
    _goto(driver, home, "https://www.google.com/", "home page")
    driver.call(lambda page: page.wait_for_timeout(6000))
    driver.call(lambda page: _wiggle(page, DWELL_SECONDS))
    jar = {c["name"]: c["value"] for c in driver.call(lambda page: page.context.cookies(SITE))}
    if _challenged(driver.current_url):
        raise BoxRefused(f"temu: Temu showed its captcha on {where}; set TEMU_PROXY to another (sticky) proxy")
    if "api_uid" not in jar:
        raise BoxRefused(f"temu: the home page loaded without a guest identity on {where}")
    if jar.get("region") != region:
        raise BoxRefused(f"temu: {where} is not in the {variant or 'us'} storefront's country for Temu "
                         f"(region {jar.get('region')!r}); set TEMU_PROXY to a proxy in that country")
    url = SITE + "/search_result.html?" + urlencode({
        "search_key": random.choice(VERIFY_QUERIES), "search_method": "shade", "refer_page_el_sn": "200010",
        "srch_enter_source": "top_search_entrance_10005", "refer_page_name": "home",
        "refer_page_id": f"10005_{int(time.time() * 1000)}_{_rid()}", "refer_page_sn": "10005",
        "_x_sessn_id": _rid()})
    _goto(driver, url, SITE + "/", "trust-check search")
    html = driver.call(lambda page: page.content()) or ""
    if _challenged(driver.current_url) or SEARCH_RESULTS_MARKER not in html:
        raise BoxRefused(f"temu: Temu does not trust this guest on {where}; set TEMU_PROXY to another (sticky) proxy")


def _close(driver):
    try:
        driver.close()
    except Exception:
        pass


# ---- identity -----------------------------------------------------------------------

_mint_lock = threading.Lock()


def mint(site="temu", proxy=None, variant=""):
    """A trusted guest for one storefront -> {cookies, user_agent, chrome_major, exit_ip}."""
    with _mint_lock:                                   # one Chrome launch at a time
        driver = _open_chrome(proxy, variant)
        print(f"temu: earning a trusted guest in Chrome ({_where(proxy)}, ~30 s)...")
        try:
            _warm(driver, variant, proxy)
            cookies = driver.call(lambda page: page.context.cookies(SITE))
            ua = driver.evaluate("navigator.userAgent")
        finally:
            _close(driver)
    major = re.search(r"Chrome/(\d+)", ua or "")
    return {"cookies": [{k: c[k] for k in ("name", "value", "domain", "path") if k in c} for c in cookies],
            "user_agent": ua, "chrome_major": int(major.group(1)) if major else None, "exit_ip": None}


def impersonation_for(ident, default="chrome"):
    """The curl_cffi impersonation matching the minting Chrome's major version."""
    major = ident.get("chrome_major")
    if not major:
        return default
    try:
        from curl_cffi import requests as curl
        known = {int(n[len("chrome"):]) for n in curl.BrowserType.__members__
                 if n.startswith("chrome") and n[len("chrome"):].isdigit()}
    except Exception:
        return default
    if major in known:
        return f"chrome{major}"
    lower = [n for n in known if n <= major]
    return f"chrome{max(lower)}" if lower else default


# ---- kept browsers for the in-page calls --------------------------------------------

def _attach(page, state, capture):
    def on_response(resp):
        if any(c in resp.url for c in capture):
            state["responses"].append(resp)
    state["handler"] = on_response
    page.on("response", on_response)


def _detach(page, state):
    try:
        page.remove_listener("response", state["handler"])
    except Exception:
        pass


def _read(state):
    out = []
    for resp in state["responses"]:
        try:
            body, err = resp.text(), None
        except Exception as e:
            body, err = None, f"{type(e).__name__}: {e}"
        try:
            post = resp.request.post_data
        except Exception:
            post = None
        out.append({"url": resp.url, "status": resp.status, "method": resp.request.method,
                    "post": post, "body": body, "error": err})
    return out


def _wait_more(page, state, before, seconds=WAIT_FOR_CALL):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if len(state["responses"]) > before:
            page.wait_for_timeout(800)
            return True
        page.wait_for_timeout(400)
    return False


def _wait_count(page, state, capture, seconds=WAIT_FOR_CALL):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if all(any(c in r.url for r in state["responses"]) for c in capture):
            page.wait_for_timeout(500)
            return True
        page.wait_for_timeout(400)
    return False


def _click_text(page, text, exact=True):
    loc = page.get_by_text(text, exact=exact)
    if not loc.count():
        return False
    el = loc.last if exact else loc.first
    el.scroll_into_view_if_needed(timeout=8000)
    page.wait_for_timeout(700)
    el.click(timeout=6000)
    return True


def _scroll_reviews_modal(page):
    """Scroll the reviews dialog to its end; it loads the next 10 on scroll."""
    return page.evaluate("""() => {
        const root = document.querySelector('[role=dialog], [aria-modal=true]') || document.body;
        const box = Array.from(root.querySelectorAll('*'))
          .filter(el => el.scrollHeight > el.clientHeight + 40 && ['auto', 'scroll'].includes(getComputedStyle(el).overflowY))
          .sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
        if (!box) return false;
        box.scrollTop = box.scrollHeight;
        return true;
    }""", isolated_context=False)


def _run_plan(driver, url, referer, spec):
    """Open `url`, run the action plan, return the captured calls."""
    capture = [c for c in (spec.get("capture") or []) if isinstance(c, str) and c]
    action = spec.get("action") or ""
    times = max(0, min(int(spec.get("times") or 0), MAX_TIMES))
    if not capture:
        raise BoxRefused("temu: nothing to capture")
    state = {"responses": []}
    driver.call(lambda page: _attach(page, state, capture))
    try:
        _goto(driver, url, referer, "page")
        driver.call(lambda page: page.wait_for_timeout(4000))
        if _challenged(driver.current_url):
            raise BoxRefused("temu: Temu challenged the page; the guest is burned")
        driver.call(_reject_cookie_banner)
        if action == "":
            driver.call(lambda page: _wait_count(page, state, capture))
        elif action == "reviews":
            before = len(state["responses"])
            if not driver.call(lambda page: _click_text(page, REVIEWS_TEXT, exact=False)):
                raise BoxRefused("temu: no 'See all reviews' control on the product page")
            driver.call(lambda page: _wait_more(page, state, before))
            for _ in range(max(0, times - 1)):
                before = len(state["responses"])
                driver.call(_scroll_reviews_modal)
                if not driver.call(lambda page: _wait_more(page, state, before)):
                    break
        elif action == "more":
            for _ in range(times):
                before = len(state["responses"])
                if not driver.call(lambda page: _click_text(page, MORE_TEXT)):
                    break
                if not driver.call(lambda page: _wait_more(page, state, before)):
                    break
        if _challenged(driver.current_url):
            raise BoxRefused("temu: Temu challenged the page; the guest is burned")
        return driver.call(lambda page: _read(state))
    finally:
        try:
            driver.call(lambda page: _detach(page, state))
        except Exception:
            pass


class ExitPool:
    """One kept, trusted Chrome per storefront (`key`) for the in-page calls.
    `mint` returns the proxy URL to use (None = your own IP)."""

    def __init__(self, site, mint, size=1):
        self.site = site
        self._mint = mint
        self._lock = threading.Lock()
        self._browsers = {}           # key -> {"driver", "proxy", "uses", "lock"}

    def _entry(self, key):
        with self._lock:
            return self._browsers.setdefault(key, {"driver": None, "proxy": None, "uses": 0,
                                                   "lock": threading.Lock()})

    def fetch_any(self, site, key="", url=None, method="GET", body=None, variant="", headers=None, **_):
        """Run the JSON action plan in `body` on `url` -> (proxy, {"status", "body"})."""
        entry = self._entry(key)
        with entry["lock"]:                           # one page at a time per Chrome
            if entry["driver"] is None or entry["uses"] >= PAGE_USES:
                if entry["driver"] is not None:
                    _close(entry["driver"])
                entry.update(driver=None, uses=0, proxy=self._mint())
                driver = _open_chrome(entry["proxy"], variant)
                try:
                    _warm(driver, variant, entry["proxy"])
                except BoxRefused as e:
                    _close(driver)
                    e.candidate, e.proxy = 0, entry["proxy"]
                    raise
                entry["driver"] = driver
            entry["uses"] += 1
            try:
                spec = json.loads(body) if isinstance(body, str) else (body or {})
                captured = _run_plan(entry["driver"], url, (headers or {}).get("referer") or SITE + "/", spec)
            except BoxRefused as e:
                self._drop(entry)
                e.candidate, e.proxy = 0, entry["proxy"]
                raise
            except Exception as e:
                self._drop(entry)
                raise BoxRefused(f"temu: the browser failed on the page ({type(e).__name__}: {e})", candidate=0)
            return entry["proxy"], {"status": 200, "body": json.dumps({"captured": captured})}

    def _drop(self, entry):
        if entry["driver"] is not None:
            _close(entry["driver"])
        entry.update(driver=None, uses=0)

    def rotate(self, proxy, key=""):
        """Close the burned Chrome; the next call opens a fresh guest."""
        entry = self._entry(key)
        with entry["lock"]:
            self._drop(entry)
        return True
