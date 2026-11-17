"""Temu parsers: raw HTML / JSON -> clean dicts. Pure functions, no I/O.

Where the data lives (www.temu.com, captured 2026-10-24 through a minted US
guest identity; fixtures in temu/fixtures/, each page's unused
window.__InitialI18nStore__ translation table emptied to {} on 2026-10-26):

  * product page   window.rawData.store on /goods.html?goods_id=<id> (with
                   the click-style query temu/fetch.py adds): goods, sku[],
                   formatSkuData, moduleMap.priceModule.data.skuTrackInfo
                   (per-variant list price + sold count), review, reviewStore
                   .commentList (first reviews), mall.mallData, delivery,
                   afterSale, activityInfo, crumbOptList, productDetail
                   fixtures product_sweater.html (50 variants, local warehouse),
                   product_earbuds.html (3 variants, video, rank, brand),
                   product_not_found.html (store.error errorCode 49001
                   GOODS_NOT_EXIST), product_refused.html (54001 captcha),
                   product_shell.html (client-side shell, no rawData),
                   product_unavailable_gb.html (sold-out page: a US product
                   the UK storefront does not sell, goods.status 7)
  * search page    window.rawData.store on /search_result.html: goodsList
                   (camelCase, wrapped in {data}; 20 cards since 2026-11,
                   40 before, while pageSize still says 40), totalPage,
                   goodsNumAdv, hasSearchResults, filtersStore, cardRecommendWords
                   fixtures search_desk_organizer.html (2026-11-07, 20 cards),
                   search_wireless_earbuds.html (2026-10-24, 40 cards),
                   search_no_results.html
  * search page N  POST /api/poppy/v1/search (captured by the browser box):
                   result.data.goods_list (snake_case cards), has_more; one
                   "See more" loads one page of what page 1 rendered (US 20,
                   UK 24 since 2026-11; 40 before)
                   fixture search_page2.json (2026-10-24, 40 cards)
  * category page  window.rawData.store on /<slug>-o3-<id>.html: goodsList,
                   crumbOptList, title, hasResult, categoryData (top level),
                   filtersStore.completeFilter (the "Category" facet = the
                   category's subcategories)
                   fixtures category_headphones.html (a leaf: no facet),
                   category_electronics_top_sales.html, category_unknown.html
  * category N     POST /api/poppy/v1/opt (browser box): same card shape
                   fixture category_page2.json
  * product reviews GET /api/bg/engels/reviews/list + /reviews/info (browser
                   box) fixtures reviews_list.json (page 1), reviews_list_page3.json,
                   reviews_info.json
  * store reviews  GET /api/bg/engels/reviews/mall/list + /mall/info (browser
                   box, the store page's Reviews tab)
                   fixtures store_reviews_list.json, store_reviews_info.json,
                   store_reviews_unknown_list.json / _info.json (unknown id)

Prices are integers in the currency's minor unit (USD / GBP / CAD cents).
"""
import json
import fastjson
import math
import re
from datetime import datetime, timezone

from temu.refs import SITE, absolute, category_link, product_link, store_link
from scraper_utils.values import num as _float, to_int as _int

_RAW_DATA_RE = re.compile(r"window\.rawData\s*=\s*")
_DOC_SOURCE_RE = re.compile(r'window\.__DOC_SOURCE__\s*=\s*"(\w+)"')
_CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_COUNT_RE = re.compile(r"([0-9][0-9,.]*)\s*([KkMm]?)")
_RANK_RE = re.compile(r"#\s*([0-9,]+)")

# store.error.errorCode values (temu/fetch.py classifies with these)
NOT_FOUND_CODES = {49001}                  # GOODS_NOT_EXIST
REFUSED_CODES = {54001, 40001, 40002, 40003}  # captcha / needLogin / refused / bad signature


# ---- page plumbing --------------------------------------------------------------------

def extract_store(html):
    """The server-rendered window.rawData.store dict, or None when the page is
    the client-side shell (no blob) or the blob does not decode."""
    if not html:
        return None
    m = _RAW_DATA_RE.search(html)
    if not m:
        return None
    try:
        raw, _ = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError:
        return None
    store = raw.get("store") if isinstance(raw, dict) else None
    return store if isinstance(store, dict) else None


