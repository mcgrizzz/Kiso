"""Kiso (基礎, "foundation"): the plumbing Anki add-ons share.

Bundled into each add-on at build time under its own package (`<pkg>/_kiso/`),
so two add-ons with different Kiso versions never meet. Everything in here
imports its siblings relatively, never as `kiso`.
"""

__version__ = "0.1.0"
