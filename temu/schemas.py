"""Marshmallow request schemas for every /temu/* route.

ONE param per input (tofler RefField convention, never a sibling url/id
pair):

    product    a 15-digit goods id OR any temu.com product link
    category   a category (opt) id OR a temu.com category link
    store      a store (mall) id (10-15 digits) OR a temu.com store link
    country    the Temu storefront: us (default), gb, ca — prices and
               currency follow it

Listing filters map to Temu's own filter_items tokens (temu/refs.py).
"""
from marshmallow import ValidationError, validates_schema

from schema_fields import BaseSchema, ChoiceField, Flag, PageField, Price, QueryField, RefField
from temu import refs

# Temu's listings stop at 360 results (totalPage 9 of its nominal 40). A page
# is Temu's own page: a US search renders and loads 20 at a time since
# 2026-11 (18 pages), a UK search 24 (15), a category 40 (9). Pages > 1 come
# from the browser box clicking "See more" (one click per page;
# recipes/temu_pages.py MAX_TIMES).
MAX_SEARCH_PAGE = 18
MAX_CATEGORY_PAGE = 9
# The reviews modal loads 10 per page, one scroll per page on the box.
MAX_REVIEWS_PAGE = 10


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class StoreRefField(RefField):
    resolver = staticmethod(refs.resolve_store)


def country_field():
    return ChoiceField(list(refs.MARKETS), load_default=refs.DEFAULT_MARKET, metadata={
        "description": "Temu storefront: us (default), gb, ca; prices and currency follow it"})


class _ListingSchema(BaseSchema):
    """Filters shared by search and category listings."""
    sort = ChoiceField(list(refs.SORTS), load_default="relevance", metadata={
        "description": "relevance (default), top_sales, newest, price_low_to_high, price_high_to_low"})
    min_price = Price(metadata={"description": "lowest price, in the storefront's currency"})
    max_price = Price(metadata={"description": "highest price, in the storefront's currency"})
    min_rating = ChoiceField(list(refs.MIN_RATINGS), metadata={
        "description": "minimum average rating: 1, 2, 3 or 4 stars and up"})
    local_warehouse = Flag(load_default=False, metadata={
        "description": "true: only items that ship from a warehouse in the storefront's country"})
    country = country_field()

    @validates_schema
    def _price_range(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("min_price must not be greater than max_price.", "min_price")


class SearchSchema(_ListingSchema):
    query = QueryField(metadata={"description": "what to search for, e.g. wireless earbuds"})
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "optional: only results in this category (id or temu.com category link)"})
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata={
        "description": f"page (1-{MAX_SEARCH_PAGE}) of Temu's own size: 20 results in the US, 24 in the UK"})


class CategoryProductsSchema(_ListingSchema):
    category = CategoryRefField(metadata={
        "description": "category id (e.g. 248) or a temu.com category link"})
    page = PageField(max_page=MAX_CATEGORY_PAGE, metadata={
        "description": f"page of 40 results (1-{MAX_CATEGORY_PAGE})"})


class ProductSchema(BaseSchema):
    product = ProductRefField(metadata={
        "description": "15-digit goods id, or a temu.com product link"})
    country = country_field()


class ProductReviewsSchema(BaseSchema):
    product = ProductRefField(metadata={
        "description": "15-digit goods id, or a temu.com product link"})
    country = country_field()
    page = PageField(max_page=MAX_REVIEWS_PAGE, metadata={
        "description": f"page of 10 reviews (1-{MAX_REVIEWS_PAGE})"})


class CategoriesListSchema(BaseSchema):
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "optional category (id or link): list its subcategories instead of the top-level categories"})
    country = country_field()


class StoreReviewsSchema(BaseSchema):
    store = StoreRefField(metadata={
        "description": "store id (e.g. 634418211040828), or a temu.com store link"})
    country = country_field()
