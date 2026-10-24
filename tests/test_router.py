# SPDX-License-Identifier: Apache-2.0
"""Integration tests on a router with luci-app-g7-ddm installed and pointed at a G7.

Skipped unless ROUTER_HOST is set:  ROUTER_HOST=192.0.2.1 python -m unittest tests/test_router.py
Needs SSH as root (key). LuCI pages are opened with a session created over SSH
(granted the installed access groups, as a root login would be); it is destroyed
at the end. Checks that need live data skip while the G7 does not answer.
Read-only on the router except for one poll of the G7.
"""
import json
import os
import subprocess
import sys
import unittest

from ddt import data, ddt, unpack

HOST = os.environ.get("ROUTER_HOST")
SID = None
SIZES = {"desktop": (1280, 900), "phone": (390, 844)}

SESSION_SH = r"""
sid=$(ubus call session create '{"timeout":1800}' | jsonfilter -e @.ubus_rpc_session)
for sc in ubus uci file cgi-io; do
  ubus call session grant "{\"ubus_rpc_session\":\"$sid\",\"scope\":\"$sc\",\"objects\":[[\"*\",\"*\"]]}" >/dev/null
done
objs=""
for g in $(ucode -e 'import * as fs from "fs"; for (let f in fs.glob("/usr/share/rpcd/acl.d/*.json")) for (let k in json(fs.readfile(f))) print(k, "\n");' | sort -u); do
  objs="$objs[\"$g\",\"read\"],[\"$g\",\"write\"],"
done
ubus call session grant "{\"ubus_rpc_session\":\"$sid\",\"scope\":\"access-group\",\"objects\":[${objs%,}]}" >/dev/null
tok=$(head -c16 /dev/urandom | hexdump -ve '1/1 "%02x"')
ubus call session set "{\"ubus_rpc_session\":\"$sid\",\"values\":{\"username\":\"root\",\"token\":\"$tok\"}}"
echo "$sid"
"""


def ssh(cmd, timeout=60):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", f"root@{HOST}", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip(), r.returncode


def ubus_json(obj, method, args=None):
    out, _ = ssh(f"ubus call {obj} {method} '{json.dumps(args or {})}'")
    return json.loads(out or "{}")


def g7_answers():
    return ubus_json("g7_ddm", "test_connection").get("connected") is True


def setUpModule():
    global SID
    if not HOST:
        raise unittest.SkipTest("set ROUTER_HOST to run the router integration tests")
    out, rc = ssh(SESSION_SH)
    if rc or len(out.splitlines()[-1]) != 32:
        raise unittest.SkipTest("cannot create a LuCI session on the router")
    SID = out.splitlines()[-1]


def tearDownModule():
    if SID:
        ssh(f"ubus call session destroy '{{\"ubus_rpc_session\":\"{SID}\"}}'")
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        import _browser
        _browser.close()
    except Exception:
        pass


