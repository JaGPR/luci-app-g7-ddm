# SPDX-License-Identifier: Apache-2.0
"""Data-driven tests of htdocs/luci-static/resources/g7_ddm/omci.js (MIB -> OMCI cards).

The real module runs in Chromium. Objects are the G7's own mib_list output
(tests/fixtures/g7_mib_los.json, identity scrubbed) plus objects built in the
agent's format for the classes an OLT provisions (84, 131, 171).
"""
import json
import sys
import unittest
from pathlib import Path

from ddt import data, ddt, unpack

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import _browser  # noqa: E402

MODULE = ROOT / "htdocs/luci-static/resources/g7_ddm/omci.js"
MIB = json.loads((HERE / "fixtures/g7_mib_los.json").read_text())["objects"]
PAGE = None

STUB = """
window.baseclass = { extend(proto) { function C() {} Object.assign(C.prototype, proto); return C; } };
window.load = src => { const C = new Function('baseclass', src)(baseclass); return new C(); };
"""


def setUpModule():
    global PAGE
    ctx = _browser.browser().new_context()
    PAGE = ctx.new_page()
    PAGE.set_content("<html><body></body></html>")
    PAGE.add_script_tag(content=STUB)
    PAGE.evaluate("src => { window.m = load(src); }", MODULE.read_text(encoding="utf-8"))


def tearDownModule():
    PAGE.context.close()
    _browser.close()


def js(expr, arg=None):
    return PAGE.evaluate(expr, arg)


def hexs(*parts):
    """Hex data from parts: int -> one byte, (int, n) -> n bytes, str -> ASCII padded to its slot."""
    out = ""
    for p in parts:
        if isinstance(p, tuple) and isinstance(p[0], str):
            out += p[0].encode().hex().ljust(p[1] * 2, "0")
        elif isinstance(p, tuple):
            out += format(p[0], f"0{p[1] * 2}x")
        else:
            out += format(p, "02x")
    return out.ljust(128, "0")


def obj(cls, eid, data, **extra):
    return {"device": 0, "class_id": cls, "entity_id": eid, "attr_mask": 65535, "origin": 1, "name": "x",
            "data": data, "origin_name": "olt", **extra}


@ddt
class Helpers(unittest.TestCase):
    @data(("0a0b", [10, 11]), ("", []), ("abc", []), ("zz", []), (None, []))
    @unpack
    def test_bytes(self, h, want):
        self.assertEqual(js("h => m.bytes(h)", h), want)

    @data(([1, 2, 3], 0, 2, 258), ([1, 2, 3], 1, 2, 515), ([1, 2], 1, 2, None), ([255, 255, 255, 255], 0, 4, 4294967295))
    @unpack
    def test_number(self, b, off, n, want):
        self.assertEqual(js("([b, o, n]) => m.number(b, o, n)", [b, off, n]), want)

    @data((257, 2, "0x0101"), (0x8100, 2, "0x8100"), (5, 1, "0x05"))
    @unpack
    def test_hex(self, n, size, want):
        self.assertEqual(js("([n, s]) => m.hex(n, s)", [n, size]), want)

    @data(([88, 90, 0, 65], 0, 4, "XZ"), ([32, 65, 32], 0, 3, "A"), ([65, 7, 66], 0, 3, "A?B"))
    @unpack
    def test_text(self, b, off, n, want):
        self.assertEqual(js("([b, o, n]) => m.text(b, o, n)", [b, off, n]), want)

    @data(
        (15, 4096, 0, False, "no tag"), (15, 4096, 0, True, "no tag added"), (14, 4096, 0, False, "default"),
        (8, 4096, 0, False, "VID any, pbit any, TPID mode 0"), (8, 4096, 0, True, "VID copy inner, pbit copy inner, TPID mode 0"),
        (0, 1015, 4, True, "VID 1015, pbit 0, TPID mode 4"), (9, 4097, 2, True, "VID copy outer, pbit copy outer, TPID mode 2"),
        (10, 100, None, True, "VID 100, pbit from DSCP"),
    )
    @unpack
    def test_tag(self, pbit, vid, tpid, treatment, want):
        self.assertEqual(js("a => m.tag(...a)", [pbit, vid, tpid, treatment]), want)


@ddt
class RealObjects(unittest.TestCase):
    def test_cards_from_real_mib(self):
        me = js("o => m.toMe(o)", MIB)
        self.assertEqual(sorted(me), ["11", "329"], "only what this G7 has without an OLT")
        self.assertEqual(len(me["11"]["instances"]), len([o for o in MIB if o["class_id"] == 11]))

    @data(
        ("EntityID", "257 (0x0101)"), ("SensedType", "47 (10/100/1000BASE-T)"), ("AdminState", "0 (unlocked)"),
        ("OpState", "0 (enabled)"), ("BridgedOrIpInd", "2"), ("MaxFrameSize", "0"),
    )
    @unpack
    def test_ethernet_uni(self, key, want):
        first = js("o => m.toMe(o)['11'].instances[0]", MIB)
        self.assertEqual(first[key], want)

    def test_entities_sorted(self):
        ids = js("o => m.toMe(o)['11'].instances.map(i => i.EntityID)", MIB)
        self.assertEqual(ids, sorted(ids, key=lambda s: int(s.split()[0])))

    @data(("AdminState", "0 (unlocked)"), ("OpState", "0 (enabled)"), ("IanaAssignedPort", "0"))
    @unpack
    def test_veip(self, key, want):
        self.assertEqual(js("o => m.toMe(o)['329'].instances[0]", MIB)[key], want)


