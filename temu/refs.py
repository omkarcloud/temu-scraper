"""Reference resolvers, markets and the search vocabulary for /temu/*.

ONE param per input (tofler RefField convention, never a sibling url/id
pair): `product` accepts a goods id OR any temu.com product link, `category`
an opt id OR a category link, `store` a mall id OR a store link. Resolvers
raise ValueError with a user-facing message (RefField turns it into a 400).

Identifier shapes (www.temu.com, 2026-10-24):
  * product   15-digit goods id; links /<slug>-g-<id>.html,
              /goods.html?goods_id=<id>, any market prefix (/uk/..., /ca/...)
  * category  opt id (1-8 digits); links /<slug>-o3-<id>.html (also -o1- /
              -o2-), /category.html?opt_id=<id>
  * store     15-digit mall id; links /<slug>-m-<id>.html,
              /mall.html?mall_id=<id>
Share links (share.temu.com/..., temu.to/...) are redirects to an app
landing page, not the record; they are refused with a hint.

Markets = Temu storefronts a guest identity is minted for. The storefront is
chosen by the identity's exit country (Temu's `region` cookie), not by the
URL, so every market uses the same www.temu.com URLs.
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://www.temu.com"

# market -> storefront facts (region id = Temu's own `region` cookie value)
MARKETS = {
    "us": {"name": "United States", "region": "211", "currency": "USD", "language": "en-US,en;q=0.9"},
    "gb": {"name": "United Kingdom", "region": "210", "currency": "GBP", "language": "en-GB,en;q=0.9"},
    "ca": {"name": "Canada", "region": "37", "currency": "CAD", "language": "en-CA,en;q=0.9"},
}
DEFAULT_MARKET = "us"

# Search / category sort orders: our public name -> Temu's filter_items token
# (search_result.html filtersStore.sortList, 2026-10-24).
SORTS = {
    "relevance": "0:1",
    "top_sales": "1:1",
    "newest": "3:1",
    "price_low_to_high": "2:0",
    "price_high_to_low": "2:1",
}
# Minimum average rating filter ("Customer reviews" group, identifier 300).
MIN_RATINGS = {"4": "300:4", "3": "300:3", "2": "300:2", "1": "300:1"}

_GOODS_ID_RE = re.compile(r"^[0-9]{12,20}$")
# Store ids are 10-15 digits (2026-10-26, 545 search cards: 15 x413, 13 x75,
# 11 x35, 12 x21, 10 x1; older stores have the short ones).
_MALL_ID_RE = re.compile(r"^[0-9]{6,20}$")
_OPT_ID_RE = re.compile(r"^[0-9]{1,9}$")
_LINK_GOODS_RE = re.compile(r"-g-([0-9]{12,20})\.html")
_LINK_MALL_RE = re.compile(r"-m-([0-9]{6,20})\.html")
_LINK_OPT_RE = re.compile(r"-o[123]-([0-9]{1,9})\.html")
_SHARE_HOSTS = ("share.temu.com", "temu.to")


def _as_url(value):
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("http://", "https://")):
        return value
    if value.lower().startswith(("www.temu.com", "temu.com", "share.temu.com", "temu.to")):
        return "https://" + value
    return None


def _host(url):
    return (urlparse(url).hostname or "").lower()


def _is_temu(url):
    host = _host(url)
    return host == "temu.com" or host.endswith(".temu.com") or host == "temu.to"


def _check_temu_link(url, kind):
    if not _is_temu(url):
        raise ValueError("Must be a temu.com link.")
    if _host(url) in _SHARE_HOSTS:
        raise ValueError(f"Share links are app redirects; open it in a browser and paste the {kind} link "
                         f"from the address bar instead.")


def _query_id(url, name):
    values = parse_qs(urlparse(url).query).get(name) or []
    return values[0].strip() if values else ""


def resolve_product(value):
    """Bare goods id or a temu.com product link -> the goods id."""
    value = (value or "").strip()
    if _GOODS_ID_RE.match(value):
        return value
    url = _as_url(value)
    if url:
        _check_temu_link(url, "product")
        goods_id = _query_id(url, "goods_id")
        if _GOODS_ID_RE.match(goods_id):
            return goods_id
        match = _LINK_GOODS_RE.search(urlparse(url).path)
        if match:
            return match.group(1)
        raise ValueError("Must be a temu.com product link (https://www.temu.com/<name>-g-<goods id>.html).")
    raise ValueError("Must be a Temu goods id (15 digits, e.g. 601099513224343) or a temu.com product link.")


def resolve_category(value):
    """Bare opt id or a temu.com category link -> the opt id."""
    value = (value or "").strip()
    if _OPT_ID_RE.match(value):
        return value.lstrip("0") or "0"
    url = _as_url(value)
    if url:
        _check_temu_link(url, "category")
        opt_id = _query_id(url, "opt_id")
        if _OPT_ID_RE.match(opt_id):
            return opt_id
        match = _LINK_OPT_RE.search(urlparse(url).path)
        if match:
            return match.group(1)
        raise ValueError("Must be a temu.com category link (https://www.temu.com/<name>-o3-<category id>.html).")
    raise ValueError("Must be a Temu category id (e.g. 248) or a temu.com category link.")


def resolve_store(value):
    """Bare mall id or a temu.com store link -> the mall id."""
    value = (value or "").strip()
    if _MALL_ID_RE.match(value):
        return value
    url = _as_url(value)
    if url:
        _check_temu_link(url, "store")
        mall_id = _query_id(url, "mall_id")
        if _MALL_ID_RE.match(mall_id):
            return mall_id
        match = _LINK_MALL_RE.search(urlparse(url).path)
        if match:
            return match.group(1)
        raise ValueError("Must be a temu.com store link (https://www.temu.com/mall.html?mall_id=<store id>).")
    raise ValueError("Must be a Temu store id (digits, e.g. 634418229064892) or a temu.com store link.")


# ---- links ------------------------------------------------------------------------

def absolute(path):
    """A site-relative path ("/x-g-1.html", "goods.html?goods_id=1") -> an absolute link."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith(("http://", "https://")):
        return path
    if path.startswith("//"):
        return "https:" + path
    return SITE + "/" + path.lstrip("/")


