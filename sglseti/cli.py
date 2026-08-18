"""Thin command-line interface over the public Python API.

The CLI only parses arguments, calls public functions, writes results, and
formats errors. Subcommands (``validate``, ``samples``, ``generate``,
``plan``) arrive with the phases that implement their underlying APIs; the
Phase 1 scaffold provides the program shell, ``--version``, and the
domain-error boundary.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import SglsetiError

_DESCRIPTION = (
    "Generate reproducible solar-gravitational-lens (SGL) sky targets for "
    "archival cross-reference and commensal searches."
)

_EPILOG = (
    "sglseti ends at target products: archive lookup, observation ingest, and "
    "historical search-coverage tracking are handled by external systems."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sglseti",
        description=_DESCRIPTION,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.set_defaults(func=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except SglsetiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
