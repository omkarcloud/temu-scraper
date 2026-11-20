"""The /temu/* endpoint functions (route_glue's route_table calls them with
the schema's loaded kwargs). Caching happens here (tofler/api.py pattern):

  * the product record is cached once per (product, country) and reused by
    products/details and products/reviews (its review summary + store id),
    so a client asking for both pays one product page;
  * listing page 1 (server-rendered: results + total pages + related
    searches) is cached on its own key, so page N > 1 (browser box) can
    report the listing's total pages without fetching page 1 again;
  * each endpoint caches its full response under its own namespace.
"""
from cache import DontCache, cached_call
from temu import cache_config as ttl
from temu import fetch, parsers
from temu.fetch import IMAGE_PAGE_SIZE, REVIEWS_PAGE_SIZE, page_size
from temu.refs import category_link, filter_items, store_link
from temu.schemas import MAX_CATEGORY_PAGE, MAX_IMAGE_SEARCH_PAGE, MAX_REVIEWS_PAGE, MAX_SEARCH_PAGE

MAX_PAGE = {"search": MAX_SEARCH_PAGE, "category": MAX_CATEGORY_PAGE}

# ---- shared product record ------------------------------------------------------------

def _product_record(product, country):
    store, html = fetch.fetch_product(product, country)
    return parsers.parse_product(store, product, html)


def _product(product, country):
    return cached_call("temu.product", {"product": product, "country": country}, _product_record,
                       ttl.PRODUCT_CACHE)


def product_details(product, country):
    """Everything the product page shows: prices per variant (list price,
    stock, sold count), options, attributes, images / video / description
    images, shipping options, returns, deal timer, ranking, store card,
    rating with review tags and the first reviews."""
    return {**_product(product, country), "country": country}


# ---- listings ---------------------------------------------------------------------------

def _filters(sort, min_price, max_price, min_rating, local_warehouse, category=None):
    return filter_items(sort=sort, min_price=min_price, max_price=max_price, min_rating=min_rating,
                        category=category, local_warehouse=local_warehouse)


def _search_first_page(query, filters, country):
    return parsers.parse_search_page(fetch.fetch_search(query, filters, country))


def _category_first_page(category, filters, country):
    return parsers.parse_category_page(fetch.fetch_category(category, filters, country), category)


def _first_page(kind, ref, filters, country):
    if kind == "search":
        # .v3: pages are Temu's own page (US 20, UK 24) since 2026-11-07
        return cached_call("temu.search_page1.v3", {"query": ref, "filters": filters, "country": country},
                           _search_first_page, ttl.SEARCH_CACHE)
    return cached_call("temu.category_page1", {"category": ref, "filters": filters, "country": country},
                       _category_first_page, ttl.CATEGORY_PRODUCTS_CACHE)


def _listing(kind, ref, filters, country, page):
    """{results, has_next, total_pages, extras} for page `page`."""
    first = _first_page(kind, ref, filters, country)
    total_pages = first.get("total_pages") if kind == "search" else None
    if page == 1:
        return first["results"], first["has_next"], total_pages, first
    if not first["results"] or not first["has_next"] or (total_pages and page > total_pages):
        return [], False, total_pages, first           # past the end: an empty page, not an error
    body, earlier = fetch.fetch_listing_page(kind, ref, page, filters, country)
    if body is None:
        return [], False, total_pages, first
    parsed = parsers.parse_search_api(body)
    # Page 1 came from a curl identity and the box browser ranks its own
    # session a little differently, so a few cards repeat across pages
    # (4 of 27 on a 2026-10-24 search page 2): drop what an earlier page had.
    seen = {card["id"] for card in first["results"]}
    for earlier_body in earlier:
        seen.update(card["id"] for card in parsers.parse_search_api(earlier_body)["results"])
    results = [card for card in parsed["results"] if card["id"] not in seen]
    has_next = parsed["has_next"] and (not total_pages or page < total_pages)
    return results, has_next, total_pages, first


def _pagination(kind, first, page, has_next, total_pages, total_count=None):
    # A search below 1000 results has an exact count (and so its pages);
    # above it Temu shows "1000+" with a page count and no total, and a
    # category shows neither: total_count stays null and has_next drives the
    # link. Either way the link stops at the last page the `page` param accepts.
    # A page is Temu's own page, measured on page 1 (US search 20, UK 24,
    # category 40).
    per_page = first.get("page_size") or page_size(kind)
    max_page = MAX_PAGE[kind]
    total_pages = min(total_pages, max_page) if total_pages else total_pages
    if total_count is not None:
        return {"page": page, "items_per_page": per_page, "total_pages": total_pages, "total_count": total_count}
    return {"page": page, "items_per_page": per_page, "has_next": has_next and page < max_page,
            "total_pages": total_pages, "total_count": None}


def _search(query, category, sort, min_price, max_price, min_rating, local_warehouse, country, page):
    filters = _filters(sort, min_price, max_price, min_rating, local_warehouse, category)
    results, has_next, total_pages, first = _listing("search", query, filters, country, page)
    return {
        "query": query,
        "country": country,
        "results_count_text": first.get("count_text"),
        "related_searches": first.get("related_searches") or [],
        "results": results,
        "pagination": _pagination("search", first, page, has_next, total_pages, first.get("total_count")),
    }


def products_search(**data):
    # .v3: pages are Temu's own page since 2026-11-07 (page 2 under the old maths was empty)
    return cached_call("temu.search.v3", data, _search, ttl.SEARCH_CACHE)


