"""Offline tests for the /temu/* request schemas.

    python -m pytest temu/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from temu import schemas  # noqa: E402


def errors(schema_cls, data):
    with pytest.raises(ValidationError) as exc:
        schema_cls().load(data)
    return exc.value.normalized_messages()


# ---- products/search ----------------------------------------------------------------------

def test_search_defaults():
    assert schemas.SearchSchema().load({"query": "  wireless   earbuds "}) == {
        "query": "wireless earbuds", "category": None, "sort": "relevance", "min_price": None,
        "max_price": None, "min_rating": None, "local_warehouse": False, "country": "us", "page": 1}


def test_search_all_filters():
    loaded = schemas.SearchSchema().load({
        "query": "phone case", "category": "https://www.temu.com/electronics-o3-248.html",
        "sort": "TOP_SALES", "min_price": "5", "max_price": "10.5", "min_rating": "4",
        "local_warehouse": "true", "country": "GB", "page": "3"})
    assert loaded == {"query": "phone case", "category": "248", "sort": "top_sales", "min_price": 5.0,
                      "max_price": 10.5, "min_rating": "4", "local_warehouse": True, "country": "gb", "page": 3}


@pytest.mark.parametrize("data,field,message", [
    ({}, "query", "Missing data"),
    ({"query": "   "}, "query", "Must not be empty"),
    ({"query": "x", "sort": "cheapest"}, "sort", "Must be one of"),
    ({"query": "x", "page": "19"}, "page", "less than or equal to 18"),
    ({"query": "x", "min_price": "-1"}, "min_price", "greater than or equal to 0"),
    ({"query": "x", "min_price": "20", "max_price": "10"}, "min_price", "must not be greater"),
    ({"query": "x", "min_rating": "5"}, "min_rating", "Must be one of"),
    ({"query": "x", "country": "fr"}, "country", "Must be one of"),
    ({"query": "x", "category": "https://example.com/x-o3-1.html"}, "category", "temu.com link"),
    ({"query": "x", "url": "https://www.temu.com"}, "url", "Unknown field"),
])
def test_search_rejects(data, field, message):
    errs = errors(schemas.SearchSchema, data)
    assert field in errs and message in " ".join(errs[field])


# ---- products/details and products/reviews ----------------------------------------------------

def test_product_schema_accepts_id_and_links():
    for value in ("601099513224343", "https://www.temu.com/x-g-601099513224343.html",
                  "https://www.temu.com/goods.html?goods_id=601099513224343&x=1"):
        assert schemas.ProductSchema().load({"product": value}) == {"product": "601099513224343", "country": "us"}


@pytest.mark.parametrize("data,field,message", [
    ({}, "product", "Missing data"),
    ({"product": "123"}, "product", "goods id"),
    ({"product": "https://share.temu.com/abc"}, "product", "Share links"),
    ({"product": "601099513224343", "goods_id": "601099513224343"}, "goods_id", "Unknown field"),
])
def test_product_schema_rejects(data, field, message):
    errs = errors(schemas.ProductSchema, data)
    assert field in errs and message in " ".join(errs[field])


def test_product_reviews_schema():
    assert schemas.ProductReviewsSchema().load({"product": "601099513224343", "page": "2", "country": "ca"}) == \
        {"product": "601099513224343", "page": 2, "country": "ca"}
    errs = errors(schemas.ProductReviewsSchema, {"product": "601099513224343", "page": "11"})
    assert "less than or equal to 10" in " ".join(errs["page"])


# ---- categories ----------------------------------------------------------------------------

def test_category_products_schema():
    loaded = schemas.CategoryProductsSchema().load({"category": "355", "sort": "newest"})
    assert loaded["category"] == "355" and loaded["sort"] == "newest" and loaded["page"] == 1
    errs = errors(schemas.CategoryProductsSchema, {"sort": "newest"})
    assert "Missing data" in " ".join(errs["category"])
    errs = errors(schemas.CategoryProductsSchema, {"category": "electronics"})
    assert "category id" in " ".join(errs["category"])
    # categories page by 40 (9 pages), searches by 20 (18 pages)
    errs = errors(schemas.CategoryProductsSchema, {"category": "355", "page": "10"})
    assert "less than or equal to 9" in " ".join(errs["page"])
    assert schemas.SearchSchema().load({"query": "x", "page": "18"})["page"] == 18


def test_categories_list_schema():
    assert schemas.CategoriesListSchema().load({}) == {"category": None, "country": "us"}
    assert schemas.CategoriesListSchema().load({"category": "https://www.temu.com/electronics-o3-248.html"}) == \
        {"category": "248", "country": "us"}


# ---- stores/reviews ----------------------------------------------------------------------

def test_store_reviews_schema():
    assert schemas.StoreReviewsSchema().load({"store": "https://www.temu.com/mall.html?mall_id=634418229064892"}) == \
        {"store": "634418229064892", "country": "us"}
    errs = errors(schemas.StoreReviewsSchema, {"store": "634418229064892", "page": "2"})
    assert "Unknown field" in " ".join(errs["page"])
    errs = errors(schemas.StoreReviewsSchema, {"store": "abc"})
    assert "store id" in " ".join(errs["store"])


# ---- products/search-by-image ------------------------------------------------------------

def test_image_search_schema():
    link = "https://img.kwcdn.com/product/fancy/89d07051-7673-4f3f-9366-0f00498e0bf1.jpg"
    assert schemas.ImageSearchSchema().load({"image": link}) == {"image": link, "country": "us", "page": 1}
    assert schemas.ImageSearchSchema().load({"image": " example.com/a.png ", "country": "gb", "page": "3"}) == \
        {"image": "https://example.com/a.png", "country": "gb", "page": 3}


@pytest.mark.parametrize("data,field,message", [
    ({}, "image", "required"),
    ({"image": "data:image/png;base64,iVBORw0"}, "image", "not a data: URI"),
    ({"image": "ftp://example.com/a.jpg"}, "image", "http(s)"),
    ({"image": "localhost/a.jpg"}, "image", "picture link"),
    ({"image": "https://example.com/a.jpg", "page": "11"}, "page", "less than or equal to 10"),
    ({"image": "https://example.com/a.jpg", "country": "de"}, "country", "Must be one of"),
])
def test_image_search_schema_rejects(data, field, message):
    assert message in " ".join(errors(schemas.ImageSearchSchema, data)[field])
