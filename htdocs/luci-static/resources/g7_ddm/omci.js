'use strict';
'require baseclass';

/*
 * The G7's OMCI MIB (omci.agent mib_list) -> the dashboard's OMCI cards.
 *
 * Each object carries its attributes as hex in ITU-T G.988 attribute order,
 * plus decoded structures for some classes (olt_g, vlan_filter, extended_vlan).
 * The cards show five classes; this turns their objects into the
 * { me: { <class>: { instances: [ { EntityID, Field: value, ..., rules?, lines? } ] } } }
 * shape the luci-app-hsgq-ddm dashboard renders.
 *
 * Pure functions only (unit tested in tests/test_omci.py).
 */

var ADMIN = { 0: 'unlocked', 1: 'locked' };
var OPER = { 0: 'enabled', 1: 'disabled' };
var ASSOCIATION = { 0: 'MAC bridge port', 1: '802.1p mapper', 2: 'PPTP Ethernet UNI', 3: 'IP host', 4: 'PPTP xDSL',
	5: 'GEM IWTP', 6: 'multicast GEM IWTP', 7: 'PPTP MoCA', 9: 'Ethernet flow TP', 10: 'VEIP' };
var SENSED = { 0: 'none', 1: '10BASE-T', 2: '100BASE-T', 3: '10/100BASE-T', 47: '10/100/1000BASE-T', 48: '1000BASE-T' };

/* [ field, byte offset, length, format ] in G.988 attribute order */
var LAYOUTS = {
	11: [ [ 'ExpectedType', 0, 1 ], [ 'SensedType', 1, 1, SENSED ], [ 'AutoDetectionConfig', 2, 1 ],
	      [ 'EthernetLoopbackConfig', 3, 1 ], [ 'AdminState', 4, 1, ADMIN ], [ 'OpState', 5, 1, OPER ],
	      [ 'ConfigurationInd', 6, 1 ], [ 'MaxFrameSize', 7, 2 ], [ 'DteOrDceInd', 9, 1 ], [ 'PauseTime', 10, 2 ],
	      [ 'BridgedOrIpInd', 12, 1 ], [ 'Arc', 13, 1 ], [ 'ArcInterval', 14, 1 ], [ 'PppoeFilter', 15, 1 ],
	      [ 'PowerControl', 16, 1 ] ],
	84: [ [ 'ForwardOperation', 24, 1, 'hex' ], [ 'NumberOfEntries', 25, 1 ] ],
	131: [ [ 'OltVendorId', 0, 4, 'hex' ], [ 'EquipmentId', 4, 20, 'str' ], [ 'Version', 24, 14, 'str' ],
	       [ 'TimeOfDayInfo', 38, 14, 'hex' ] ],
	171: [ [ 'AssociationType', 0, 1, ASSOCIATION ], [ 'ReceivedFrameVlanTagOperTableMaxSize', 1, 2 ],
	       [ 'InputTpid', 3, 2, 'hex' ], [ 'OutputTpid', 5, 2, 'hex' ], [ 'DownstreamMode', 7, 1 ],
	       [ 'AssociatedMePoint', 24, 2, 'hex' ] ],
	329: [ [ 'AdminState', 0, 1, ADMIN ], [ 'OpState', 1, 1, OPER ], [ 'InterdomainName', 2, 25, 'str' ],
	       [ 'TcpUdpPointer', 27, 2, 'hex' ], [ 'IanaAssignedPort', 29, 2 ] ]
};

var CLASSES = [ 11, 84, 171, 329, 131 ];

/* Who created an object: the agent reports it as origin_name. Firmware defaults
   (e.g. VLAN filters for VID 100 / 660 on a local bridge) are not part of the
   ISP's service, so they are labelled and listed after the OLT's objects. */
var SOURCES = { olt: 'OLT (ISP service)', 'default': 'Firmware default, not from the OLT', local: 'Set on this G7', hardware: 'Hardware' };
var SOURCE_ORDER = { olt: 0, local: 1, hardware: 2, 'default': 3 };

