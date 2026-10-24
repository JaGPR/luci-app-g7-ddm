#!/bin/sh
# Removes luci-app-g7-ddm installed by install.sh.
#   wget -qO /tmp/uninstall.sh https://raw.githubusercontent.com/JaGPR/luci-app-g7-ddm/main/uninstall.sh && sh /tmp/uninstall.sh
# KEEP_CONFIG=1 keeps /etc/config/g7_ddm (the G7 address and login) for a later reinstall.
#
# Licensed under the Apache License, Version 2.0. See LICENSE and NOTICE.

[ "$(id -u)" = "0" ] || { echo "run as root" >&2; exit 1; }

/etc/init.d/g7_ddm stop 2>/dev/null
/etc/init.d/g7_ddm disable 2>/dev/null

rm -f  /usr/libexec/rpcd/g7_ddm /etc/init.d/g7_ddm \
       /usr/share/luci/menu.d/luci-app-g7-ddm.json /usr/share/rpcd/acl.d/luci-app-g7-ddm.json \
       /lib/upgrade/keep.d/luci-app-g7-ddm /etc/uci-defaults/80_luci-app-g7-ddm
rm -rf /usr/share/g7_ddm /www/luci-static/resources/g7_ddm /www/luci-static/resources/view/g7_ddm
rm -f  /tmp/g7_ddm_* /tmp/g7_ddm.lock /tmp/g7_ddm.sid
[ "$KEEP_CONFIG" = "1" ] || rm -f /etc/config/g7_ddm

rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache*
/etc/init.d/rpcd reload 2>/dev/null

echo "luci-app-g7-ddm removed.$([ "$KEEP_CONFIG" = "1" ] && echo " Config kept in /etc/config/g7_ddm.")"
