'use strict';
'require view';
'require form';
'require rpc';
'require ui';

/*
 * Modified from luci-app-hsgq-ddm / luci-app-vsol-ddm (Apache-2.0) for the
 * TP-Link XZ000-G7 running the galachip OpenWrt firmware. See NOTICE.
 *
 * The G7 publishes its status without a login, so only its address is needed.
 */
var callTestConnection = rpc.declare({
	object: 'g7_ddm',
	method: 'test_connection',
	expect: {}
});

return view.extend({
	render: function() {
		var m, s, o;

		m = new form.Map('g7_ddm', _('G7 GPON Diagnostics Settings'),
			_('Reads the optics and GPON state of a TP-Link XZ000-G7 running the galachip OpenWrt firmware. ' +
			  'The G7 publishes them read-only without a login; a username and password are optional.'));

		s = m.section(form.NamedSection, 'main', 'g7_ddm', _('Connection Settings'));
		s.anonymous = true;
		s.addremove = false;

		o = s.option(form.Flag, 'enabled', _('Enable Telemetry Polling'),
			_('Poll the G7 in the background every 30 seconds.'));
		o.default = '1';
		o.rmempty = false;

		/* No default address: it is specific to the user's network, and a guess
		   would have the poller probing whatever device holds that address. */
		o = s.option(form.Value, 'host', _('G7 IP Address'),
			_('Management address of the G7 (its LuCI address). Required.'));
		o.datatype = 'ip4addr';
		o.rmempty = false;

		o = s.option(form.Value, 'port', _('HTTP Port'), _('Port of the G7\'s web server (default 80).'));
		o.datatype = 'port';
		o.default = '80';
		o.rmempty = false;

		/* Optional: the optics and GPON state need no login. With the G7's own
		   LuCI login the dashboard also shows system information and the OMCI
		   tables and can restart the G7. Stored in /etc/config/g7_ddm (root only). */
		o = s.option(form.Value, 'username', _('Username'),
			_('Optional: the G7\'s web interface login (usually <code>root</code>). Adds system information and the OMCI tables, and allows restarting the G7. Leave empty to use only its public status.'));
		o.placeholder = 'root';
		o.rmempty = true;

		o = s.option(form.Value, 'password', _('Password'),
			_('The password of that login. A G7 on which no password has been set yet accepts an empty one.'));
		o.password = true;
		o.rmempty = true;
		o.depends({ 'username': '', '!reverse': true });

		o = s.option(form.ListValue, 'optical_class', _('Optical Class'),
			_('Used for the labels only; the warning and alarm limits come from the G7\'s own module. In EPON mode PX20 is used automatically.'));
		o.value('bplus', _('GPON Class B+'));
		o.value('cplus', _('GPON Class C+'));
		o.default = 'bplus';

		o = s.option(form.ListValue, 'unit_system', _('Default Unit System'),
			_('Choose whether metrics display in Dual mode (°C & °F, dBm & µW), Metric only, or Imperial only.'));
		o.value('dual', _('Dual (Metric & Imperial)'));
		o.value('metric', _('Metric Only (°C, dBm)'));
		o.value('imperial', _('Imperial Only (°F, µW)'));
		o.default = 'metric';

		o = s.option(form.Value, 'timeout', _('Request Timeout (seconds)'),
			_('Time allowed for one status request to the G7 (3 to 30 seconds).'));
		o.datatype = 'range(3,30)';
		o.default = '8';

		o = s.option(form.Button, '_test', _('Test Connection'),
			_('Ask the G7 for its status now.'));
		o.inputtitle = _('Run Test');
		o.inputstyle = 'apply';
		o.onclick = function() {
			return callTestConnection().then(function(res) {
				if (res && res.connected)
					ui.addNotification(null, E('p', { class: 'alert-message success' },
						_('The G7 at %s answered with its optical and GPON status.').format(res.host || '')));
				else
					ui.addNotification(null, E('p', { class: 'alert-message warning' },
						_('Connection failed: ') + ((res && res.error) || _('No answer from the G7.'))));
			}).catch(function(err) {
				ui.addNotification(null, E('p', { class: 'alert-message warning' }, err.message || err));
			});
		};

		return m.render();
	}
});
