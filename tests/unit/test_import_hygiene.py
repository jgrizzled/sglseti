"""Importing sglseti must be side-effect free.

The package import must not import sqlite3 (no ledger dependencies), must not
touch the network, and must not open files beyond normal module loading.
Checked in a subprocess with an audit hook so this test cannot be fooled by
modules other tests already imported.
"""

from __future__ import annotations

import json
import subprocess
import sys

_PROBE = """
import json
import os
import sys

report = {"network": [], "file_opens": []}

_allowed_roots = [os.path.realpath(p) for p in sys.path if p]


def _allowed(path):
    real = os.path.realpath(path)
    return any(
        real == root or real.startswith(root + os.sep) for root in _allowed_roots
    )


def _hook(event, args):
    if event.startswith("socket.") or event.startswith("urllib"):
        report["network"].append(event)
    elif event == "open":
        target = args[0]
        if isinstance(target, (str, bytes, os.PathLike)):
            path = os.fsdecode(target)
            if not _allowed(path):
                report["file_opens"].append(path)


sys.addaudithook(_hook)

import sglseti  # noqa: F401,E402

report["sqlite3_imported"] = "sqlite3" in sys.modules
sys.stdout.write(json.dumps(report))
"""


def _run_probe() -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_import_has_no_side_effects() -> None:
    report = _run_probe()
    assert report["sqlite3_imported"] is False, "importing sglseti must not import sqlite3"
    assert report["network"] == [], f"importing sglseti touched the network: {report['network']}"
    assert report["file_opens"] == [], (
        f"importing sglseti opened files outside module loading: {report['file_opens']}"
    )