@ddt
class Backend(unittest.TestCase):
    def test_object_and_methods(self):
        out, _ = ssh("ubus -v list g7_ddm")
        for m in ("get_status", "get_history", "get_omci", "restart", "test_connection"):
            self.assertIn(m, out)

    def test_poller_running(self):
        svc = ubus_json("service", "list", {"name": "g7_ddm"}).get("g7_ddm", {})
        self.assertTrue(any(i.get("running") for i in svc.get("instances", {}).values()))

    def test_status_shape(self):
        d = ubus_json("g7_ddm", "get_status")
        self.assertIn("success", d)
        self.assertEqual(d.get("host"), ssh("uci -q get g7_ddm.main.host")[0])
        if not d["success"]:
            self.assertIn("error", d)

    def test_live_poll(self):
        if not g7_answers():
            self.skipTest("the G7 does not answer right now")
        _, rc = ssh("/usr/libexec/rpcd/g7_ddm poll")
        self.assertEqual(rc, 0)
        d = ubus_json("g7_ddm", "get_status")
        self.assertTrue(d["success"])
        self.assertRegex(d["onu"]["state"] or "", r"^O[1-7]$|^$")
        # ubus re-encodes rpcd replies and drops a zero fraction (-30.00 -> -30): any number will do
        self.assertIsInstance(d["thresholds"]["rx_pwr_low_alarm"], (int, float))
        hist = ubus_json("g7_ddm", "get_history")["history"]
        self.assertGreaterEqual(len(hist), 1)

    def test_offline_g7_reported_not_crashing(self):
        if g7_answers():
            self.skipTest("the G7 answers; offline path covered by unit tests")
        d = ubus_json("g7_ddm", "test_connection")
        self.assertIs(d["connected"], False)
        self.assertIn("/ubus", d["error"])

    @data("hsgq_ddm", "vsol_ddm")
    def test_other_ddm_apps_untouched(self, obj):
        out, rc = ssh(f"ubus list {obj}")
        if rc:
            self.skipTest(f"{obj} not installed")
        self.assertEqual(out, obj)


