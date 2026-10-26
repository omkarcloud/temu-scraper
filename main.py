"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The first call opens Chrome for about 30 seconds to earn a
trusted Temu guest, then product and search pages run over plain HTTP.
"""
import json
import os

from temu.api import product_details, product_reviews, products_search

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a product ID or any temu.com product link
    save("product_601099537773480.json", product_details(product="601099537773480", country="us"))

    # 40 products per page; sort, price, rating and warehouse filters are optional
    save("search_raspberry_pi.json", products_search(query="raspberry pi", category=None, sort="relevance",
                                                     min_price=None, max_price=None, min_rating=None,
                                                     local_warehouse=False, country="us", page=1))

    # 10 reviews per page with photos, videos and the variant bought
    save("reviews_601099537773480.json", product_reviews(product="601099537773480", country="us", page=1))
