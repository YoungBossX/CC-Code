"""Pytest plugin to label skipped tests as test_1, test_2 in short progress output.

Behavior:
- When a test is skipped at the `call` phase, assign it a label `test_N` and
  write that label into the short progress stream instead of the single-letter
  `s` marker.
- At the end of the run, print a small mapping table showing which label maps
  to which test nodeid.

Note: this changes the short-progress output width (labels are longer than a
single char) which may affect alignment; it's intended for local readability.
"""
from __future__ import annotations

import collections
from typing import Dict
import sys

skip_counter = 0
# nodeid -> (label, shortchar)
skip_map: Dict[str, tuple[str, str]] = collections.OrderedDict()


def _short_char_for(n: int) -> str:
    """Return a single-character short marker for index n (1-based).

    Uses digits 1-9, then lowercase letters a-z, then uppercase A-Z if needed.
    """
    if n <= 9:
        return str(n)
    n -= 10
    letters = "abcdefghijklmnopqrstuvwxyz"
    if n < len(letters):
        return letters[n]
    n -= len(letters)
    letters2 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n < len(letters2):
        return letters2[n]
    # fallback
    return "?"


def pytest_report_teststatus(report, config):
    # When a test is skipped at the call phase, return a custom shortlabel
    # (e.g. "test_1") so pytest prints that label in the short progress stream
    # instead of the single-letter 's'. We also record the mapping for summary.
    global skip_counter
    if getattr(report, "when", None) == "call" and getattr(report, "skipped", False):
        nodeid = getattr(report, "nodeid", "<unknown>")
        global skip_counter
        skip_counter += 1
        label = f"test_{skip_counter}"
        shortchar = _short_char_for(skip_counter)
        skip_map[nodeid] = (label, shortchar)
        # Return single-character short marker so pytest prints it in the
        # short-progress stream instead of the default 's'.
        return "skipped", shortchar, "SKIPPED"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not skip_map:
        return
    terminalreporter.write_sep("-", "Skipped tests mapping")
    for nodeid, (label, shortchar) in skip_map.items():
        terminalreporter.write_line(f"{shortchar}: {label} -> {nodeid}")
    # Also write the mapping directly to stderr so it appears even when pytest
    # is run with -q/quiet (which may suppress some terminalreporter output).
    try:
        sys.stderr.write("\n--- Skipped tests mapping (forced) ---\n")
        for nodeid, (label, shortchar) in skip_map.items():
            sys.stderr.write(f"{shortchar}: {label} -> {nodeid}\n")
        sys.stderr.write("--- end mapping ---\n\n")
    except Exception:
        pass


def pytest_runtest_logreport(report):
    # No-op: we assign short markers in pytest_report_teststatus so the
    # terminal short-progress stream shows single-character markers directly.
    return