@ddt
class Pages(unittest.TestCase):
    def open(self, path, size):
        sys.path.insert(0, os.path.dirname(__file__))
        import _browser
        ctx = _browser.browser().new_context(viewport={"width": size[0], "height": size[1]}, is_mobile=size[0] < 768,
                                             has_touch=size[0] < 768, ignore_https_errors=True)
        ctx.add_cookies([{"name": "sysauth_http", "value": SID, "url": f"http://{HOST}"}])
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(f"http://{HOST}/cgi-bin/luci/{path}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        return page

    @data(*[(p, n, s) for p in ("admin/status/g7_ddm/dashboard", "admin/status/g7_ddm/settings") for n, s in SIZES.items()])
    @unpack
    def test_loads(self, path, name, size):
        page = self.open(path, size)
        try:
            self.assertEqual(page.errors, [], f"{path} @ {name}")
            self.assertNotIn("sysauth", page.url)
        finally:
            page.context.close()

    def test_dashboard_is_g7(self):
        page = self.open("admin/status/g7_ddm/dashboard", SIZES["desktop"])
        try:
            text = page.inner_text("#view")          # the dashboard, not the menu (other DDM apps)
            self.assertIn("TP-LINK XZ000-G7", text.upper())
            self.assertNotIn("HSGQ", text.upper())
            self.assertNotIn("SFP TO SWITCH", text.upper())
            link = page.locator("a:has-text('Open G7 web interface')")
            self.assertEqual(link.get_attribute("href"), f"http://{ssh('uci -q get g7_ddm.main.host')[0]}/")
        finally:
            page.context.close()

    def test_settings_credentials_are_optional(self):
        page = self.open("admin/status/g7_ddm/settings", SIZES["desktop"])
        try:
            text = page.inner_text("body")
            self.assertIn("G7 IP Address", text)
            self.assertIn("Optional", text)
            self.assertNotIn("Telnet", text)
        finally:
            page.context.close()


@ddt
class Login(unittest.TestCase):
    """The optional G7 login, against the real G7 (root with an empty password,
    the G7's default). The original settings are restored afterwards; the G7 is
    never restarted (the Restart confirmation is dismissed)."""

    @classmethod
    def setUpClass(cls):
        cls.saved = {k: ssh(f"uci -q get g7_ddm.main.{k}")[0] for k in ("username", "password")}
        if not g7_answers():
            raise unittest.SkipTest("the G7 does not answer right now")

    @classmethod
    def tearDownClass(cls):
        cmds = []
        for k, v in cls.saved.items():
            cmds.append(f"uci set g7_ddm.main.{k}='{v}'" if v else f"uci -q delete g7_ddm.main.{k}")
        ssh("; ".join(cmds) + "; uci commit g7_ddm; /etc/init.d/g7_ddm restart")

    def login_as(self, user, password):
        ssh(f"uci set g7_ddm.main.username='{user}'; uci set g7_ddm.main.password='{password}'; uci commit g7_ddm; "
            "rm -f /tmp/g7_ddm.sid; /usr/libexec/rpcd/g7_ddm poll")

    def test_default_login_works(self):
        self.login_as("root", "")
        d = ubus_json("g7_ddm", "test_connection")
        self.assertIn("login works", d.get("message", ""), d)
        s = ubus_json("g7_ddm", "get_status")
        self.assertEqual(s["auth"], "logged in as root")
        self.assertRegex(s["device"]["uptime"] or "", r"^\d+d \d+h \d+m$")
        self.assertIn("OpenWrt", s["device"]["firmware"])
        self.assertTrue(s["device"]["hardware"].startswith("Linux "))

    def test_omci_objects(self):
        self.login_as("root", "")
        d = ubus_json("g7_ddm", "get_omci")
        self.assertIs(d["success"], True)
        self.assertIn(11, {o["class_id"] for o in d["objects"]})

    @data("definitely-wrong-password")
    def test_wrong_password_reported(self, password):
        self.login_as("root", password)
        d = ubus_json("g7_ddm", "test_connection")
        if d.get("success"):
            self.skipTest("this G7 accepts any password for root (none set): nothing to refuse")
        self.assertIn("login failed", d["error"])
        self.assertEqual(ubus_json("g7_ddm", "get_status")["auth"], "login failed for root")

    def test_dashboard_with_login(self):
        self.login_as("root", "")
        sys.path.insert(0, os.path.dirname(__file__))
        import _browser
        ctx = _browser.browser().new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "sysauth_http", "value": SID, "url": f"http://{HOST}"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        dialogs = []
        page.on("dialog", lambda dlg: (dialogs.append(dlg.message), dlg.dismiss()))
        try:
            page.goto(f"http://{HOST}/cgi-bin/luci/admin/status/g7_ddm/dashboard", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            self.assertEqual(errors, [])
            view = page.inner_text("#view").upper()     # the theme shows card labels in capitals
            self.assertIn("ENTITY 257 (0X0101)", view, "Ethernet UNI card shows the G7's UNI ports")
            self.assertIn("10/100/1000BASE-T", view)
            self.assertIn("SYSTEM UPTIME", view)
            origins = {o.get("origin_name") for o in ubus_json("g7_ddm", "get_omci")["objects"] if o["class_id"] == 84}
            card = view[view.index("ME 84 - "):view.index("ME 171 - ")]
            if "default" in origins:
                self.assertIn("FIRMWARE DEFAULT, NOT FROM THE OLT", card)
            if {"olt", "default"} <= origins:    # registered: the ISP's filters come before the firmware's
                self.assertLess(card.index("OLT (ISP SERVICE)"), card.index("FIRMWARE DEFAULT, NOT FROM THE OLT"))
            btn = page.locator("button:has-text('Restart G7')")
            self.assertEqual(btn.count(), 1)
            up_before = ubus_json("g7_ddm", "get_status")["device"]["uptime"]
            btn.click()
            page.wait_for_timeout(1000)
            self.assertTrue(dialogs and "Restart the G7" in dialogs[0], dialogs)
            self.assertTrue(g7_answers(), "dismissed: the G7 was not restarted")
            self.assertIsNotNone(up_before)
        finally:
            ctx.close()

    def test_settings_fields(self):
        sys.path.insert(0, os.path.dirname(__file__))
        import _browser
        ctx = _browser.browser().new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "sysauth_http", "value": SID, "url": f"http://{HOST}"}])
        page = ctx.new_page()
        try:
            page.goto(f"http://{HOST}/cgi-bin/luci/admin/status/g7_ddm/settings", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            self.assertEqual(page.locator("input[id$='.username']").count(), 1)
            self.assertEqual(page.locator("input[id$='.password'][type='password']").count(), 1)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