@ddt
class OltProvisioned(unittest.TestCase):
    @data(
        # VLAN filter from the agent's decoded entries
        (obj(84, 1, hexs((0x03f7, 2)), vlan_filter={"entries": [{"index": 0, "tci": 1015, "pbit": 0, "dei": 0, "vid": 1015}],
                                                     "forward_operation": 16, "num_entries": 1}),
         ["VLAN 1: VID 1015, pbit 0, DEI 0"]),
        # from the raw bytes when the agent sent none: two TCIs, pbit 5 on the second
        (obj(84, 2, hexs((100, 2), (0xA000 | 200, 2), *[0] * 20, 0x10, 2)), ["VLAN 1: VID 100, pbit 0, DEI 0", "VLAN 2: VID 200, pbit 5, DEI 0"]),
        (obj(84, 3, hexs(*[0] * 24, 0x10, 0)), None),
    )
    @unpack
    def test_vlan_filter(self, o, lines):
        inst = js("o => m.instance(o)", o)
        self.assertEqual(inst.get("lines"), lines)

    def test_vlan_filter_fields(self):
        inst = js("o => m.instance(o)", obj(84, 2, hexs((100, 2), *[0] * 22, 0x10, 1)))
        self.assertEqual((inst["ForwardOperation"], inst["NumberOfEntries"]), ("0x10", "1"))

    @data(
        (obj(131, 0, hexs(("ALCL", 4), ("XGS-PON-OLT", 20), ("FX-16", 14))), "0x414c434c", "XGS-PON-OLT", "FX-16"),
        (obj(131, 0, hexs(("HWTC", 4), ("MA5800", 20), ("V100R019", 14)), olt_g={"vendor_id": "ZTEG"}), "0x5a544547", "MA5800", "V100R019"),
    )
    @unpack
    def test_olt_g(self, o, vendor_hex, equipment, version):
        inst = js("o => m.instance(o)", o)
        self.assertEqual((inst["OltVendorId"], inst["EquipmentId"], inst["Version"]), (vendor_hex, equipment, version))

    RULE = {"index": 0, "delete": 0, "filter_outer_pbit": 15, "filter_outer_vid": 4096, "filter_outer_tpid_dei": 0,
            "filter_inner_pbit": 15, "filter_inner_vid": 4096, "filter_inner_tpid_dei": 0, "filter_ethertype": 0,
            "tags_to_remove": 0, "treat_outer_pbit": 15, "treat_outer_vid": 0, "treat_outer_tpid_dei": 0,
            "treat_inner_pbit": 0, "treat_inner_vid": 1015, "treat_inner_tpid_dei": 4}

    def test_extended_vlan_rule(self):
        o = obj(171, 1, hexs(2, (16, 2), (0x8100, 2), (0x8100, 2), 0, *[0] * 16, (0x0101, 2)),
                extended_vlan={"association_type": 2, "associated_me": 257, "input_tpid": 0x8100, "output_tpid": 0x8100,
                               "rules": [self.RULE, dict(self.RULE, index=1, delete=1)]})
        inst = js("o => m.instance(o)", o)
        self.assertEqual(inst["AssociationType"], "2 (PPTP Ethernet UNI)")
        self.assertEqual(inst["AssociatedMePoint"], "0x0101")
        self.assertEqual(inst["InputTpid"], "0x8100")
        self.assertEqual(inst["rules"], [{"index": 0, "filter_outer": "no tag", "filter_inner": "no tag",
                                          "treatment_outer": "remove 0 tags; no tag added",
                                          "treatment_inner": "VID 1015, pbit 0, TPID mode 4"}],
                         "untagged frames get VLAN 1015; the deleted rule is hidden")

    @data((1, "remove 1 tag; "), (2, "remove 2 tags; "), (3, "discard frame; "))
    @unpack
    def test_tags_to_remove(self, n, prefix):
        rule = js("r => m.rule(r, 0)", dict(self.RULE, tags_to_remove=n))
        self.assertTrue(rule["treatment_outer"].startswith(prefix), rule)

    def test_extended_vlan_from_bytes_only(self):
        inst = js("o => m.instance(o)", obj(171, 1, hexs(10, (16, 2), (0x8100, 2), (0x88a8, 2), 1, *[0] * 16, (0x0a01, 2))))
        self.assertEqual((inst["AssociationType"], inst["OutputTpid"], inst["AssociatedMePoint"]), ("10 (VEIP)", "0x88a8", "0x0a01"))
        self.assertNotIn("rules", inst)

    def test_all_five_cards(self):
        objs = MIB + [obj(84, 1, hexs((1015, 2), *[0] * 22, 0x10, 1)), obj(131, 0, hexs(("ALCL", 4))),
                      obj(171, 1, hexs(2), extended_vlan={"rules": [self.RULE]})]
        self.assertEqual(sorted(js("o => m.toMe(o)", objs)), ["11", "131", "171", "329", "84"])


@ddt
class Robustness(unittest.TestCase):
    @data(None, [], [None], [{"class_id": 11, "entity_id": 1, "data": "zz"}], [{"class_id": 11, "entity_id": 1}])
    def test_bad_input_does_not_throw(self, objs):
        me = js("o => m.toMe(o)", objs)
        self.assertIsInstance(me, dict)

    def test_short_data_skips_missing_fields(self):
        inst = js("o => m.instance(o)", {"class_id": 11, "entity_id": 1, "data": "0001"})
        self.assertEqual(inst, {"EntityID": "1 (0x0001)", "ExpectedType": "0", "SensedType": "1 (10BASE-T)"})


if __name__ == "__main__":
    unittest.main()
