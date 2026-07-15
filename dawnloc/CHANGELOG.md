# Changelog

## 0.1.0-rc.3

> [!IMPORTANT]
> **OpenWrt agent update required:** Update the DAWNLoc agent on every participating OpenWrt node. Without the RC.3 agent, the actual connected access point, channel and frequency band may remain unknown.

- Fix hostapd association detection on OpenWrt versions where `jshn` converts MAC-address object keys from `aa:bb:cc:dd:ee:ff` to `aa_bb_cc_dd_ee_ff`.
- Restore the original colon-separated MAC address before sending associations to DAWNLoc.
- Update GitHub Actions to `actions/checkout@v7` and `actions/setup-python@v6` for native Node.js 24 support.

## 0.1.0-rc.2

> [!IMPORTANT]
> **OpenWrt agent update required:** Update the DAWNLoc agent on every participating OpenWrt node after installing this release. The actual connected access point, channel and frequency band cannot be reported until the nodes run the RC.2 agent.

- Read the actual client association from hostapd and publish the connected access point, BSSID, channel and frequency band.
- Remove the estimated label from the current access-point entity and leave it unknown when no association is available.
- Allow configured devices and rooms to be renamed after setup.
- Keep device entity slugs and room IDs stable so renaming does not affect Home Assistant entities or stored fingerprints.

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
