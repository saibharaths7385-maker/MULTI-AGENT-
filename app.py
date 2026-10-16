"""Compatibility entry point for `uvicorn app:app` and existing imports."""
from backend import core
from backend.core import parse_files, parse_json, safe
from backend.main import app

WS = core.WS


def run_tests(pid):
    previous_ws = core.WS
    core.WS = WS
    try:
        return core.run_tests(pid)
    finally:
        core.WS = previous_ws
