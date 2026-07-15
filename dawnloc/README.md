# Home Assistant App: DAWNLoc

DAWNLoc assigns Wi-Fi devices to rooms by comparing OpenWrt DAWN signal values
with fingerprints recorded during calibration.

The app provides an ingress web interface and publishes Home Assistant entities
through MQTT Discovery. Device trackers report `home` while a device is still seen on
the network and `not_home` after the offline timeout. Room detection remains separate.

This is a very early beta. Use it for convenience automations, not for alarms,
access control or other safety-related decisions.

Project: https://github.com/slammo84/ha-dawnloc
