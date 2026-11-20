"""Cache TTL per /temu/* endpoint (cache.py, keyed on the validated params).

Temu reprices constantly (flash deals, clearance timers) and every uncached
page spends part of a guest identity's ~6-page budget, so listings cache
for an hour and product records a few hours; reviews and the category tree
move slowly.
"""
from datetime import timedelta

# Product record (details + the review summary/products/reviews reuse it).
PRODUCT_CACHE = timedelta(hours=3)
# Search results reorder with sales and ads within hours.
SEARCH_CACHE = timedelta(hours=1)
# Search by image: the same ranking signals as search (keyed on the picture link).
IMAGE_SEARCH_CACHE = timedelta(hours=1)
# Category listings: same ranking signals as search.
CATEGORY_PRODUCTS_CACHE = timedelta(hours=1)
# The category tree changes a few times a year.
CATEGORY_TREE_CACHE = timedelta(days=7)
# Product reviews: a popular item gets a few new reviews a day.
REVIEWS_CACHE = timedelta(hours=12)
# Store reviews: same cadence across a store's catalogue.
STORE_REVIEWS_CACHE = timedelta(hours=12)
