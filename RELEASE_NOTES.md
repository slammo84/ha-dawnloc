# DAWNLoc 0.1.0-rc.3

> [!IMPORTANT]
> **Update the OpenWrt agent on every participating AP/router after installing RC.3.** Without the updated agent, DAWNLoc may continue to show an unknown access point, channel and frequency band.

## Fixed

- Fixed hostapd association detection when OpenWrt `jshn` converts MAC-address JSON keys from colon-separated form to underscore-separated shell keys.
- Restored valid MAC addresses before publishing the `associations` payload.
- Updated the CI workflow to GitHub Actions versions that run natively on Node.js 24.

## OpenWrt update

```sh
wget -O /tmp/ha-dawnloc-install.sh \
  https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt/install.sh

sh /tmp/ha-dawnloc-install.sh --update
```

After the update, restart or reload the DAWNLoc add-on if the connected AP does not appear within a few seconds.