def doc_source(html):
    """'ssr' (server-rendered) or 'csrPath' (Temu served the client-side
    shell: the identity is not trusted for this page), None if absent."""
    m = _DOC_SOURCE_RE.search(html or "")
    return m.group(1) if m else None


def page_error(store):
    """store.error as {code, message} or None."""
    err = (store or {}).get("error")
    if not isinstance(err, dict):
        return None
    return {"code": err.get("errorCode"), "message": err.get("message") or err.get("errorMsg")}


def canonical_link(html):
    m = _CANONICAL_RE.search(html or "")
    return m.group(1) if m else None


# ---- value helpers --------------------------------------------------------------------

def snake(obj):
    """camelCase keys -> snake_case, recursively (the server-rendered cards
    are camelCase, the signed API cards snake_case; one parser reads both)."""
    if isinstance(obj, dict):
        return {(_CAMEL_RE.sub("_", k).lower() if isinstance(k, str) else k): snake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [snake(v) for v in obj]
    return obj


def _dig(obj, *path, default=None):
    for key in path:
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int) and -len(obj) <= key < len(obj):
            obj = obj[key]
        else:
            return default
        if obj is None:
            return default
    return obj


def money(minor):
    """Minor units (cents) -> amount; None for missing / non-positive."""
    value = _int(minor)
    if value is None or value <= 0:
        return None
    return round(value / 100, 2)


