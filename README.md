# ha-dawnloc

**English** | [Deutsch](README.de.md)

![Version](https://img.shields.io/badge/version-0.1.0--rc.2-blue)
![Status](https://img.shields.io/badge/status-release%20candidate-blue)

DAWNLoc is a Home Assistant app for room-level Wi-Fi location tracking with
[OpenWrt](https://github.com/openwrt/openwrt) and
[DAWN](https://github.com/berlin-open-wireless-lab/DAWN).

It compares the signal values reported by multiple access points and determines
the most likely room for a Wi-Fi device. The result is published to Home
Assistant through MQTT Discovery.

> [!WARNING]
> DAWNLoc is a release candidate. Configuration, entities and behaviour may
> still change before the stable release.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fslammo84%2Fha-dawnloc)

## Features

- room-level detection using multiple OpenWrt access points
- DAWN hearing map processing
- automatic discovery of locatable Wi-Fi clients
- IP address, MAC address, associated AP, channel and frequency band display
- devices grouped by their detected room
- device and room names can be changed without changing their internal IDs
- location certainty indicator
- automatic Home Assistant MQTT Discovery
- German and English web interface
- fully local processing

Only clients seen by multiple physical access points are offered for setup.

## Requirements

- Home Assistant OS or another installation with app support
- Home Assistant MQTT integration and an MQTT broker
- multiple OpenWrt access points running DAWN
- a working shared DAWN hearing map
- root access to the participating OpenWrt nodes

Check the hearing map on OpenWrt with:

```sh
ubus call dawn get_hearing_map
```

## Use a fixed MAC address

Many phones, tablets and laptops use a randomized or private MAC address by
default. Disable it for your trusted home Wi-Fi on every device you want to
track. Otherwise DAWNLoc may see the same device as a new client after its MAC
address changes.

Keep private MAC addresses enabled on public or unknown Wi-Fi networks.

## Install the Home Assistant app

Use the button above or add the repository manually:

```text
Settings → Apps → App store → ⋮ → Repositories
```

```text
https://github.com/slammo84/ha-dawnloc
```

Then install and start **DAWNLoc**.

## Install the OpenWrt agent

The agent sends the DAWN hearing map, local AP information, hostapd client
associations and available DHCP client data to MQTT. Install it on every OpenWrt access point whose hostname and
radios should appear in DAWNLoc. At least one installed node should have access
to your DHCP leases so hostnames and IP addresses can be added.

Recommended installation:

```sh
wget -O /tmp/ha-dawnloc-install.sh \
  https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt/install.sh

cat /tmp/ha-dawnloc-install.sh
sh /tmp/ha-dawnloc-install.sh
```

Quick installation:

```sh
wget -qO- \
  https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt/install.sh | sh
```

The installer detects `opkg` or `apk`, installs missing dependencies, asks for
your MQTT settings, creates the UCI configuration and starts the service.

Update an existing agent without changing its MQTT configuration:

```sh
wget -O /tmp/ha-dawnloc-install.sh \
  https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt/install.sh
sh /tmp/ha-dawnloc-install.sh --update
```

## Setup

1. Add the rooms you want to distinguish.
2. Wait until locatable clients appear.
3. Add a client. Its hostname is suggested as the device name.
4. Calibrate the device in each room at typical positions.

Saved devices are grouped by their stable room. The device tracker reports `home`
while the device is still visible on the network and `not_home` after the offline timeout.
An uncertain room reading does not change presence. The last reliable room is retained for
short signal gaps and while only one access point can see the device. Deleting a device also
removes its MQTT Discovery entries and Home Assistant entities.

Access points are shown by hostname with one 2.4 GHz and one 5 GHz entry per
physical AP where available. Their names and BSSIDs are detected automatically.

## Location certainty

Location certainty shows how clearly the current readings match one room. It is
not an exact probability or precise position. Walls, furniture, people, device
hardware, power saving and radio interference can affect the result.

DAWNLoc is intended for convenience automations, not alarms, access control or
other safety-related decisions.

## Privacy

DAWNLoc works inside your own network. It does not send data to external cloud
services. Depending on your setup, it processes MAC addresses, hostnames, local
IP addresses, Wi-Fi signal values, room assignments and timestamps.

Do not track people or devices without permission.

DAWNLoc is an independent project and is not officially affiliated with
OpenWrt, DAWN or Home Assistant.

## Author

**slammo84**

## License

[Apache License 2.0](LICENSE)
