# SPDX-License-Identifier: Apache-2.0
"""Data-driven unit tests of the G7 parser (parse.awk) and rpcd backend (g7_ddm).

The real awk parser and shell backend run against replies captured from a G7
(tests/fixtures, identity scrubbed); a stand-in curl returns them and a stand-in
uci supplies the settings. Needs a POSIX sh with awk (on Windows: Git for Windows).
Run:  python -m unittest discover -s tests -p "test_*.py"
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from ddt import data, ddt, unpack

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
PARSER = ROOT / "root/usr/share/g7_ddm/parse.awk"
BACKEND = ROOT / "root/usr/libexec/rpcd/g7_ddm"
SH = shutil.which("sh") or shutil.which("bash")
AWK = shutil.which("awk")


def parse(fixture, cls="bplus", host="192.0.2.1"):
    r = subprocess.run([AWK, "-v", f"host={host}", "-v", "ts=1700000000", "-v", f"req_class={cls}", "-f", PARSER.as_posix()],
                       input=(FIX / fixture).read_text(), capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def dig(d, path):
    for k in path.split("."):
        d = d[k]
    return d


@unittest.skipUnless(AWK, "no awk")
@ddt
class Parser(unittest.TestCase):
    @data(
        # registered, light as measured on a G7 (9800 nW in, 1.8162 mW out)
        ("g7_o5.json", "ddm.rx_power_dbm", -20.09),
        ("g7_o5.json", "ddm.tx_power_dbm", 2.59),
        ("g7_o5.json", "ddm.temperature_c", 34.82),
        ("g7_o5.json", "ddm.voltage_v", 3.24),
        ("g7_o5.json", "ddm.bias_current_ma", 14.48),
        ("g7_o5.json", "onu.state", "O5"),
        ("g7_o5.json", "onu.state_raw", "Operation State (O5)"),
        ("g7_o5.json", "onu.registered_status", "Registered (O5)"),
        ("g7_o5.json", "onu.alarm_los", "Clear (Normal)"),
        ("g7_o5.json", "onu.onu_id", 100),
        ("g7_o5.json", "onu.serial_number", "TPLG0000ABCD"),
        ("g7_o5.json", "onu.olt_profile", "nokia-alcl"),
        ("g7_o5.json", "onu.omci_agent", "operational"),
        ("g7_o5.json", "onu.mib_objects", 265),
        ("g7_o5.json", "device.model", "XZ000-G7 v1.0"),
        ("g7_o5.json", "ddm.part_number", "XZ000-G7"),
        ("g7_o5.json", "optical_class", "bplus"),
        ("g7_o5.json", "optical_class_source", "module"),
        # the module's own limits, nW -> dBm
        ("g7_o5.json", "thresholds.rx_pwr_low_alarm", -30.0),
        ("g7_o5.json", "thresholds.rx_pwr_low_warn", -28.86),
        ("g7_o5.json", "thresholds.rx_pwr_high_warn", -7.0),
        ("g7_o5.json", "thresholds.rx_pwr_high_alarm", -6.0),
        ("g7_o5.json", "thresholds.tx_pwr_low_alarm", -0.5),
        ("g7_o5.json", "thresholds.tx_pwr_low_warn", 0.0),
        ("g7_o5.json", "thresholds.tx_pwr_high_warn", 5.5),
        ("g7_o5.json", "thresholds.tx_pwr_high_alarm", 6.0),
        ("g7_o5.json", "thresholds.temp_high_warn", 65.0),
        # no fibre (as captured): no light, O1, LOS
        ("g7_los.json", "ddm.rx_power_dbm", None),
        ("g7_los.json", "ddm.tx_power_dbm", None),
        ("g7_los.json", "ddm.temperature_c", 40.05),
        ("g7_los.json", "onu.state", "O1"),
        ("g7_los.json", "onu.registered_status", "Not Registered (O1)"),
        ("g7_los.json", "onu.alarm_los", "Active (LOS Alarm)"),
        ("g7_los.json", "onu.onu_id", None),                   # 65535 = no ONU-ID
        ("g7_los.json", "onu.omci_agent", "waiting for the OLT"),
        ("g7_los.json", "ddm.module_alarms", "0x0140"),
        # weak but above the module's LOS limit
        ("g7_weak.json", "ddm.rx_power_dbm", -29.21),
        ("g7_weak.json", "onu.alarm_los", "Clear (Normal)"),
        # EPON mode
        ("g7_epon.json", "optical_class", "epon_px20"),
        ("g7_epon.json", "onu.registered_status", "Registered (EPON)"),
        ("g7_epon.json", "onu.state", None),
        ("g7_epon.json", "thresholds.citation", "IEEE 802.3 1000BASE-PX20-U"),
    )
    @unpack
    def test_field(self, fixture, path, want):
        self.assertEqual(dig(parse(fixture), path), want)

    @data(("bplus", "ITU-T G.984.2 Class B+"), ("cplus", "ITU-T G.984.2 Class C+"), ("bogus", "ITU-T G.984.2 Class B+"))
    @unpack
    def test_class(self, cls, citation):
        d = parse("g7_o5.json", cls)
        self.assertEqual(d["ddm"]["optical_budget_class"], citation)

    @data("g7_o5.json", "g7_los.json", "g7_weak.json", "g7_epon.json")
    def test_compatible_with_hsgq_and_noc(self, fixture):
        # keys the shared dashboard and the Home NOC read from every DDM cache
        d = parse(fixture)
        self.assertIs(d["success"], True)
        self.assertIs(d["connected"], True)
        self.assertEqual(d["timestamp"], 1700000000)
        for k in ("rx_power_dbm", "tx_power_dbm", "temperature_c", "voltage_v", "bias_current_ma"):
            self.assertIn(k, d["ddm"])
        for k in ("state", "registered_status", "alarm_los"):
            self.assertIn(k, d["onu"])
        for k in ("rx_pwr_low_alarm", "rx_pwr_low_warn", "rx_pwr_high_warn", "tx_pwr_low_warn", "tx_pwr_high_warn",
                  "temp_low_warn", "temp_high_warn"):
            self.assertIsInstance(d["thresholds"][k], float)

    @data(("g7_denied.json", "did not return its status"), (None, "did not return its status"))
    @unpack
    def test_failure(self, fixture, msg):
        r = subprocess.run([AWK, "-v", "host=192.0.2.1", "-v", "ts=1", "-v", "req_class=bplus", "-f", PARSER.as_posix()],
                           input=(FIX / fixture).read_text() if fixture else "", capture_output=True, text=True)
        d = json.loads(r.stdout)
        self.assertIs(d["success"], False)
        self.assertIn(msg, d["error"])


@unittest.skipUnless(SH, "no POSIX shell")
@ddt
class Backend(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.reply = self.tmp / "reply.json"
        self.uci = {"enabled": "1", "host": "192.0.2.7", "port": "80", "timeout": "8", "optical_class": "bplus"}
        (self.bin / "curl").write_text('#!/bin/sh\necho "$*" >> "$CURL_LOG"\n[ -s "$REPLY" ] && cat "$REPLY"\n', newline="\n")
        (self.bin / "uci").write_text('#!/bin/sh\n# uci -q get g7_ddm.main.<opt>\nopt="${3##*.}"\nf="$UCI_DIR/$opt"\n[ -f "$f" ] && cat "$f"\n', newline="\n")
        for f in ("curl", "uci"):
            (self.bin / f).chmod(0o755)
        self.write_uci()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_uci(self):
        d = self.tmp / "uci"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        for k, v in self.uci.items():
            (d / k).write_text(v)

    def run_backend(self, *args, fixture="g7_o5.json", check=True):
        if fixture:
            shutil.copy(FIX / fixture, self.reply)
        elif self.reply.exists():
            self.reply.unlink()
        env = dict(os.environ, PATH=self.bin.as_posix() + os.pathsep + os.environ.get("PATH", ""),
                   REPLY=self.reply.as_posix(), CURL_LOG=(self.tmp / "curl.log").as_posix(), UCI_DIR=(self.tmp / "uci").as_posix(),
                   CACHE_FILE=(self.tmp / "cache.json").as_posix(), HISTORY_FILE=(self.tmp / "history.json").as_posix(),
                   PARSER=PARSER.as_posix())
        r = subprocess.run([SH, BACKEND.as_posix(), *args], env=env, capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(r.returncode, 0, r.stderr)
        self.rc = r.returncode
        return r.stdout

    def test_list(self):
        self.assertEqual(set(json.loads(self.run_backend("list"))),
                         {"get_status", "get_info", "get_history", "test_connection", "get_omci", "restart"})

    def test_poll_writes_cache_and_history(self):
        self.run_backend("poll")
        cache = json.loads((self.tmp / "cache.json").read_text())
        self.assertEqual(cache["onu"]["state"], "O5")
        self.assertEqual(cache["host"], "192.0.2.7")
        hist = (self.tmp / "history.json").read_text().split()
        self.assertEqual(len(hist), 1)
        ts, rx, tx, temp, bias = json.loads(hist[0])
        self.assertEqual((rx, tx, temp, bias), (-20.09, 2.59, 34.82, 14.48))
        self.assertIn("http://192.0.2.7/ubus", (self.tmp / "curl.log").read_text())

    @data(("80", "http://192.0.2.7/ubus"), ("8080", "http://192.0.2.7:8080/ubus"))
    @unpack
    def test_url(self, port, url):
        self.uci["port"] = port
        self.write_uci()
        self.run_backend("poll")
        self.assertIn(url, (self.tmp / "curl.log").read_text())

    def test_history_rate_limited(self):
        self.run_backend("poll")
        self.run_backend("poll")
        self.assertEqual(len((self.tmp / "history.json").read_text().split()), 1, "one sample per minute")

    def test_history_without_light(self):
        self.run_backend("poll", fixture="g7_los.json")
        self.assertEqual(json.loads((self.tmp / "history.json").read_text().split()[0])[1:], [None, None, 40.05, 14.89])

    @data(("g7_denied.json",), (None,))
    @unpack
    def test_failed_poll_keeps_old_cache(self, fixture):
        self.run_backend("poll")
        before = (self.tmp / "cache.json").read_text()
        self.run_backend("poll", fixture=fixture, check=False)
        self.assertNotEqual(self.rc, 0, "a failed poll reports failure")
        self.assertEqual((self.tmp / "cache.json").read_text(), before)

    def test_status_from_cache(self):
        self.run_backend("poll")
        self.assertEqual(json.loads(self.run_backend("call", "get_status", fixture=None))["onu"]["state"], "O5")
        self.assertNotIn("get_status", (self.tmp / "curl.log").read_text(), "status never contacts the G7")
        self.assertEqual(len((self.tmp / "curl.log").read_text().splitlines()), 1)

    def test_status_stale(self):
        self.run_backend("poll")
        old = time.time() - 600
        os.utime(self.tmp / "cache.json", (old, old))
        d = json.loads(self.run_backend("call", "get_status", fixture=None))
        self.assertIs(d["success"], False)
        self.assertIn("No answer from the G7", d["error"])

    def test_status_before_first_poll(self):
        d = json.loads(self.run_backend("call", "get_status", fixture=None))
        self.assertIn("Waiting for the first reading", d["error"])

    @data(
        ({"host": ""}, "configured", False),
        ({"enabled": "0"}, "error", "Monitoring has been disabled in configuration"),
    )
    @unpack
    def test_status_config(self, change, key, want):
        self.uci.update(change)
        self.write_uci()
        if not change.get("host", "x"):
            (self.tmp / "uci" / "host").unlink()
        self.assertEqual(json.loads(self.run_backend("call", "get_status"))[key], want)

    def test_unconfigured_never_polls(self):
        (self.tmp / "uci" / "host").unlink()
        self.run_backend("poll")
        self.assertFalse((self.tmp / "cache.json").exists())
        self.assertFalse((self.tmp / "curl.log").exists())

    @data(("g7_o5.json", True), ("g7_denied.json", False), (None, False))
    @unpack
    def test_test_connection(self, fixture, ok):
        self.assertIs(json.loads(self.run_backend("call", "test_connection", fixture=fixture))["connected"], ok)

    @data(("get_omci", "OMCI summary"), ("restart", "System -> Reboot"))
    @unpack
    def test_unsupported_explained(self, method, text):
        d = json.loads(self.run_backend("call", method))
        self.assertIs(d["success"], False)
        self.assertIn(text, d["error"])

    def test_get_history(self):
        self.run_backend("poll")
        d = json.loads(self.run_backend("call", "get_history"))
        self.assertEqual(len(d["history"]), 1)

    def test_unknown(self):
        self.assertIn("Unknown method", self.run_backend("call", "nope"))


class Files(unittest.TestCase):
    def test_shell_syntax_and_lf(self):
        for f in (BACKEND, ROOT / "root/etc/init.d/g7_ddm", ROOT / "root/etc/uci-defaults/80_luci-app-g7-ddm",
                  ROOT / "install.sh", ROOT / "uninstall.sh"):
            self.assertNotIn(b"\r\n", f.read_bytes(), f.name)
            if SH:
                self.assertEqual(subprocess.run([SH, "-n", f.as_posix()], capture_output=True).returncode, 0, f.name)

    def test_json_files(self):
        for f in (ROOT / "root/usr/share/luci/menu.d/luci-app-g7-ddm.json", ROOT / "root/usr/share/rpcd/acl.d/luci-app-g7-ddm.json"):
            json.loads(f.read_text())

    def test_fixture_identity_is_scrubbed(self):
        # captured from a real unit: only the placeholder serial and documentation addresses
        for f in FIX.glob("*.json"):
            text = f.read_text()
            for serial in re.findall(r'"serial"\s*:\s*"([^"]*)"', text):
                self.assertEqual(serial, "TPLG0000ABCD", f.name)
            for ip in re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", text):
                self.assertTrue(ip.startswith(("192.0.2.", "198.51.100.", "203.0.113.")), (f.name, ip))


if __name__ == "__main__":
    unittest.main()