def product_link(goods_id):
    return f"{SITE}/goods.html?goods_id={goods_id}"


def category_link(opt_id):
    return f"{SITE}/category.html?opt_id={opt_id}"


def store_link(mall_id):
    return f"{SITE}/mall.html?mall_id={mall_id}"


def category_page_path(opt_id):
    """The category listing page: the slug part is optional for Temu."""
    return f"/category-o3-{opt_id}.html"


def filter_items(sort=None, min_price=None, max_price=None, min_rating=None, category=None,
                 local_warehouse=False):
    """Temu's `filter_items` value: `<group>:<value>` tokens joined by '|'
    (the site's own filtersStore joins them that way; ';' is silently
    ignored, 2026-10-24). Group ids from search_result.html
    filtersStore.completeFilter: sort 0-3, 101 category, 104 price
    "min,max" (-1 = open), 300 minimum stars, 400 ships from a local
    warehouse."""
    tokens = []
    if sort and sort in SORTS and sort != "relevance":
        tokens.append(SORTS[sort])
    if category:
        tokens.append(f"101:{category}")
    if min_price is not None or max_price is not None:
        tokens.append(f"104:{_price(min_price)},{_price(max_price)}")
    if min_rating:
        tokens.append(MIN_RATINGS[str(min_rating)])
    if local_warehouse:
        tokens.append("400:1")
    return "|".join(tokens)


def _price(value):
    if value is None:
        return "-1"
    value = float(value)
    return str(int(value)) if value == int(value) else f"{value:.2f}"
