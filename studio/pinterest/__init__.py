"""Pinterest search + save-to-media for the studio.

`client.py` is a thin REST wrapper around Pinterest's API (with a
search-URL scrape fallback). `pinterest_app.py` (in studio/) is the
Streamlit search UI that hands selected pins off to the intake tools.
"""

from .client import PinterestClient, PinResult  # noqa: F401