return baseclass.extend({
	LAYOUTS: LAYOUTS,

	/* Bytes of a hex string; [] for anything else. */
	bytes: function(hex) {
		if (typeof hex != 'string' || !/^([0-9a-fA-F]{2})*$/.test(hex))
			return [];
		var out = [];
		for (var i = 0; i < hex.length; i += 2)
			out.push(parseInt(hex.substr(i, 2), 16));
		return out;
	},

	/* Big-endian number of len bytes at off, or null past the end. */
	number: function(b, off, len) {
		if (off + len > b.length)
			return null;
		var n = 0;
		for (var i = 0; i < len; i++)
			n = n * 256 + b[off + i];
		return n;
	},

	hex: function(n, len) {
		var s = Number(n).toString(16);
		while (s.length < len * 2)
			s = '0' + s;
		return '0x' + s;
	},

	/* Printable ASCII up to the first NUL, trimmed. */
	text: function(b, off, len) {
		var s = '';
		for (var i = off; i < off + len && i < b.length && b[i]; i++)
			s += (b[i] >= 32 && b[i] < 127) ? String.fromCharCode(b[i]) : '?';
		return s.trim();
	},

	field: function(b, spec) {
		var off = spec[1], len = spec[2], fmt = spec[3];
		if (fmt == 'str')
			return off < b.length ? this.text(b, off, len) : null;
		var n = this.number(b, off, len);
		if (n == null)
			return null;
		if (fmt == 'hex')
			return this.hex(n, len);
		if (fmt && typeof fmt == 'object')
			return fmt[n] != null ? n + ' (' + fmt[n] + ')' : String(n);
		return String(n);
	},

	/* One VLAN tag of a class 171 rule, as the agent's own formatter words it. */
	tag: function(pbit, vid, tpid, treatment) {
		if (pbit == 15)
			return treatment ? 'no tag added' : 'no tag';
		if (!treatment && pbit == 14)
			return 'default';
		var p = pbit == 8 ? (treatment ? 'copy inner' : 'any') : pbit == 9 ? 'copy outer' : pbit == 10 ? 'from DSCP' : String(pbit);
		var v = vid == 4096 ? (treatment ? 'copy inner' : 'any') : vid == 4097 ? 'copy outer' : String(vid);
		return 'VID ' + v + ', pbit ' + p + (tpid != null ? ', TPID mode ' + tpid : '');
	},

	rule: function(r, i) {
		var remove = r.tags_to_remove == 3 ? 'discard frame' : 'remove ' + (r.tags_to_remove || 0) + ' tag' + (r.tags_to_remove == 1 ? '' : 's');
		return {
			index: r.index != null ? r.index : i + 1,
			filter_outer: this.tag(r.filter_outer_pbit, r.filter_outer_vid, r.filter_outer_tpid_dei),
			filter_inner: this.tag(r.filter_inner_pbit, r.filter_inner_vid, r.filter_inner_tpid_dei) +
				(r.filter_ethertype ? ' (ethertype mode ' + r.filter_ethertype + ')' : ''),
			treatment_outer: remove + '; ' + this.tag(r.treat_outer_pbit, r.treat_outer_vid, r.treat_outer_tpid_dei, true),
			treatment_inner: this.tag(r.treat_inner_pbit, r.treat_inner_vid, r.treat_inner_tpid_dei, true)
		};
	},

	/* One MIB object -> one card instance. */
	instance: function(o) {
		var b = this.bytes(o.data), inst = { EntityID: o.entity_id + ' (' + this.hex(o.entity_id, 2) + ')' };
		if (o.origin_name)
			inst.Source = SOURCES[o.origin_name] || o.origin_name;
		var self = this;

		(LAYOUTS[o.class_id] || []).forEach(function(spec) {
			var v = self.field(b, spec);
			if (v != null && v !== '')
				inst[spec[0]] = v;
		});

		if (o.class_id == 84) {
			var entries = (o.vlan_filter && o.vlan_filter.entries) || null, lines = [];
			if (!entries) {
				entries = [];
				for (var i = 0; i < Math.min(self.number(b, 25, 1) || 0, 12); i++) {
					var tci = self.number(b, i * 2, 2);
					entries.push({ vid: tci & 0xfff, pbit: tci >> 13, dei: (tci >> 12) & 1 });
				}
			}
			entries.forEach(function(e, i) {
				lines.push('VLAN ' + (i + 1) + ': VID ' + e.vid + ', pbit ' + e.pbit + ', DEI ' + (e.dei || 0));
			});
			if (lines.length)
				inst.lines = lines;
		}

		if (o.class_id == 171 && o.extended_vlan) {
			var x = o.extended_vlan;
			if (x.association_type != null)
				inst.AssociationType = x.association_type + (ASSOCIATION[x.association_type] ? ' (' + ASSOCIATION[x.association_type] + ')' : '');
			if (x.associated_me != null)
				inst.AssociatedMePoint = self.hex(x.associated_me, 2);
			if (x.input_tpid != null)
				inst.InputTpid = self.hex(x.input_tpid, 2);
			if (x.output_tpid != null)
				inst.OutputTpid = self.hex(x.output_tpid, 2);
			inst.rules = (x.rules || []).filter(function(r) { return !r.delete; }).map(function(r, i) { return self.rule(r, i); });
		}

		if (o.class_id == 131 && o.olt_g && typeof o.olt_g.vendor_id == 'string' && o.olt_g.vendor_id.length == 4) {
			var h = '0x';
			for (var k = 0; k < 4; k++)
				h += ('0' + o.olt_g.vendor_id.charCodeAt(k).toString(16)).slice(-2);
			inst.OltVendorId = h;
		}

		return inst;
	},

	/* mib_list objects -> { me: { '<class>': { instances: [...] } } } for the cards. */
	toMe: function(objects) {
		var me = {}, self = this;

		CLASSES.forEach(function(c) {
			var list = (objects || []).filter(function(o) { return o && o.class_id == c; })
				.sort(function(a, b) {
					var oa = SOURCE_ORDER[a.origin_name], ob = SOURCE_ORDER[b.origin_name];
					oa = oa == null ? 1 : oa; ob = ob == null ? 1 : ob;
					return oa - ob || a.entity_id - b.entity_id;
				});
			if (list.length)
				me[String(c)] = { instances: list.map(function(o) { return self.instance(o); }) };
		});

		return me;
	}
});
