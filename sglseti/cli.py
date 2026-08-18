"""Thin command-line interface over the public Python API.

The CLI only parses arguments, calls public functions, writes results, and
formats errors. Remaining subcommands (``samples``, ``generate``, ``plan``)
arrive with the phases that implement their underlying APIs.
"""

from __future__ import annotations

import argparse
import sys
from typing import Literal

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


def _cmd_validate_targets(args: argparse.Namespace) -> int:
    from .targets import load_target_registry

    policy: Literal["error", "flag"] = "flag" if args.allow_missing_rv else "error"
    registry = load_target_registry(args.path, missing_radial_velocity=policy)
    print(f"OK: {len(registry)} target(s) validated from {args.path}")
    for target in registry:
        flags = f" [{', '.join(target.flags)}]" if target.flags else ""
        print(f"  {target.target_id}: {target.display_name} ({target.endpoint_kind}){flags}")
    print(f"registry hash: {registry.source_hash}")
    return 0


def _cmd_validate_request(args: argparse.Namespace) -> int:
    from .config import load_request
    from .models import TimeGrid, TimeList, TimeSingle

    request = load_request(args.path)
    print(f"OK: request {args.path} is valid")
    print(f"  targets: {', '.join(request.target_ids)}")
    print(f"  roles: {', '.join(role.value for role in request.roles)}")
    if isinstance(request.time, TimeSingle):
        print(f"  time: single epoch {request.time.epoch.epoch_id}")
    elif isinstance(request.time, TimeList):
        print(f"  time: {len(request.time.epochs)} listed epoch(s)")
    elif isinstance(request.time, TimeGrid):
        print(f"  time: grid at {request.time.cadence_s:g} s cadence")
    print(f"  observer: {request.observer.observer_id} ({request.observer.kind})")
    print(
        f"  relay range: {request.relay_range.z_min_au:g}-{request.relay_range.z_max_au:g} AU "
        f"({request.sampling.kind} sampling)"
    )
    print(f"  model: {request.model_id}")
    return 0


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

    subcommands = parser.add_subparsers(dest="command")

    validate = subcommands.add_parser(
        "validate",
        help="Validate local input files without computing geometry.",
    )
    validate_kind = validate.add_subparsers(dest="validate_kind", required=True)

    validate_targets = validate_kind.add_parser(
        "targets", help="Validate a curated target registry YAML file."
    )
    validate_targets.add_argument("path", help="Path to the target registry YAML.")
    validate_targets.add_argument(
        "--allow-missing-rv",
        action="store_true",
        help=(
            "Accept targets without radial velocity as flagged instead of failing; "
            "the value is recorded as missing, never assumed zero."
        ),
    )
    validate_targets.set_defaults(func=_cmd_validate_targets)

    validate_request = validate_kind.add_parser(
        "request", help="Validate a calculation request YAML file."
    )
    validate_request.add_argument("path", help="Path to the request YAML.")
    validate_request.set_defaults(func=_cmd_validate_request)

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
