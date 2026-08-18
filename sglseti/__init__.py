"""SGLSETI: reproducible sky-target generation for SGL technosignature searches.

SGLSETI turns a curated stellar-system hypothesis, an observer, and past or
future epochs into reproducible, telescope-usable solar-gravitational-lens
target regions.

The package ends at the generation and export of target products. Archive
discovery, observation ingest, historical-coverage accounting, and candidate
management belong to other projects, and no module in this package may depend
on an observation ledger or mutable service database.

Importing :mod:`sglseti` must stay side-effect free: no file reads, no network
access, and no heavy scientific imports at package-import time.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
