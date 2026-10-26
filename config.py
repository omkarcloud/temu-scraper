"""Configuration for the Temu Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT          port the API listens on (default 8000)
    TEMU_PROXY    proxy URL for every request, e.g. http://user:pass@host:port
                  (default: none — your own IP). Temu serves each storefront
                  only to visitors in its country (us = USA, gb = UK,
                  ca = Canada) and shows a captcha to IPs it distrusts. If you
                  get "captcha" / "not in the storefront's country" errors,
                  point this at a STICKY proxy (one IP per URL, never a
                  rotating one) in that country: Temu's trust is bound to the
                  IP it was earned on.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

TEMU_PROXY = os.environ.get("TEMU_PROXY") or None

# Pages one trusted guest serves before a fresh one is earned in Chrome
# (Temu answers the 7th product page / 7th search of a guest with its captcha).
TEMU_PRODUCT_PAGES = 5
TEMU_LISTING_PAGES = 4
TEMU_IDENTITY_MAX_AGE = 900    # seconds
# Chrome runs to earn a guest: at most this many per minute, and this many
# tries per request before it fails.
TEMU_MINTS_PER_MINUTE = 4
TEMU_MINT_ATTEMPTS = 1
TEMU_PAGES_SESSIONS = 1        # kept Chromes per storefront for page 2+ and reviews


def temu_proxy(market="us"):
    """The connection Chrome earns trust on and every request reuses (None = your own IP)."""
    return os.environ.get("TEMU_PROXY") or None
