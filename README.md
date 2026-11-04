# 🛒 Temu Scraper

Temu Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Temu data for free.

## ✨ What Can I Get?

- 🛍️ **Full details on any Temu product in the US, UK & Canada** — every variant's price, stock & sold count, photos, video, shipping & store
- 🔍 **Search & browse all 34 Temu departments** — sort by top sales, newest or price, with price, rating & local-warehouse filters
- ⭐ **Real buyer reviews** — star breakdown, fit, buyer country, the variant bought, photos & videos
- 🏪 **Store ratings & reviews** — rating, star breakdown & reviews with the product each one is about

## 🎥 Example: A Full Temu Product

```json
{
  "id": "601099537773480",
  "name": "Elegant French Imitation Pearl Handmade Beaded Positioning Love Stacked Bracelet Hand String Combination Set of 4pcs",
  "link": "https://www.temu.com/4pcs--beads-beaded-bracelet-set-elegant-handmade-hand-string-jewelry-accessory-g-601099537773480.html",
  "item_number": "DV51617",
  "is_available": true,
  "pricing": { "price": 2.57, "max_price": null, "list_price": 19.54, "discount_percent": 87, "currency": "USD" },
  "sold_count": 100000,
  "rating": 4.9,
  "review_count": 3584,
  "category": { "id": "426", "name": "Women's Jewelry", "link": "https://www.temu.com/category.html?opt_id=426" },
  "images": [
    { "link": "https://img.kwcdn.com/product/Fancyalgo/VirtualModelMatting/a147b69e0ed77aa6904fda086bce0678.jpg", "width": 1000, "height": 1000 }
  ],
  "video": { "link": "https://goods-vod.kwcdn.com/goods-video/413465e99920ea731558e7dfff78c51464f9e34a.f30.mp4", "thumbnail": "https://img.kwcdn.com/product/9dc464208de77ef23f8f9a30e1c4d8cb3740f45d.goods.000001.jpeg", "width": 720, "height": 720 },
  "attributes": [{ "name": "Plating", "values": ["KC Golden Plated"] }, { "name": "Style", "values": ["Vintage", "Elegant"] }],
  "variants": [
    { "id": "17592305566829", "options": [{ "name": "Size", "value": "One-size" }], "price": 2.57, "list_price": 19.54, "discount_percent": 87, "stock": 501, "sold_count": 243089 }
  ],
  "shipping": { "title": "Free shipping for this item", "options": [{ "summary": "Fastest delivery in 8 days", "cost": "Free on all orders", "delivery_time": "Nov 3-16" }] },
  "returns": { "summary": "Free returns within 90 days of purchase" },
  "store": { "id": "45456903367", "name": "SINDLAN", "rating": 4.8, "review_count": 64349, "sold_count": 1000000, "follower_count": 4900, "badge": "Star store" },
  "review_tags": [{ "name": "Well Made", "count": 391 }, { "name": "Super Cute", "count": 325 }],
  "reviews": [
    { "rating": 5, "text": "comfortable to wear,, super cute well made these are so cute. Love them. You can put them all together...", "date": "2024-07-18", "author": "Ellen Propp", "author_country": "United States" }
  ]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Temu Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/temu-scraper
cd temu-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

It needs Google Chrome installed: the first call opens it for about 30 seconds to earn Temu's trust, then product and search pages run over plain HTTP. Outside the US (or if Temu shows your IP its captcha), set `TEMU_PROXY` to a sticky US proxy first.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=601099537773480"
```

```json
{
  "id": "601099537773480",
  "name": "Elegant French Imitation Pearl Handmade Beaded Positioning Love Stacked Bracelet Hand String Combination Set of 4pcs",
  "link": "https://www.temu.com/4pcs--beads-beaded-bracelet-set-elegant-handmade-hand-string-jewelry-accessory-g-601099537773480.html",
  "item_number": "DV51617",
  "is_available": true,
  "pricing": { "price": 2.57, "max_price": null, "list_price": 4.24, "discount_percent": 39, "currency": "USD" },
  "sold_count": 100000,
  "rating": 4.9,
  "review_count": 3584,
  "category": { "id": "426", "name": "Women's Jewelry" },
  "variants": [
    { "id": "17592305566829", "options": [{ "name": "Size", "value": "One-size" }], "price": 2.57, "stock": 501, "sold_count": 243089 }
  ],
  "shipping": { "title": "Free shipping for this item", "options": [{ "summary": "Fastest delivery in 8 days", "delivery_time": "Nov 3-16" }] },
  "store": { "id": "45456903367", "name": "SINDLAN", "rating": 4.8, "review_count": 64349, "badge": "Star store" }
}
```

All 6 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

6 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Every variant's price and stock, sold counts, media, shipping and store |
| Search Products | `/products/search` | 40 products per page, sortable, with price, rating and warehouse filters |
| Product Reviews | `/products/reviews` | 10 reviews per page with photos, videos and the variant bought |
| Categories | `/categories/list` | All 34 top-level departments, or any category's subcategories |
| Category Products | `/categories/products` | Any category's products, sortable, with price and rating filters |
| Store Reviews | `/stores/reviews` | Store rating, star breakdown and reviews with the product each covers |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-temu-scraper-free-200-calls/pricing) — 200 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-temu-scraper-free-200-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-temu-scraper-free-200-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "601099537773480"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Temu Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/temu-scraper-github-whatsapp)

[![Ask Us by Email about Temu Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Temu%20Scraper%20API&body=I%20need%20help%20using%20the%20Temu%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/temu-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/temu-scraper)
