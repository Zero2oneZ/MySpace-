"""lucid/ — outbound bridges to Lucid's developer platform.

Two pieces live here:

  - standard_import.py   converts our Tesseract inventory into a Lucid
                         Standard Import JSON file that can be dropped
                         into Lucid via File → Import. Pure offline; no
                         Lucid account needed.

  - data_connector/      Node.js skeleton (scaffolding only) for a real
                         data connector that would expose action handlers
                         to Lucid. Not deployed in-tree.

See studio/docs/LUCID_INTEGRATION.md for the full mapping + plan.
"""
from .standard_import import build_standard_import  # noqa: F401
