# SPDX-License-Identifier: Apache-2.0
"""Shared Playwright browser for the tests: its own Chromium, else Chrome or Edge."""
import unittest

_PW = _BROWSER = None


def browser():
    global _PW, _BROWSER
    if _BROWSER:
        return _BROWSER
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise unittest.SkipTest("playwright is not installed (pip install playwright)")
    _PW = sync_playwright().start()
    for kw in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
        try:
            _BROWSER = _PW.chromium.launch(**kw)
            return _BROWSER
        except Exception:
            continue
    _PW.stop()
    _PW = None
    raise unittest.SkipTest("no Chromium, Chrome or Edge for Playwright")


def close():
    global _PW, _BROWSER
    if _BROWSER:
        _BROWSER.close()
    if _PW:
        _PW.stop()
    _PW = _BROWSER = None