def count_from_text(text):
    """'100K+' -> 100000, '6.1K+ sold' -> 6100, '1.2M+' -> 1200000,
    '20,104' -> 20104 (a lower bound when the site shows a '+')."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(text)
    m = _COUNT_RE.search(str(text))
    if not m:
        return None
    number, unit = m.group(1).replace(",", ""), m.group(2).lower()
    try:
        value = float(number)
    except ValueError:
        return None
    if unit == "k":
        value *= 1000
    elif unit == "m":
        value *= 1_000_000
    return int(round(value))


def discount_percent(price, list_price):
    if not price or not list_price or list_price <= price:
        return None
    return int(round((list_price - price) / list_price * 100))


def iso_date(epoch):
    """Epoch seconds or milliseconds -> 'YYYY-MM-DD' (UTC)."""
    value = _int(epoch)
    if not value or value <= 0:
        return None
    if value > 10_000_000_000:
        value //= 1000
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")


def iso_datetime(epoch):
    value = _int(epoch)
    if not value or value <= 0:
        return None
    if value > 10_000_000_000:
        value //= 1000
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rich_text(obj, sep=""):
    """Plain text of a Temu rich-text block ({textRich: [{type 0: value}]} or
    a list). `sep` joins the parts (tags are separate words: " ")."""
    if isinstance(obj, dict):
        obj = obj.get("textRich") or obj.get("text_rich") or []
    if not isinstance(obj, list):
        return None
    parts = [str(t.get("value") or t.get("text") or "") for t in obj
             if isinstance(t, dict) and t.get("type", 0) == 0]
    if sep:
        parts = [p.strip() for p in parts]
    text = " ".join(sep.join(p for p in parts if p).split())
    return text or None


def clean_product_link(path, goods_id=None):
    """A card's seo link without Temu's tracking query; falls back to the
    goods.html link."""
    link = absolute(path) if path else None
    if link and "-g-" in link:
        return link.split("?", 1)[0]
    return product_link(goods_id) if goods_id else link


def _label_name(text):
    """'Easy Assembly(15)' -> 'Easy Assembly'."""
    return re.sub(r"\s*\([0-9,]+\)\s*$", "", str(text or "")).strip() or None


def _specs(value):
    """Review specs (a JSON string or list of {spec_key, spec_value}) ->
    [{name, value}]; masked keys (Temu blanks some words) give name null."""
    if isinstance(value, str):
        try:
            value = fastjson.loads(value)
        except ValueError:
            return []
    out = []
    for spec in value or []:
        if not isinstance(spec, dict):
            continue
        name = spec.get("spec_key") or spec.get("specKey") or spec.get(" _key")
        val = spec.get("spec_value") or spec.get("specValue") or spec.get(" _value")
        name = name.strip() if isinstance(name, str) else None
        if val:
            out.append({"name": name or None, "value": str(val).strip()})
    return out


def _review_images(review):
    images = []
    for key in ("pictures", "review_pic_list", "pic_list", "list"):
        for pic in review.get(key) or []:
            if isinstance(pic, dict) and pic.get("url"):
                images.append({"link": pic["url"], "width": _int(pic.get("width")), "height": _int(pic.get("height"))})
    return images


def _review_videos(review):
    videos = []
    for key in ("video", "videos", "review_video_list"):
        items = review.get(key)
        items = items if isinstance(items, list) else [items] if isinstance(items, dict) else []
        for v in items:
            link = v.get("url") or v.get("video_url")
            if link:
                videos.append({"link": link, "thumbnail": v.get("cover_image_url") or v.get("cover_url")})
    return videos


def _country(rich):
    """'in United States on Oct 6, 2026' (the review's aria label) -> 'United States'."""
    label = (rich or {}).get("ariaLabel") or (rich or {}).get("aria_label") or ""
    m = re.match(r"\s*in\s+(.+?)\s+on\s+", label)
    return m.group(1).strip() if m else None


# ---- listing cards (search, category, both shapes) --------------------------------------

def _is_sponsored(card):
    tags = card.get("tags_info") or {}
    return bool(tags.get("ad_tags_sliding") or tags.get("ad_tags"))


def _card_tags(card):
    tags = []
    for tag in card.get("goods_tags") or []:
        if not isinstance(tag, dict):
            continue
        text = tag.get("text")
        if not text:
            raw = _dig(tag, "ext_map", "ranking_list_rich_text")
            if isinstance(raw, str):
                try:
                    text = rich_text(snake(fastjson.loads(raw)).get("text_rich"), sep=" ")
                except ValueError:
                    text = None
        if text and text not in tags:
            tags.append(text)
    return tags


def parse_card(raw):
    """One listing card (server-rendered camelCase {data: …} or signed-API
    snake_case) -> a product summary."""
    card = snake(raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw or {})
    goods_id = card.get("goods_id")
    if not goods_id:
        return None
    goods_id = str(goods_id)
    info = card.get("price_info") or {}
    price, list_price = money(info.get("price")), money(info.get("market_price"))
    comment = card.get("comment") or {}
    video = card.get("video") or {}
    return {
        "id": goods_id,
        "name": card.get("title") or None,
        "link": clean_product_link(card.get("seo_link_url"), goods_id),
        "image": _dig(card, "image", "url") or card.get("thumb_url") or None,
        "video": video.get("video_url") or None,
        "price": price,
        "list_price": list_price if list_price and price and list_price > price else None,
        "discount_percent": discount_percent(price, list_price),
        "currency": info.get("currency") or None,
        "sold_count": count_from_text(card.get("sales_num") or card.get("sales_tip")),
        "rating": _float(comment.get("goods_score")) or None,
        "review_count": _int(comment.get("comment_num_tips")),
        "store_id": str(card["mall_id"]) if card.get("mall_id") else None,
        "category_id": str(card["opt_id"]) if card.get("opt_id") else None,
        "tags": _card_tags(card),
        "is_sponsored": _is_sponsored(card),
    }


def parse_cards(items):
    return [c for c in (parse_card(i) for i in items or []) if c]


# ---- search ---------------------------------------------------------------------------

def search_is_empty(store):
    """True when the page is Temu's genuine "no results" page (it carries
    the contact block and hasSearchResults false) — as opposed to a refused
    render, which has neither results nor that block."""
    return bool(store) and store.get("hasSearchResults") is False and bool(store.get("contactInfo"))


def parse_search_page(store, page_size=None):
    """Page 1 of a search (server-rendered). A page is Temu's own page: the
    cards page 1 renders, which is also what each "See more" loads (US 20,
    UK 24 since 2026-11; 40 before), unless `page_size` says otherwise."""
    cards = parse_cards(store.get("goodsList"))
    size = page_size or len(cards)
    count_text = str(store.get("goodsNumAdv")) if store.get("goodsNumAdv") not in (None, 0, "0", "") else None
    # goodsNumAdv is exact below 1000 ("53") and "1000+" above. totalPage is
    # not the page count for small results (53 results: totalPage 1 with
    # hasMore true, 2026-10-24), so an exact count decides the pages.
    exact = int(count_text) if count_text and count_text.isdigit() else None
    if not cards:
        total_pages, exact = 0, 0
    elif exact is not None:
        total_pages = total_pages_for(exact, size)
    else:
        # "1000+": totalPage counts pages of the store's nominal pageSize (it
        # says 40 and totalPage 9 while 20 / 24 render per page, 2026-11-07),
        # so the listing's reach is totalPage x pageSize results
        nominal = _int(store.get("pageSize")) or size
        total = _int(store.get("totalPage"))
        total_pages = total_pages_for(total * nominal, size) if total else None
    return {
        "results": cards,
        "page_size": size or None,
        "total_pages": total_pages,
        "total_count": exact,
        "count_text": count_text,
        "has_next": bool(cards) and (total_pages > 1 if total_pages else bool(store.get("hasMore"))),
        "related_searches": related_searches(store),
    }


def related_searches(store):
    """The query-related suggestions Temu shows with the results
    (cardRecommendWords). recommendWords is the site-wide trending list,
    the same for every query, and is left out."""
    out = []
    for word in store.get("cardRecommendWords") or []:
        text = (word or {}).get("shadeWord") or (word or {}).get("recommend")
        if text and text not in out:
            out.append(text)
    return out


def parse_search_api(payload):
    """A captured POST /api/poppy/v1/search (or /api/poppy/v1/opt) body ->
    {results, has_next}."""
    result = (payload or {}).get("result") or {}
    data = result.get("data") or {}
    cards = parse_cards(data.get("goods_list"))
    return {"results": cards, "has_next": bool(result.get("has_more")) and bool(cards)}


# ---- category -------------------------------------------------------------------------

def category_path(crumbs):
    path = []
    for crumb in crumbs or []:
        opt_id = _int((crumb or {}).get("optId"))
        if not opt_id or opt_id <= 0:
            continue
        path.append({"id": str(opt_id), "name": crumb.get("optName") or crumb.get("title"),
                     "link": category_link(opt_id)})
    return path


def category_is_unknown(store):
    """An opt id Temu does not have renders an empty generic page: no
    breadcrumb, hasResult false, no goods."""
    return (not store.get("crumbOptList") and store.get("hasResult") is False
            and not store.get("goodsList"))


def parse_category_page(store, opt_id):
    path = category_path(store.get("crumbOptList"))
    current = path[-1] if path else {"id": str(opt_id), "name": store.get("title"), "link": category_link(opt_id)}
    cards = parse_cards(store.get("goodsList"))
    return {
        "category": {**current, "path": path},
        "results": cards,
        "page_size": len(cards) or None,       # Temu's own page (40), as for a search
        "has_next": bool(store.get("hasMore")) and bool(cards),
        "subcategories": parse_subcategories(store),
        "top_categories": parse_top_categories(store),
    }


def _category_entry(opt_id, name, image=None):
    return {"id": str(opt_id), "name": name or None, "link": category_link(opt_id), "image": image or None}


def parse_top_categories(store):
    """categoryData.categoryList on any server-rendered category page -> the
    top-level categories. Temu's 'Featured' row (id -13) only repeats other
    categories and is skipped."""
    out = []
    for node in _dig(store, "categoryData", "categoryList", default=[]) or []:
        opt_id = _int((node or {}).get("optId")) if isinstance(node, dict) else None
        if opt_id and opt_id > 0:
            out.append(_category_entry(opt_id, node.get("optName"), node.get("imageUrl")))
    return out


def parse_subcategories(store):
    """The page's "Category" filter (filtersStore.completeFilter group 101,
    options "101:<opt id>") -> the category's subcategories. Temu shows the
    facet only on categories that have children, so a leaf gets []. The
    facet carries no images (2026-10-24: Electronics lists 15 of the 16
    subcategories its in-page opt_list call returns)."""
    groups = _dig(store, "filtersStore", "completeFilter", "filterList", default=[]) or []
    out, seen = [], set()
    for group in groups:
        if not isinstance(group, dict) or str(group.get("identifier")) != "101":
            continue
        for option in group.get("filterList") or []:
            key = str((option or {}).get("filter") or "")
            opt_id = _int(key.partition(":")[2]) if key.startswith("101:") else None
            if opt_id and opt_id > 0 and opt_id not in seen:
                seen.add(opt_id)
                out.append(_category_entry(opt_id, option.get("name")))
    return out


# ---- product --------------------------------------------------------------------------

def product_state(store):
    """'ok' | 'not_found' | 'refused' | 'empty' for a product page store."""
    if not store:
        return "empty"
    if _dig(store, "goods", "goodsName"):
        return "ok"
    err = page_error(store)
    if err and (err["code"] in NOT_FOUND_CODES or err.get("message") == "GOODS_NOT_EXIST"):
        return "not_found"
    if err and err["code"] in REFUSED_CODES:
        return "refused"
    return "empty"


def _images(gallery):
    images, video = [], None
    for item in gallery or []:
        if not isinstance(item, dict):
            continue
        if item.get("url") and item.get("type", 1) == 1:
            images.append({"link": item["url"], "width": _int(item.get("width")), "height": _int(item.get("height"))})
        v = item.get("video") or {}
        if video is None and v.get("videoUrl"):
            video = {"link": v["videoUrl"], "thumbnail": v.get("url") or None,
                     "width": _int(v.get("width")), "height": _int(v.get("height"))}
    return images, video


def _variants(store):
    track = _dig(store, "moduleMap", "priceModule", "data", "skuTrackInfo", default={}) or {}
    out = []
    for sku in store.get("sku") or []:
        if not isinstance(sku, dict) or not sku.get("skuId"):
            continue
        t = track.get(str(sku["skuId"])) or {}
        price = money(sku.get("salePrice")) or money(t.get("sale_price"))
        list_price = money(t.get("normal_line_price"))
        sizes = []
        for hover in sku.get("sizeDescHoverLists") or []:
            for desc in (hover or {}).get("sizeDescList") or []:
                content = (desc or {}).get("content")
                if content:
                    sizes.append(((desc.get("name") or "").strip() + " " + content).strip())
        out.append({
            "id": str(sku["skuId"]),
            "options": [{"name": s.get("specKey"), "value": s.get("specValue")}
                        for s in sku.get("specs") or [] if isinstance(s, dict)],
            "price": price,
            "list_price": list_price if list_price and price and list_price > price else None,
            "discount_percent": discount_percent(price, list_price),
            "stock": _int(sku.get("stockQuantity")),
            "sold_count": _int(t.get("sold_quantity")),
            "max_order_quantity": _int(sku.get("limitQuantity")),
            "is_available": sku.get("isOnsale") == 1,
            "image": sku.get("thumbUrl") or sku.get("specShowImageUrl") or None,
            "size_details": sizes,
        })
    return out


def _options(store):
    out = []
    for group in _dig(store, "formatSkuData", "skuTypeValues", default=[]) or []:
        if isinstance(group, dict) and group.get("type"):
            out.append({"name": group["type"], "values": [v for v in group.get("values") or [] if v]})
    return out


def _shipping(store):
    delivery = store.get("delivery") or {}
    options = []
    for d in delivery.get("shippingDetail") or []:
        if not isinstance(d, dict):
            continue
        table = d.get("table") or {}
        cost = " ".join(
            "".join(str(part.get("text") or "") for part in (cell or {}).get("ladderContent") or [])
            for cell in table.get("costsValue") or []).strip()
        when = " ".join(str((c or {}).get("text") or "") for c in table.get("deliveryTimeValue") or []).strip()
        options.append({
            "name": d.get("name") or None,
            "summary": d.get("content") or None,
            "cost": cost or None,
            "delivery_time": when or None,
            "delivery_days_distribution": [
                {"days": t.get("name"), "share_percent": round(_int(t.get("percentage")) / 100, 1)}
                for t in d.get("timeDistributed") or [] if isinstance(t, dict) and _int(t.get("percentage")) is not None],
        })
    return {
        "title": delivery.get("title") or None,
        "is_local_warehouse": _dig(store, "goods", "isLocalGoods") == 1,
        "options": options,
    }


def _store_card(store):
    mall = _dig(store, "mall", "mallData", default={}) or _dig(store, "moduleMap", "mallModule", "data", "mallData", default={}) or {}
    mall_id = mall.get("mallId") or _dig(store, "goods", "mallId")
    if not mall_id:
        return None
    unit = lambda key: (mall.get(key) or [None])[0] if isinstance(mall.get(key), list) else None  # noqa: E731
    return {
        "id": str(mall_id),
        "name": mall.get("mallName") or None,
        "link": store_link(mall_id),
        "logo": mall.get("mallLogo") or None,
        "rating": _float(mall.get("mallStar")) or None,
        "review_count": _int(mall.get("reviewNumStr")),
        "items_count": _int(mall.get("goodsNumV2")) or count_from_text(unit("goodsNumUnit")),
        "sold_count": count_from_text(unit("goodsSalesNumUnit")),
        "follower_count": count_from_text(unit("followerNumUnit")),
        "badge": _dig(store, "moduleMap", "salesTipModule", "data", "mallTag", "text"),
    }


def _ranking(store):
    rank = _dig(store, "moduleMap", "bestSellerModule", "data", "rank", default={}) or {}
    parts = rank.get("textRich") or []
    text = "".join(str((p or {}).get("text") or "") for p in parts).strip()
    if not text:
        return None
    m = _RANK_RE.search(text)
    category = text.split(" in ", 1)[1].strip() if " in " in text else None
    return {"type": rank.get("rankingType") or None, "rank": _int(m.group(1)) if m else None,
            "category_id": str(rank["rankingOptId"]) if rank.get("rankingOptId") else None,
            "category_name": category}


def _brand(store):
    banner = _dig(store, "moduleMap", "brandCardModule", "data", "brandBanner", "brandName")
    text = rich_text(banner)
    if text and ":" in text:
        text = text.split(":", 1)[1].strip()
    return text or None


def _documents(store):
    files = _dig(store, "moduleMap", "productDetailExtensionModule", "data", "instruction",
                 "guideFileSplit", "guideFileList", default=[]) or []
    return [{"languages": f.get("langInPdf") or [], "link": f.get("url")} for f in files if isinstance(f, dict) and f.get("url")]


def _deal(store):
    act = store.get("activityInfo") or {}
    if not act.get("activityName"):
        return None
    return {"name": act["activityName"], "ends_at": iso_datetime(act.get("activityEndTime"))}


def _page_reviews(store):
    out = []
    for c in _dig(store, "reviewStore", "commentList", default=[]) or []:
        if not isinstance(c, dict):
            continue
        out.append({
            "id": str(c.get("reviewId")) if c.get("reviewId") else None,
            "rating": _int(c.get("score")),
            "text": c.get("comment") or None,
            "date": iso_date(c.get("time")),
            "author": c.get("name") or None,
            "author_country": _country(c.get("concatRichText")),
            "variant": _specs(c.get("specs")),
            "images": _review_images(snake(c)),
        })
    return out


def parse_product(store, goods_id, html=None):
    """A product page store (product_state == 'ok') -> the product record."""
    goods = store.get("goods") or {}
    review = _dig(store, "review", "reviewData", default={}) or {}
    variants = _variants(store)
    prices = [v["price"] for v in variants if v["price"]]
    price = min(prices) if prices else money(goods.get("minOnSalePrice"))
    max_price = max(prices) if prices else money(goods.get("maxOnSalePrice"))
    cheapest = next((v for v in variants if v["price"] == price), None)
    list_price = cheapest["list_price"] if cheapest else None
    images, video = _images(goods.get("gallery"))
    # A product the market does not sell (or discontinued) renders a sold-out
    # page: goodsName is the sold-out title ("Unavailable for purchase"), no
    # gallery, only a thumbnail (fixture product_unavailable_gb.html).
    sold_out_title = _dig(goods, "soldOutContent", "soldOutTitleContent")
    name = goods.get("goodsName") if goods.get("goodsName") != sold_out_title else None
    if not images and goods.get("hdThumbUrl"):
        images = [{"link": goods["hdThumbUrl"], "width": None, "height": None}]
    path = category_path(store.get("crumbOptList"))
    after = store.get("afterSale") or {}
    return {
        "id": str(goods.get("goodsId") or goods_id),
        "name": name or None,
        "link": canonical_link(html) or product_link(goods_id),
        "item_number": goods.get("itemId") or None,
        "brand": _brand(store),
        "is_available": goods.get("isOnsale") == 1 and goods.get("status", 1) == 1,
        "pricing": {
            "price": price,
            "max_price": max_price if max_price and max_price != price else None,
            "list_price": list_price,
            "discount_percent": discount_percent(price, list_price),
            "currency": _dig(store, "localInfo", "currency"),
        },
        "sold_count": _int(goods.get("soldQuantity")) or count_from_text(goods.get("sideSalesTip")),
        "rating": _float(review.get("goodsScore")) or None,
        "review_count": _int(review.get("reviewNum")),
        "category": ({**path[-1], "path": path} if path else None),
        "ranking": _ranking(store),
        "deal": _deal(store),
        "images": images,
        "video": video,
        "description_images": [{"link": i.get("url"), "width": _int(i.get("width")), "height": _int(i.get("height"))}
                               for i in store.get("productDetailFlatList") or [] if isinstance(i, dict) and i.get("url")],
        "attributes": [{"name": p.get("key"), "values": p.get("values") or []}
                       for p in goods.get("goodsProperty") or [] if isinstance(p, dict) and p.get("key")],
        "options": _options(store),
        "variants": variants,
        "variants_count": len(variants),
        "shipping": _shipping(store),
        "returns": {"summary": after.get("title") or None, "details": after.get("contents") or []} if after else None,
        "documents": _documents(store),
        "store": _store_card(store),
        "review_tags": [{"name": _label_name(l.get("text")), "count": _int(l.get("num"))}
                        for l in review.get("labels") or [] if isinstance(l, dict) and l.get("text")],
        "reviews": _page_reviews(store),
    }


# ---- product reviews (browser-box captures) ---------------------------------------------

def parse_review(item):
    r = snake(item or {})
    return {
        "id": str(r.get("review_id")) if r.get("review_id") else None,
        "rating": _int(r.get("score")),
        "text": r.get("comment") or None,
        "date": iso_date(r.get("time_ms") or r.get("time")),
        "author": r.get("name") or None,
        "author_country": _country(r.get("concat_rich_text")),
        "variant": _specs(r.get("specs")),
        "fit": _dig(r, "goods_specific_review_level_info", "text"),
        "images": _review_images(r),
        "videos": _review_videos(r),
    }


def parse_reviews_list(payload):
    """GET /api/bg/engels/reviews/list body -> {results, max_reviews}."""
    payload = payload or {}
    return {"results": [parse_review(i) for i in payload.get("data") or [] if isinstance(i, dict)],
            "max_reviews": _int(payload.get("max_list_size"))}


def parse_reviews_info(payload):
    """GET /api/bg/engels/reviews/info body -> the review summary."""
    info = payload or {}
    return {
        "review_count": _int(info.get("review_num")),
        "rating_breakdown": [{"stars": _int(s.get("score")), "percent": _float(s.get("percent"))}
                             for s in info.get("score_num_info_list") or [] if isinstance(s, dict)],
        "fit_breakdown": [{"fit": s.get("text"), "percent": _float(s.get("percent"))}
                          for s in info.get("cloth_fit_review_info_list") or [] if isinstance(s, dict)],
        "tags": [{"name": _label_name(l.get("text")), "count": _int(l.get("num"))}
                 for l in info.get("labels") or []
                 if isinstance(l, dict) and _label_name(l.get("text"))],
    }


# ---- store reviews (browser-box captures of the store page) --------------------------------

def parse_store_review(item):
    """One /api/bg/engels/reviews/mall/list item: a product review plus the
    reviewed product and Temu's English translation."""
    r = snake(item or {})
    goods = r.get("goods_info") or {}
    goods_id = goods.get("goods_id") or r.get("goods_id")
    return {
        **parse_review(item),
        "translated_text": _dig(r, "review_lang", "translate_comment") or None,
        "product": {
            "id": str(goods_id),
            "name": goods.get("goods_name") or None,
            "link": clean_product_link(goods.get("seo_link_url"), goods_id),
            "image": goods.get("thumb_url") or None,
        } if goods_id else None,
    }


def parse_store_reviews(listing):
    """GET /api/bg/engels/reviews/mall/list body -> reviews."""
    return [parse_store_review(i) for i in (listing or {}).get("data") or [] if isinstance(i, dict)]


def parse_store_reviews_info(info):
    """GET /api/bg/engels/reviews/mall/info body -> the store review summary."""
    info = info or {}
    summary = parse_reviews_info(info)
    return {
        "rating": _float(info.get("mall_star")) or None,
        "review_count": summary["review_count"],
        "rating_breakdown": summary["rating_breakdown"],
        "tags": summary["tags"],
    }


def total_pages_for(total, per_page):
    if not total or not per_page:
        return 0
    return int(math.ceil(total / per_page))
