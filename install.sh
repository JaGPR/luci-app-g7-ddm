#!/bin/sh
# luci-app-g7-ddm installer for OpenWrt (no SDK, no package signing needed).
#
#   wget -qO /tmp/install.sh https://raw.githubusercontent.com/JaGPR/luci-app-g7-ddm/main/install.sh && sh /tmp/install.sh
#
# Environment overrides:
#   REPO=user/luci-app-g7-ddm   GitHub repository to install from
#   BRANCH=main                   branch or tag
#   TARBALL=/tmp/x.tar.gz         install from a local archive instead of GitHub
#   DRY_RUN=1                     print every step, change nothing
#
# Licensed under the Apache License, Version 2.0. See LICENSE and NOTICE.

set -e

REPO="${REPO:-JaGPR/luci-app-g7-ddm}"
BRANCH="${BRANCH:-main}"
WORK="/tmp/g7-ddm-install.$$"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; rm -rf "$WORK"; exit 1; }
run()  { if [ "$DRY_RUN" = "1" ]; then echo "    [dry-run] $*"; else eval "$@"; fi; }

[ "$(id -u)" = "0" ] || die "run this as root on the OpenWrt router"
[ -f /etc/openwrt_release ] || die "this does not look like OpenWrt (/etc/openwrt_release missing)"
command -v uci >/dev/null    || die "uci not found"
[ -d /www/luci-static ]      || die "LuCI is not installed (install luci first)"

mkdir -p "$WORK"

# 1. Fetch the source
if [ -n "$TARBALL" ]; then
	say "Using local archive $TARBALL"
	cp "$TARBALL" "$WORK/src.tar.gz" || die "cannot read $TARBALL"
else
	URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
	say "Downloading $REPO ($BRANCH)"
	wget -qO "$WORK/src.tar.gz" "$URL" || die "download failed: $URL (is HTTPS support installed? try: apk add ca-bundle / opkg install ca-bundle)"
fi
tar -xzf "$WORK/src.tar.gz" -C "$WORK" || die "archive is not a valid .tar.gz"
SRC="$(find "$WORK" -maxdepth 2 -type f -name Makefile -path '*g7-ddm*' | head -1 | xargs dirname 2>/dev/null)"
[ -n "$SRC" ] && [ -f "$SRC/root/usr/libexec/rpcd/g7_ddm" ] || die "archive does not contain luci-app-g7-ddm"

# 2. Install files (config is only created if it does not exist yet)
say "Installing files"
run "mkdir -p /usr/libexec/rpcd /usr/share/g7_ddm /www/luci-static/resources/g7_ddm /www/luci-static/resources/view/g7_ddm /etc/init.d /etc/config /usr/share/luci/menu.d /usr/share/rpcd/acl.d /lib/upgrade/keep.d"
run "cp '$SRC/root/usr/libexec/rpcd/g7_ddm' /usr/libexec/rpcd/g7_ddm"
run "cp '$SRC'/root/usr/share/g7_ddm/*.awk /usr/share/g7_ddm/"
run "cp '$SRC'/htdocs/luci-static/resources/g7_ddm/*.js /www/luci-static/resources/g7_ddm/"
run "cp '$SRC'/htdocs/luci-static/resources/view/g7_ddm/*.js /www/luci-static/resources/view/g7_ddm/"
run "cp '$SRC/root/etc/init.d/g7_ddm' /etc/init.d/g7_ddm"
run "cp '$SRC/root/usr/share/luci/menu.d/luci-app-g7-ddm.json' /usr/share/luci/menu.d/"
run "cp '$SRC/root/usr/share/rpcd/acl.d/luci-app-g7-ddm.json' /usr/share/rpcd/acl.d/"
run "cp '$SRC/root/lib/upgrade/keep.d/luci-app-g7-ddm' /lib/upgrade/keep.d/"
if [ -f /etc/config/g7_ddm ]; then
	say "Keeping existing /etc/config/g7_ddm (your G7 address and login are preserved)"
else
	run "cp '$SRC/root/etc/config/g7_ddm' /etc/config/g7_ddm"
fi
run "chmod 755 /usr/libexec/rpcd/g7_ddm /etc/init.d/g7_ddm"
run "chmod 600 /etc/config/g7_ddm"
run "chmod 644 /usr/share/g7_ddm/*.awk /www/luci-static/resources/g7_ddm/*.js /www/luci-static/resources/view/g7_ddm/*.js /usr/share/luci/menu.d/luci-app-g7-ddm.json /usr/share/rpcd/acl.d/luci-app-g7-ddm.json /lib/upgrade/keep.d/luci-app-g7-ddm"

# 3. Seed defaults (never overwrites existing values), register with rpcd, start
say "Applying defaults and registering with LuCI"
run "sh '$SRC/root/etc/uci-defaults/80_luci-app-g7-ddm'"
run "/etc/init.d/rpcd reload"

rm -rf "$WORK"

say "Done."
cat <<'EOF'

  Next steps:
   1. Log out of LuCI and log back in (new menu permissions are granted at login).
   2. Open  Status -> G7 GPON DDM -> Settings
      - G7 IP address: its management address (its own LuCI address)
      - Save & Apply, then press "Test connection"
   3. Open  Status -> G7 GPON DDM -> Optical Diagnostics

  The G7 publishes its optics and GPON state without a login. Its username and
  password (optional, in Settings) add system information, the OMCI tables and
  restart. The router must be able to reach the G7's address.
EOF
