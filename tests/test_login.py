# SPDX-License-Identifier: Apache-2.0
"""Data-driven tests of the optional G7 login in the backend (rpcd g7_ddm).

A stand-in curl behaves like the G7's /ubus endpoint: "session login" checks the
password and hands out a session, calls with an unknown session are refused
(Access denied), and status, mib_list and reboot answer from tests/fixtures.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ddt import data, ddt, unpack

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
BACKEND = ROOT / "root/usr/libexec/rpcd/g7_ddm"
PARSER = ROOT / "root/usr/share/g7_ddm/parse.awk"
SH = shutil.which("sh") or shutil.which("bash")
VALID = "0123456789abcdef0123456789abcdef"
PUBLIC = "0" * 32

FAKE_CURL = r'''#!/bin/sh
# stand-in for the G7's /ubus endpoint
while [ $# -gt 0 ]; do case "$1" in --data) body="$2"; shift ;; esac; shift; done
printf '%s\n' "$body" >> "$CURL_LOG"
denied='{"jsonrpc":"2.0","id":1,"error":{"code":-32002,"message":"Access denied"}}'
case "$body" in
*'"session","login"'*)
	if [ -z "$G7_DOWN" ] && printf '%s' "$body" | grep -qF "\"password\":\"$GOOD_PASS_JSON\""; then
		echo '{"jsonrpc":"2.0","id":1,"result":[0,{"ubus_rpc_session":"'"$VALID_SID"'","timeout":900}]}'
	else
		echo '{"jsonrpc":"2.0","id":1,"result":[6]}'
	fi ;;
*'"omci.agent","mib_list"'*)
	case "$body" in *"$VALID_SID"*)
		printf '{"jsonrpc":"2.0","id":1,"result":[0,%s]}\n' "$(cat "$MIB")" ;;
	*) echo "$denied" ;; esac ;;
*'"system","reboot"'*)
	case "$body" in *"$VALID_SID"*) echo '{"jsonrpc":"2.0","id":1,"result":[0]}' ;; *) echo "$denied" ;; esac ;;
*)
	[ -n "$G7_DOWN" ] && exit 7
	case "$body" in
	*'"00000000000000000000000000000000","xpon.public"'*) cat "$REPLY" ;;
	*"\"$VALID_SID\",\"xpon.public\""*) cat "$REPLY_LOGIN" ;;
	*) echo "[$denied,$denied,$denied,$denied]" ;;
	esac ;;
esac
'''


def json_escape(s):
    return json.dumps(s)[1:-1]


@unittest.skipUnless(SH, "no POSIX shell")
@ddt
class Login(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "curl").write_text(FAKE_CURL, newline="\n")
        (self.bin / "uci").write_text('#!/bin/sh\nopt="${3##*.}"\nf="$UCI_DIR/$opt"\n[ -f "$f" ] && cat "$f"\n', newline="\n")
        for f in ("curl", "uci"):
            (self.bin / f).chmod(0o755)
        self.mib = self.tmp / "mib.json"
        self.mib.write_text((FIX / "g7_mib_los.json").read_text().strip())
        self.good = ""
        self.config(host="192.0.2.7")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def config(self, **opts):
        d = self.tmp / "uci"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        for k, v in opts.items():
            (d / k).write_text(v)

    def run_backend(self, *args, down=False):
        env = dict(os.environ, PATH=self.bin.as_posix() + os.pathsep + os.environ.get("PATH", ""),
                   CURL_LOG=(self.tmp / "curl.log").as_posix(), UCI_DIR=(self.tmp / "uci").as_posix(),
                   REPLY=(FIX / "g7_o5.json").as_posix(), REPLY_LOGIN=(FIX / "g7_o5_login.json").as_posix(),
                   MIB=self.mib.as_posix(), VALID_SID=VALID, GOOD_PASS_JSON=json_escape(self.good),
                   CACHE_FILE=(self.tmp / "cache.json").as_posix(), HISTORY_FILE=(self.tmp / "history.json").as_posix(),
                   SID_FILE=(self.tmp / "sid").as_posix(), PARSER=PARSER.as_posix())
        if down:
            env["G7_DOWN"] = "1"
        r = subprocess.run([SH, BACKEND.as_posix(), *args], env=env, capture_output=True, text=True, timeout=60)
        self.out = r.stdout
        return r.stdout

    def log(self):
        p = self.tmp / "curl.log"
        return p.read_text().splitlines() if p.exists() else []

    def cache(self):
        return json.loads((self.tmp / "cache.json").read_text())

    # -- polling -----------------------------------------------------------------------

    @data(
        # (username, password set, correct password, auth, uptime, calls in status batch)
        (None, None, "", "public", None, 2),
        ("root", "", "", "logged in as root", "1d 2h 3m", 4),            # the G7's default: empty password
        ("root", "s3cret", "s3cret", "logged in as root", "1d 2h 3m", 4),
        ("root", "wrong", "s3cret", "login failed for root", None, 2),    # falls back to the public status
        ("admin", 'q"uo\\te', 'q"uo\\te', "logged in as admin", "1d 2h 3m", 4),   # JSON escaping
    )
    @unpack
    def test_poll(self, user, password, good, auth, uptime, calls):
        self.good = good
        opts = {"host": "192.0.2.7"}
        if user:
            opts["username"] = user
        if password is not None:
            opts["password"] = password
        self.config(**opts)
        self.run_backend("poll")
        c = self.cache()
        self.assertEqual(c["auth"], auth)
        self.assertEqual(c["device"]["uptime"], uptime)
        self.assertEqual(c["onu"]["state"], "O5", "optics and GPON state either way")
        status = [l for l in self.log() if "xpon.public" in l][-1]
        self.assertEqual(status.count('"method":"call"'), calls)

    def test_session_is_reused(self):
        self.config(host="192.0.2.7", username="root", password="")
        self.run_backend("poll")
        self.run_backend("poll")
        self.assertEqual(sum('"session","login"' in l for l in self.log()), 1)
        self.assertEqual((self.tmp / "sid").read_text(), VALID)

    def test_expired_session_logs_in_again(self):
        self.config(host="192.0.2.7", username="root", password="")
        (self.tmp / "sid").write_text("f" * 32)                # a session the G7 no longer knows
        self.run_backend("poll")
        self.assertEqual(self.cache()["auth"], "logged in as root")
        self.assertEqual(sum('"session","login"' in l for l in self.log()), 1)
        self.assertEqual((self.tmp / "sid").read_text(), VALID)

    def test_failed_login_leaves_no_session(self):
        self.good = "right"
        self.config(host="192.0.2.7", username="root", password="wrong")
        self.run_backend("poll")
        self.assertFalse((self.tmp / "sid").exists())

    @data("s3cret-Pa55", 'q"uo\\te')
    def test_password_never_shown(self, password):
        self.good = password
        self.config(host="192.0.2.7", username="root", password=password)
        outputs = [self.run_backend("poll"), self.run_backend("call", "get_status"), self.run_backend("call", "test_connection"),
                   self.run_backend("call", "get_omci"), self.run_backend("call", "get_history")]
        for text in outputs + [(self.tmp / "cache.json").read_text(), (self.tmp / "history.json").read_text()]:
            self.assertNotIn(password, text)
            self.assertNotIn(json_escape(password), text)

    # -- test connection --------------------------------------------------------------

    @data(
        (None, "", False, True, "optical and GPON status"),
        ("", "", False, True, "login works"),
        ("wrong", "right", False, False, "login failed"),
        ("", "", True, False, "No status"),
    )
    @unpack
    def test_test_connection(self, password, good, down, ok, text):
        self.good = good
        opts = {"host": "192.0.2.7"}
        if password is not None:
            opts.update(username="root", password=password)
        self.config(**opts)
        d = json.loads(self.run_backend("call", "test_connection", down=down))
        self.assertIs(d["success"], ok)
        self.assertIn(text, d.get("message") or d.get("error"))

    # -- OMCI and restart ---------------------------------------------------------------

    def test_omci_with_login(self):
        self.config(host="192.0.2.7", username="root", password="")
        d = json.loads(self.run_backend("call", "get_omci"))
        self.assertIs(d["success"], True)
        self.assertEqual(d["objects"], json.loads(self.mib.read_text())["objects"])

    @data((None, "need the G7 login"), ("wrong", "Could not log in"))
    @unpack
    def test_omci_without_working_login(self, password, text):
        self.good = "right"
        opts = {"host": "192.0.2.7"}
        if password is not None:
            opts.update(username="root", password=password)
        self.config(**opts)
        d = json.loads(self.run_backend("call", "get_omci"))
        self.assertIs(d["success"], False)
        self.assertIn(text, d["error"])

    def test_restart_with_login(self):
        self.config(host="192.0.2.7", username="root", password="")
        self.run_backend("poll")
        d = json.loads(self.run_backend("call", "restart"))
        self.assertIs(d["success"], True)
        self.assertIn('"system","reboot"', self.log()[-1])
        self.assertFalse((self.tmp / "sid").exists(), "the session dies with the reboot")
        self.assertFalse((self.tmp / "cache.json").exists())

    @data((None, "need", "the G7 login"), ("wrong", "right", "did not accept"))
    @unpack
    def test_restart_refused(self, password, good, text):
        self.good = good
        opts = {"host": "192.0.2.7"}
        if password is not None:
            opts.update(username="root", password=password)
        self.config(**opts)
        d = json.loads(self.run_backend("call", "restart"))
        self.assertIs(d["success"], False)
        self.assertIn(text, d["error"])
        self.assertFalse(any('"system","reboot"' in l for l in self.log() if VALID in l))


if __name__ == "__main__":
    unittest.main()
