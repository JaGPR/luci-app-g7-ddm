# luci-app-g7-ddm

Optical diagnostics in your **OpenWrt router's LuCI** for a **TP-Link XZ000-G7** GPON ONT
running the [galachip OpenWrt firmware](https://github.com/AliLostInTheDark/openwrt-galachip):
Rx/Tx optical power, temperature, voltage and laser bias with the module's own warning and
alarm limits, GPON state (O1–O7), ONU-ID, OLT profile, LOS alarm and 24-hour history charts.

It is the G7 sibling of [luci-app-hsgq-ddm](https://github.com/JaGPR/luci-app-hsgq-ddm) and
[luci-app-vsol-ddm](https://github.com/AliLostInTheDark/luci-app-vsol-ddm), with the same dashboard.

**No login needed.** The G7 firmware publishes its optics and GPON state read-only over HTTP
(`xpon.public status`, `omci.agent status` on its `/ubus` endpoint), so the only setting is
the G7's address. Nothing is stored but that address.

## How it works
- A background poller on the router asks the G7 for its status every 30 s with one batched
  JSON-RPC request and writes `/tmp/g7_ddm_cache.json` (plus a one-sample-per-minute history).
- The dashboard only reads that cache, so leaving the page open adds no load on the G7.
- The cache has the same format as luci-app-vsol-ddm / -hsgq-ddm, so tools that read those
  (for example Home NOC's fibre panel and alerts) can read the G7's too.
- The full OMCI MIB and reboot need a login on the G7; the dashboard links to its own web
  interface for those.

## Install
```sh
wget -qO /tmp/install.sh https://raw.githubusercontent.com/JaGPR/luci-app-g7-ddm/main/install.sh && sh /tmp/install.sh
```
Then **Status → G7 GPON DDM → Settings**: enter the G7's management address, Save & Apply,
press **Test connection**, and open **Optical Diagnostics**. The router must be able to reach
that address (for example a VLAN interface on the G7's management network).

Remove with `uninstall.sh` (`KEEP_CONFIG=1` keeps the address). An OpenWrt `Makefile` is
included for building a package in the SDK.

## Tests
```sh
pip install ddt playwright && python -m playwright install chromium
python -m unittest discover -s tests -p "test_*.py"                          # unit: parser + backend
ROUTER_HOST=192.0.2.1 python -m unittest tests/test_router.py                # integration, on a router
```
The unit tests run the real awk parser and shell backend against replies captured from a G7
(`tests/fixtures`, identity scrubbed) with a stand-in `curl` and `uci`. The integration tests
check the installed backend, the poller and both LuCI pages on a real router (read-only apart
from one poll), skipping the live-data checks while the G7 does not answer.

## License
Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the original authors and the
list of changes.
