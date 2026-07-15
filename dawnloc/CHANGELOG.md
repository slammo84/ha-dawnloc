# Changelog

## 0.1.0-rc.1

- Group signal measurements by physical access point and frequency band before matching them against room fingerprints.
- Prevent multiple SSIDs or BSSIDs on the same radio from giving an access point additional weight.
- Use a weighted nearest-neighbour comparison across multiple fingerprints and reject weak or ambiguous matches.
- Keep the last reliable room during short signal gaps and while only one access point remains visible.
- Leave newly detected single-AP devices without a room until a reliable multi-AP match is available.
- Require a configurable confidence threshold before switching an existing device to another room.
- Track Home Assistant presence independently from room detection and report `not_home` only after the offline timeout.
- Show the IP address, estimated current access point, channel and frequency band for configured devices.
- Keep existing BSSID-based fingerprints compatible while storing new fingerprints in the grouped format.

## 0.0.1-beta.3

- Fix installation on fresh OpenWrt nodes by creating `/etc/config/dawnloc` before writing the UCI configuration.
- Suppress harmless UCI `Entry not found` messages during first-time setup.
- Start the service cleanly on first installation instead of restarting a service that is not registered yet.
- Keep update and repair installations restarting an existing DAWNLoc service.
- Confirm compatibility with OpenWrt 25.12 and the `apk` package manager.

## 0.0.1-beta.2

- Resolve client hostnames and IP addresses from DHCP leases, static UCI host entries and the neighbour table.
- Publish each OpenWrt node's hostname together with its local BSSIDs and frequency bands.
- Group BSSIDs by physical access point and frequency band.
- Count only known physical access points when deciding whether a client is locatable.
- Hide unknown BSSIDs from the access-point overview and prevent inflated AP counts.
