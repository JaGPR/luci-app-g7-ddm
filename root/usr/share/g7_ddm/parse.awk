# G7 DDM parser: the G7's public ubus status (JSON-RPC over HTTP) -> dashboard JSON.
#
# Input: the reply to one batched JSON-RPC request with two calls,
#   xpon.public status   optics (nW, m°C, µV, µA) and the module's own alarm limits
#   omci.agent  status   GPON state, ONU-ID, identity, OLT profile, MIB size
# Both are readable without a login on the G7 (its "unauthenticated" ACL).
#
# Output: one JSON object in the same shape as luci-app-vsol-ddm and
# luci-app-hsgq-ddm caches (success, ddm, onu, device, thresholds), so the same
# dashboard and the Home NOC read it unchanged.
#
# Variables: host, ts (unix time), req_class (bplus | cplus | epon_px20 | auto)
#
# Portable awk only (BusyBox, mawk, gawk): no gensub, no arrays of arrays.

function val(key,    re, s) {
	re = "\"" key "\"[ \t]*:[ \t]*(\"[^\"]*\"|-?[0-9.]+|true|false|null)"
	if (!match(ALL, re))
		return ""
	s = substr(ALL, RSTART, RLENGTH)
	sub(/^"[^"]*"[ \t]*:[ \t]*/, "", s)
	gsub(/"/, "", s)
	return s == "null" ? "" : s
}

function num(s) { return (s ~ /^-?[0-9]+(\.[0-9]+)?$/) }

# Natural logarithm without awk's math library: some BusyBox builds have no log().
# Scale x into [1, 2) by powers of two, then ln(x) = 2 atanh((x-1)/(x+1)) as a
# series, which converges fast there (|y| <= 1/3).
function ln(x,    j, y, y2, s, t, k) {
	j = 0
	while (x >= 2) { x /= 2; j++ }
	while (x < 1) { x *= 2; j-- }
	y = (x - 1) / (x + 1); y2 = y * y; s = 0; t = y
	for (k = 1; k <= 41; k += 2) { s += t / k; t *= y2 }
	return 2 * s + j * 0.6931471805599453
}

# nW -> dBm with two decimals; "null" when there is no light or no value
function dbm(nw) {
	if (!num(nw) || nw + 0 <= 0)
		return "null"
	return sprintf("%.2f", 10 * ln(nw / 1000000) / 2.302585092994046)
}

function scaled(v, div, fmt) { return num(v) ? sprintf(fmt, v / div) : "null" }

function js(s) { gsub(/\\/, "\\\\", s); gsub(/"/, "\\\"", s); return "\"" s "\"" }
function jsn(s) { return s == "" ? "null" : js(s) }
function jn(v) { return (v == "" || v == "null") ? "null" : v }

BEGIN { ALL = "" }
{ ALL = ALL $0 " " }

END {
	if (ALL !~ /"jsonrpc"/ || ALL !~ /"temp_mc"/) {
		printf "{\"success\": false, \"connected\": false, \"host\": %s, \"error\": \"The G7 at %s did not return its status (xpon.public)\"}\n", js(host), host
		exit
	}

	mode = val("mode")
	rx_nw = val("rx_nw"); tx_nw = val("tx_nw")
	rx = dbm(rx_nw); tx = dbm(tx_nw)
	temp = scaled(val("temp_mc"), 1000, "%.2f")
	volt = scaled(val("vcc_uv"), 1000000, "%.2f")
	bias = scaled(val("bias_ua"), 1000, "%.2f")

	# the module's own limits (nW)
	rla = val("rx_alarm_low_nw"); rlw = val("rx_warn_low_nw")
	rhw = val("rx_warn_high_nw"); rha = val("rx_alarm_high_nw")
	tla = val("tx_alarm_low_nw"); tlw = val("tx_warn_low_nw")
	thw = val("tx_warn_high_nw"); tha = val("tx_alarm_high_nw")

	# EPON when the ONU runs in EPON mode, else the requested GPON class
	cls = req_class
	if (mode == "epon")
		cls = "epon_px20"
	else if (cls != "bplus" && cls != "cplus")
		cls = "bplus"
	citation = (cls == "epon_px20") ? "IEEE 802.3 1000BASE-PX20-U" : (cls == "cplus") ? "ITU-T G.984.2 Class C+" : "ITU-T G.984.2 Class B+"
	wl_rx = (cls == "epon_px20") ? 1490 : 1490
	wl_tx = 1310

	# GPON state from the OMCI agent: 1..7 = O1..O7
	st = val("state")
	ostate = (num(st) && st >= 1 && st <= 7) ? "O" st : ""
	split("Initial State,Standby State,Serial Number State,Ranging State,Operation State,POPUP State,Emergency Stop State", SN, ",")
	state_raw = ostate != "" ? SN[st + 0] " (" ostate ")" : ""
	if (mode == "epon")
		registered = (val("channel_up") == "true") ? "Registered (EPON)" : "Not Registered (EPON)"
	else
		registered = ostate == "O5" ? "Registered (O5)" : (ostate != "" ? "Not Registered (" ostate ")" : "")

	# LOS: no light, or below the module's own low-power alarm
	dark = (!num(rx_nw) || rx_nw + 0 <= 0 || (num(rla) && rx_nw + 0 < rla + 0))
	alos = dark ? "Active (LOS Alarm)" : "Clear (Normal)"

	onu_id = val("onu_id")
	if (num(onu_id) && onu_id + 0 >= 255)
		onu_id = ""

	printf "{\n"
	printf "  \"success\": true,\n  \"connected\": true,\n  \"configured\": true,\n"
	printf "  \"host\": %s,\n  \"timestamp\": %s,\n", js(host), ts
	printf "  \"optical_class\": %s,\n  \"optical_class_source\": \"module\",\n", js(cls)
	printf "  \"pon_mode\": %s,\n", jsn(mode)

	printf "  \"ddm\": {\n"
	printf "    \"rx_power_dbm\": %s,\n    \"tx_power_dbm\": %s,\n", rx, tx
	printf "    \"temperature_c\": %s,\n    \"voltage_v\": %s,\n    \"bias_current_ma\": %s,\n", temp, volt, bias
	printf "    \"rx_power_nw\": %s,\n    \"tx_power_nw\": %s,\n", jn(rx_nw), jn(tx_nw)
	printf "    \"module_alarms\": %s,\n", jsn(val("alarms"))
	printf "    \"vendor_name\": %s,\n    \"part_number\": %s,\n", jsn(val("vendor_id")), jsn(val("equipment_id"))
	printf "    \"wavelength_rx\": \"%d nm\",\n    \"wavelength_tx\": \"%d nm\",\n", wl_rx, wl_tx
	printf "    \"wavelength_rx_nm\": %d,\n    \"wavelength_tx_nm\": %d,\n", wl_rx, wl_tx
	printf "    \"optical_budget_class\": %s\n", js(citation)
	printf "  },\n"

	printf "  \"onu\": {\n"
	printf "    \"state\": %s,\n    \"state_raw\": %s,\n    \"registered_status\": %s,\n", jsn(ostate), jsn(state_raw), jsn(registered)
	printf "    \"serial_number\": %s,\n    \"onu_id\": %s,\n", jsn(val("serial")), jn(onu_id)
	printf "    \"olt_profile\": %s,\n    \"onu_type\": %s,\n", jsn(val("olt_profile_effective_name")), jsn(val("onu_type_name"))
	printf "    \"omci_agent\": %s,\n", val("agent_operational") == "1" ? "\"operational\"" : "\"waiting for the OLT\""
	printf "    \"mib_objects\": %s,\n    \"omci_messages\": %s,\n", jn(val("mib_objects")), jn(val("responses"))
	printf "    \"alarm_los\": %s\n", js(alos)
	printf "  },\n"

	printf "  \"device\": {\n"
	printf "    \"model\": %s,\n    \"vendor\": \"TP-Link\",\n", jsn(val("hardware_version"))
	printf "    \"firmware\": \"OpenWrt (galachip)\",\n    \"hardware\": \"GalaChip GC1601\",\n"
	printf "    \"rx_packets\": %s,\n    \"tx_packets\": %s,\n    \"rx_bytes\": %s,\n    \"tx_bytes\": %s\n", \
		jn(val("rx_packets")), jn(val("tx_packets")), jn(val("rx_bytes")), jn(val("tx_bytes"))
	printf "  },\n"

	printf "  \"thresholds\": {\n"
	printf "    \"class\": %s,\n    \"citation\": %s,\n    \"sff_citation\": \"module (BOSA) limits\",\n", js(cls), js(citation)
	printf "    \"wavelength_rx_nm\": %d,\n    \"wavelength_tx_nm\": %d,\n", wl_rx, wl_tx
	printf "    \"rx_sensitivity_dbm\": %s,\n    \"rx_overload_dbm\": %s,\n", dbm(rla), dbm(rha)
	printf "    \"tx_min_dbm\": %s,\n    \"tx_max_dbm\": %s,\n", dbm(tla), dbm(tha)
	printf "    \"rx_pwr_low_alarm\": %s,\n    \"rx_pwr_low_warn\": %s,\n", dbm(rla), dbm(rlw)
	printf "    \"rx_pwr_high_warn\": %s,\n    \"rx_pwr_high_alarm\": %s,\n", dbm(rhw), dbm(rha)
	printf "    \"tx_pwr_low_alarm\": %s,\n    \"tx_pwr_low_warn\": %s,\n", dbm(tla), dbm(tlw)
	printf "    \"tx_pwr_high_warn\": %s,\n    \"tx_pwr_high_alarm\": %s,\n", dbm(thw), dbm(tha)
	# temperature, voltage and bias limits are not published by the module: SFF-8472 class values
	printf "    \"temp_low_alarm\": -40.0,\n    \"temp_low_warn\": 0.0,\n    \"temp_high_warn\": 65.0,\n    \"temp_high_alarm\": 70.0,\n"
	printf "    \"voltage_low_alarm\": 2.95,\n    \"voltage_low_warn\": 3.02,\n    \"voltage_high_warn\": 3.57,\n    \"voltage_high_alarm\": 3.65,\n"
	printf "    \"bias_low_alarm\": 0.0,\n    \"bias_low_warn\": 2.0,\n    \"bias_high_warn\": 30.0,\n    \"bias_high_alarm\": 40.0\n"
	printf "  }\n"
	printf "}\n"
}