def _category_products(category, sort, min_price, max_price, min_rating, local_warehouse, country, page):
    filters = _filters(sort, min_price, max_price, min_rating, local_warehouse)
    results, has_next, _, first = _listing("category", category, filters, country, page)
    return {
        "category": first.get("category") or {"id": category, "name": None, "link": category_link(category), "path": []},
        "country": country,
        "results": results,
        "pagination": _pagination("category", first, page, has_next, None),
    }


def categories_products(**data):
    return cached_call("temu.category_products", data, _category_products, ttl.CATEGORY_PRODUCTS_CACHE)


# ---- search by image ----------------------------------------------------------------------

def _search_by_image(image, country, page):
    """Products that look like the picture (Temu's "Find similar" list):
    the picture is downloaded and re-encoded here, the box has Temu's page
    post the search (temu/fetch.py). Page N drops what pages 1..N-1 of the
    same box visit already showed."""
    body, earlier = fetch.fetch_image_search(fetch.search_picture(image), page, country)
    results, has_next = [], False
    if body is not None:
        parsed = parsers.parse_search_api(body)
        seen = set()
        for earlier_body in earlier:
            seen.update(card["id"] for card in parsers.parse_search_api(earlier_body)["results"])
        results = [card for card in parsed["results"] if card["id"] not in seen]
        has_next = parsed["has_next"] and page < MAX_IMAGE_SEARCH_PAGE
    out = {
        "image": image,
        "country": country,
        "results": results,
        "pagination": {"page": page, "items_per_page": IMAGE_PAGE_SIZE, "has_next": has_next,
                       "total_pages": None, "total_count": None},
    }
    # an empty first page may be a transient refusal Temu answers as "nothing
    # found": not kept for the cache's hour
    return DontCache(out) if page == 1 and not results else out


def products_search_by_image(**data):
    return cached_call("temu.search_by_image", data, _search_by_image, ttl.IMAGE_SEARCH_CACHE)


# ---- categories ---------------------------------------------------------------------------

# Any category page carries the top-level list; Electronics is a stable one.
TOP_LEVEL_SOURCE = "248"


def _categories_list(category, country):
    """Both forms read the unfiltered category page 1 that categories/products
    caches (no extra page for a client that asks for both)."""
    if not category:
        top = _first_page("category", TOP_LEVEL_SOURCE, "", country)["top_categories"]
        return {"parent": None, "country": country, "count": len(top), "categories": top}
    first = _first_page("category", category, "", country)
    subs = first["subcategories"]
    return {"parent": first["category"], "country": country, "count": len(subs), "categories": subs}


def categories_list(**data):
    return cached_call("temu.categories", data, _categories_list, ttl.CATEGORY_TREE_CACHE)


# ---- product reviews ------------------------------------------------------------------------

def _product_reviews(product, country, page):
    record = _product(product, country)
    if not record.get("review_count"):
        # a product without reviews has no "See all reviews" control, so the
        # box could only refuse (burning an exit per attempt): an empty page
        listing, info = None, None
    else:
        listing, info = fetch.fetch_reviews(product, page, country)
    parsed = parsers.parse_reviews_list(listing) if listing else {"results": [], "max_reviews": None}
    summary = parsers.parse_reviews_info(info) if info else None
    total = (summary or {}).get("review_count") or record.get("review_count") or 0
    # total_count is the product's review count; total_pages is what this
    # endpoint can page through (Temu's list cap, then the page param's cap)
    reachable = min(total, parsed["max_reviews"]) if parsed["max_reviews"] else total
    total_pages = min(parsers.total_pages_for(reachable, REVIEWS_PAGE_SIZE), MAX_REVIEWS_PAGE)
    return {
        "product": {"id": record["id"], "name": record["name"], "link": record["link"]},
        "country": country,
        "rating": record.get("rating"),
        "review_count": total or None,
        "rating_breakdown": (summary or {}).get("rating_breakdown") or [],
        "fit_breakdown": (summary or {}).get("fit_breakdown") or [],
        "tags": (summary or {}).get("tags") or record.get("review_tags") or [],
        "results": parsed["results"],
        "pagination": {"page": page, "items_per_page": REVIEWS_PAGE_SIZE, "total_pages": total_pages,
                       "total_count": total or 0},
    }


def product_reviews(**data):
    return cached_call("temu.reviews", data, _product_reviews, ttl.REVIEWS_CACHE)


# ---- store reviews ----------------------------------------------------------------------

def _store_reviews(store, country):
    listing, info = fetch.fetch_store_reviews(store, country)
    if listing is None and info is None:
        raise fetch.TemuBlocked("the store page loaded without its review calls")
    summary = parsers.parse_store_reviews_info(info) if info else {}
    reviews = parsers.parse_store_reviews(listing) if listing else []
    if not reviews and not summary.get("review_count"):
        # an unknown store id and a store without reviews look the same to
        # Temu's review calls (an empty list, no count)
        raise fetch.TemuNotFound(f"store {store} not found, or it has no reviews")
    # Only the first page loads for a guest: the store page opens Temu's
    # sign-in modal before the review list pages further (2026-10-24).
    return {
        "store": {"id": store, "link": store_link(store)},
        "country": country,
        "rating": summary.get("rating"),
        "review_count": summary.get("review_count"),
        "rating_breakdown": summary.get("rating_breakdown") or [],
        "tags": summary.get("tags") or [],
        "results": reviews,
    }


def stores_reviews(**data):
    return cached_call("temu.store_reviews", data, _store_reviews, ttl.STORE_REVIEWS_CACHE)
