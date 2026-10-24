#
# luci-app-g7-ddm - optical diagnostics for the TP-Link XZ000-G7 (galachip OpenWrt firmware).
#
# Modified from luci-app-vsol-ddm (https://github.com/AliLostInTheDark/luci-app-vsol-ddm).
# Licensed under the Apache License, Version 2.0. See LICENSE and NOTICE.
#

include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-g7-ddm
PKG_VERSION:=1.0.0
PKG_RELEASE:=1

PKG_LICENSE:=Apache-2.0
PKG_LICENSE_FILES:=LICENSE NOTICE
PKG_MAINTAINER:=JaGPR (https://github.com/JaGPR)
PKG_URL:=https://github.com/JaGPR/luci-app-g7-ddm

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)

include $(INCLUDE_DIR)/package.mk

# Shell + awk and the router's own HTTP client (uclient-fetch, or curl): no compiled
# component, so one package installs on every architecture.
define Package/luci-app-g7-ddm
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=TP-Link XZ000-G7 GPON Optical Diagnostics & DDM Monitor
  DEPENDS:=+luci-base
  PKGARCH:=all
endef

define Package/luci-app-g7-ddm/description
  LuCI dashboard for a TP-Link XZ000-G7 GPON ONT running the galachip OpenWrt
  firmware: optical DDM (Rx/Tx power, temperature, voltage, bias) with the
  module's own alarm limits, GPON state, ONU-ID, OLT profile, LOS alarm and
  history charts. Read over HTTP from the G7's public status: no login needed.
endef

# Kept across package upgrade. Sysupgrade retention is handled by
# /lib/upgrade/keep.d/luci-app-g7-ddm, installed below.
define Package/luci-app-g7-ddm/conffiles
/etc/config/g7_ddm
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
endef

define Build/Compile
endef

define Package/luci-app-g7-ddm/install
	$(INSTALL_DIR) $(1)/usr/share/g7_ddm
	$(INSTALL_DATA) ./root/usr/share/g7_ddm/* $(1)/usr/share/g7_ddm/

	$(INSTALL_DIR) $(1)/www/luci-static/resources/view/g7_ddm
	$(INSTALL_DATA) ./htdocs/luci-static/resources/view/g7_ddm/* $(1)/www/luci-static/resources/view/g7_ddm/

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./root/etc/init.d/g7_ddm $(1)/etc/init.d/g7_ddm

	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./root/etc/config/g7_ddm $(1)/etc/config/g7_ddm

	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./root/etc/uci-defaults/80_luci-app-g7-ddm $(1)/etc/uci-defaults/

	$(INSTALL_DIR) $(1)/lib/upgrade/keep.d
	$(INSTALL_DATA) ./root/lib/upgrade/keep.d/luci-app-g7-ddm $(1)/lib/upgrade/keep.d/luci-app-g7-ddm

	$(INSTALL_DIR) $(1)/usr/libexec/rpcd
	$(INSTALL_BIN) ./root/usr/libexec/rpcd/g7_ddm $(1)/usr/libexec/rpcd/g7_ddm

	$(INSTALL_DIR) $(1)/usr/share/luci/menu.d
	$(INSTALL_DATA) ./root/usr/share/luci/menu.d/luci-app-g7-ddm.json $(1)/usr/share/luci/menu.d/

	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) ./root/usr/share/rpcd/acl.d/luci-app-g7-ddm.json $(1)/usr/share/rpcd/acl.d/
endef

define Package/luci-app-g7-ddm/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache* /tmp/g7_ddm_cache.json
	/etc/init.d/rpcd reload 2>/dev/null || true
}
exit 0
endef

define Package/luci-app-g7-ddm/prerm
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	/etc/init.d/g7_ddm stop 2>/dev/null || true
	/etc/init.d/g7_ddm disable 2>/dev/null || true
}
exit 0
endef

define Package/luci-app-g7-ddm/postrm
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache* /tmp/g7_ddm_*
	/etc/init.d/rpcd reload 2>/dev/null || true
}
exit 0
endef

$(eval $(call BuildPackage,luci-app-g7-ddm))
