# DAWNLoc

DAWNLoc determines the most likely room of a Wi-Fi device from signal values
reported by multiple OpenWrt access points running DAWN.

## Requirements

- Home Assistant with app support
- MQTT integration and an MQTT broker
- multiple OpenWrt access points running DAWN
- the DAWNLoc OpenWrt agent on the participating nodes
- a fixed MAC address for each tracked device on your home Wi-Fi

## Setup

1. Install and start the DAWNLoc app.
2. Run `dawnloc/openwrt/install.sh` on the participating OpenWrt nodes.
3. Add the rooms you want to distinguish.
4. Add a client after it is visible to multiple physical access points.
5. Record fingerprints in each room at typical device positions.

The web interface shows access points by hostname and groups saved devices by
their detected room. Deleting a device also removes its MQTT Discovery entries.

## Home Assistant entities

For every configured device, MQTT Discovery creates a device tracker and sensors
for the stable room, current room candidate, location certainty, estimated current AP,
channel, frequency band, visible AP count and last-seen timestamp. The tracker reports
`home` while the device is still seen on the network and `not_home` after the offline timeout.

## Limitations

Wi-Fi signal values are affected by walls, furniture, people, power saving,
roaming and device hardware. DAWNLoc provides an approximate room assignment,
not precise positioning.

Do not track people or devices without permission.
