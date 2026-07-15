// SPDX-FileCopyrightText: 2026 slammo84
// SPDX-License-Identifier: Apache-2.0

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>'"]/g,
  (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character],
);

let currentCalibration = null;
let currentLanguage = "de";
let translations = {};
let discoveredClients = new Map();
let configuredDevices = new Map();
let configuredRooms = new Map();
let accessPointRooms = new Map();

function lookup(key) {
  return key.split(".").reduce((value, part) => value?.[part], translations);
}

function t(key, variables = {}) {
  let value = lookup(key);
  if (typeof value !== "string") {
    value = key;
  }
  return value.replace(/\{(\w+)\}/g, (_match, name) => variables[name] ?? `{${name}}`);
}

function detectLanguage() {
  const saved = window.localStorage.getItem("dawnloc-language");
  if (saved === "de" || saved === "en") {
    return saved;
  }
  return navigator.language.toLowerCase().startsWith("de") ? "de" : "en";
}

async function loadLanguage(language) {
  const response = await fetch(`assets/locales/${language}.json`);
  if (!response.ok) {
    throw new Error(`Unable to load language: ${language}`);
  }
  translations = await response.json();
  currentLanguage = language;
  document.documentElement.lang = language;
  byId("languageSelect").value = language;
  window.localStorage.setItem("dawnloc-language", language);
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
}

async function api(path, options = {}) {
  const response = await fetch(`api/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.ok) {
    return response.json();
  }

  let message = response.statusText;
  try {
    const body = await response.json();
    message = body.detail || message;
  } catch (_error) {
    message = (await response.text()) || message;
  }
  throw new Error(lookup(message) ? t(message) : message);
}

function relativeAgeSeconds(seconds) {
  if (seconds === null || seconds === undefined) {
    return t("time.never");
  }
  const rounded = Math.max(0, Math.round(Number(seconds)));
  const formatter = new Intl.RelativeTimeFormat(currentLanguage, { numeric: "always" });
  if (rounded < 60) {
    return formatter.format(-rounded, "second");
  }
  if (rounded < 3600) {
    return formatter.format(-Math.round(rounded / 60), "minute");
  }
  if (rounded < 86400) {
    return formatter.format(-Math.round(rounded / 3600), "hour");
  }
  return formatter.format(-Math.round(rounded / 86400), "day");
}

function relativeTimestamp(timestamp) {
  if (!timestamp) {
    return t("time.never");
  }
  return relativeAgeSeconds(Date.now() / 1000 - timestamp);
}

function certaintyLabel(confidence) {
  if (confidence >= 75) {
    return t("certainty.high");
  }
  if (confidence >= 45) {
    return t("certainty.medium");
  }
  return t("certainty.low");
}

function renderStatus(status) {
  byId("status").innerHTML = `
    <span class="pill">
      <span class="dot ${status.mqtt_connected ? "ok" : ""}"></span>
      ${t(status.mqtt_connected ? "status.mqtt_connected" : "status.mqtt_disconnected")}
    </span>
    <span class="pill">${t("status.source")}: ${escapeHtml(status.source_node || t("common.none_yet"))}</span>
    <span class="pill">${t("status.last_data")}: ${relativeTimestamp(status.last_raw_message)}</span>
    <span class="pill">${t("status.fingerprints", { count: status.fingerprint_count })}</span>
    <span class="pill">v${escapeHtml(status.version)}</span>`;
}

function deviceRoom(device) {
  if (device.offline) {
    return { key: "~offline", label: t("locations.not_seen") };
  }
  if (device.stable_room) {
    return { key: device.stable_room.toLocaleLowerCase(), label: device.stable_room };
  }
  return { key: "~unknown", label: t("locations.unknown") };
}

function renderDeviceCard(device) {
  const confidence = Math.max(0, Math.min(100, Number(device.confidence || 0)));
  const vectorRows = Object.entries(device.vector || {})
    .map(([ap, rssi]) => `<tr><td>${escapeHtml(ap)}</td><td>${rssi} dBm</td></tr>`)
    .join("");
  const ipAddress = device.ip_address || t("common.unknown_ip");
  const currentAp = device.current_ap || t("common.unknown_ap");
  const currentChannel = device.current_channel || t("common.unknown");
  const currentBand = device.current_band || t("common.unknown_band");

  return `<article class="device-card">
    <div class="device-card-head">
      <div>
        <h4>${escapeHtml(device.name)}</h4>
        <div class="device-addresses">${escapeHtml(ipAddress)}</div>
      </div>
      <div class="button-row">
        <button class="small secondary" onclick="renameDevice('${escapeHtml(device.device_mac)}')">${t("common.rename")}</button>
        <button class="small danger" onclick="deleteDevice('${escapeHtml(device.device_mac)}')">${t("common.delete")}</button>
      </div>
    </div>
    <div class="device-meta"><code>${escapeHtml(device.device_mac)}</code></div>
    <div class="meter" aria-label="${t("certainty.title")}"><span style="width:${confidence}%"></span></div>
    <div class="device-summary">
      <strong>${certaintyLabel(confidence)} Â· ${confidence.toFixed(0)} %</strong>
      <span>${t("device.current_ap")}: ${escapeHtml(currentAp)}</span>
      <span>${t("device.channel")}: ${escapeHtml(currentChannel)}</span>
      <span>${t("device.band")}: ${escapeHtml(currentBand)}</span>
      <span>${t("device.visible_aps", { count: device.visible_aps })}</span>
      <span>${t("device.last_seen")} ${relativeAgeSeconds(device.age_seconds)}</span>
    </div>
    <details>
      <summary>${t("device.signal_values")}</summary>
      <table><tbody>${vectorRows || `<tr><td>${t("empty.no_fresh_values")}</td></tr>`}</tbody></table>
    </details>
  </article>`;
}

function renderLive(devices) {
  if (!devices.length) {
    byId("live").innerHTML = `<div class="card muted">${t("empty.no_devices")}</div>`;
    return;
  }

  const groups = new Map();
  devices.forEach((device) => {
    const room = deviceRoom(device);
    if (!groups.has(room.key)) {
      groups.set(room.key, { label: room.label, devices: [] });
    }
    groups.get(room.key).devices.push(device);
  });

  const ordered = [...groups.entries()].sort(([keyA, groupA], [keyB, groupB]) => {
    if (keyA.startsWith("~") || keyB.startsWith("~")) {
      return keyA.localeCompare(keyB);
    }
    return groupA.label.localeCompare(groupB.label, currentLanguage);
  });

  byId("live").innerHTML = ordered.map(([_key, group]) => `
    <section class="room-group">
      <div class="room-heading">
        <h3>${escapeHtml(group.label)}</h3>
        <span>${group.devices.length}</span>
      </div>
      <div class="device-list">${group.devices.map(renderDeviceCard).join("")}</div>
    </section>`).join("");
}

function renderClients(clients) {
  discoveredClients = new Map(clients.map((client) => [client.mac, client]));
  if (!clients.length) {
    byId("clients").innerHTML = `<p class="muted">${t("empty.no_locatable_clients")}</p>`;
    return;
  }

  const rows = clients.slice(0, 40).map((client) => {
    const hostname = client.hostname || t("common.unknown_hostname");
    const ipAddress = client.ip_address || t("common.unknown_ip");
    return `<tr>
      <td>
        <strong>${escapeHtml(hostname)}</strong><br>
        <span class="muted">${escapeHtml(ipAddress)} Â· <code>${escapeHtml(client.mac)}</code></span>
      </td>
      <td>${t("device.visible_aps", { count: client.visible_aps })}</td>
      <td>${client.configured
        ? `<span title="${t("device.already_added")}">âœ“</span>`
        : `<button class="small secondary" onclick="useClient('${escapeHtml(client.mac)}')">${t("common.add")}</button>`}
      </td>
    </tr>`;
  }).join("");
  byId("clients").innerHTML = `<h4>${t("device.discovered_clients")}</h4><table><tbody>${rows}</tbody></table>`;
}

function renderRooms(rooms) {
  configuredRooms = new Map(rooms.map((room) => [room.id || room.slug, room]));
  if (!rooms.length) {
    byId("rooms").innerHTML = `<p class="muted">${t("empty.no_rooms")}</p>`;
    return;
  }
  const rows = rooms.map((room) => `
    <tr>
      <td><strong>${escapeHtml(room.name)}</strong><br><code>${escapeHtml(room.id || room.slug)}</code></td>
      <td><div class="button-row">
        <button class="small secondary" onclick="renameRoom('${escapeHtml(room.id || room.slug)}')">${t("common.rename")}</button>
        <button class="small danger" onclick="deleteRoom('${escapeHtml(room.id || room.slug)}')">${t("common.delete")}</button>
      </div></td>
    </tr>`).join("");
  byId("rooms").innerHTML = `<table><tbody>${rows}</tbody></table>`;
}

function renderSelectors(devices, rooms) {
  const selectedDevice = byId("calDevice").value;
  const selectedRoom = byId("calRoom").value;
  byId("calDevice").innerHTML = devices
    .map((device) => `<option value="${escapeHtml(device.mac)}">${escapeHtml(device.name)}</option>`)
    .join("");
  byId("calRoom").innerHTML = rooms
    .map((room) => `<option value="${escapeHtml(room.slug)}">${escapeHtml(room.name)}</option>`)
    .join("");

  if ([...byId("calDevice").options].some((option) => option.value === selectedDevice)) {
    byId("calDevice").value = selectedDevice;
  }
  if ([...byId("calRoom").options].some((option) => option.value === selectedRoom)) {
    byId("calRoom").value = selectedRoom;
  }
}

async function assignAccessPointRoom(hostname, roomSlug) {
  await api(`access-point-rooms/${encodeURIComponent(hostname)}`, {
    method: "PUT",
    body: JSON.stringify({ room_slug: roomSlug || null, weight: 0.08 }),
  });
  await refresh();
}

function renderAccessPoints(accessPoints) {
  if (!accessPoints.length) {
    byId("aps").innerHTML = t("empty.no_access_points");
    return;
  }

  const roomOptions = [...configuredRooms.values()]
    .map((room) => `<option value="${escapeHtml(room.slug)}">${escapeHtml(room.name)}</option>`)
    .join("");

  const rows = accessPoints.map((accessPoint) => {
    const hostname = accessPoint.hostname || t("common.unknown_ap");
    const band = accessPoint.band === "unknown" ? t("common.unknown_band") : accessPoint.band;
    const assigned = accessPointRooms.get(hostname.toLocaleLowerCase())?.room_slug || "";
    return `<div class="ap-row">
      <div class="ap-name"><strong>${escapeHtml(hostname)}</strong><span>${escapeHtml(band)}</span></div>
      <code>${escapeHtml(accessPoint.bssid)}</code>
      <select onchange="assignAccessPointRoom('${escapeHtml(hostname)}', this.value)">
        <option value="">Keinem Raum zugeordnet</option>
        ${roomOptions}
      </select>
      <span class="muted">${t("access_points.last_value")} ${relativeAgeSeconds(accessPoint.age_seconds)}</span>
    </div>`;
  }).join("");
  byId("aps").innerHTML = `<div class="ap-list">${rows}</div>`;
  accessPoints.forEach((accessPoint) => {
    const hostname = accessPoint.hostname || "";
    const assigned = accessPointRooms.get(hostname.toLocaleLowerCase())?.room_slug || "";
    const selects = [...byId("aps").querySelectorAll("select")];
    const target = selects.find((select) => select.getAttribute("onchange")?.includes(`'${hostname}'`));
    if (target) target.value = assigned;
  });
}

function renderFingerprints(fingerprints) {
  if (!fingerprints.length) {
    byId("fingerprints").innerHTML = t("empty.no_fingerprints");
    return;
  }
  const rows = fingerprints.map((fingerprint) => `
    <tr>
      <td><strong>${escapeHtml(fingerprint.device_name || fingerprint.device_mac)}</strong></td>
      <td>${escapeHtml(fingerprint.room_name || fingerprint.room_slug)}</td>
      <td>${Object.keys(fingerprint.vector).length}</td>
      <td>${fingerprint.sample_count}</td>
      <td><button class="small danger" onclick="deleteFingerprint(${fingerprint.id})">${t("common.delete")}</button></td>
    </tr>`).join("");
  byId("fingerprints").innerHTML = `
    <table>
      <thead><tr><th>${t("device.name")}</th><th>${t("calibration.room")}</th><th>${t("fingerprints.aps")}</th><th>${t("fingerprints.samples")}</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function refresh() {
  try {
    const [status, live, discovered, devices, rooms, fingerprints, apRooms] = await Promise.all([
      api("status"),
      api("live"),
      api("discovered"),
      api("devices"),
      api("rooms"),
      api("fingerprints"),
      api("access-point-rooms"),
    ]);
    renderStatus(status);
    configuredDevices = new Map(devices.map((device) => [device.mac, device]));
    configuredRooms = new Map(rooms.map((room) => [room.id || room.slug, room]));
    accessPointRooms = new Map(
      apRooms.map((item) => [item.hostname.toLocaleLowerCase(), item]),
    );
    renderLive(live);
    renderClients(discovered.clients);
    renderRooms(rooms);
    renderSelectors(devices, rooms);
    renderAccessPoints(discovered.access_points);
    renderFingerprints(fingerprints);
  } catch (error) {
    console.error(error);
  }
}

async function renameDevice(mac) {
  const device = configuredDevices.get(mac);
  const name = window.prompt(t("prompt.device_name"), device?.name || "");
  if (!name || name.trim() === device?.name) {
    return;
  }
  try {
    await api(`devices/${encodeURIComponent(mac)}`, {
      method: "PATCH",
      body: JSON.stringify({ name: name.trim() }),
    });
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
}

async function renameRoom(roomId) {
  const room = configuredRooms.get(roomId);
  const name = window.prompt(t("prompt.room_name"), room?.name || "");
  if (!name || name.trim() === room?.name) {
    return;
  }
  try {
    await api(`rooms/${encodeURIComponent(roomId)}`, {
      method: "PATCH",
      body: JSON.stringify({ name: name.trim() }),
    });
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
}

function useClient(mac) {
  const client = discoveredClients.get(mac);
  byId("deviceMac").value = mac;
  byId("deviceName").value = client?.hostname || "";
  byId("deviceName").focus();
}

async function deleteDevice(mac) {
  if (!window.confirm(t("confirm.delete_device"))) {
    return;
  }
  try {
    await api(`devices/${encodeURIComponent(mac)}`, { method: "DELETE" });
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteRoom(slug) {
  if (!window.confirm(t("confirm.delete_room"))) {
    return;
  }
  try {
    await api(`rooms/${encodeURIComponent(slug)}`, { method: "DELETE" });
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteFingerprint(id) {
  if (!window.confirm(t("confirm.delete_fingerprint"))) {
    return;
  }
  try {
    await api(`fingerprints/${id}`, { method: "DELETE" });
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
}

async function pollCalibration() {
  if (!currentCalibration) {
    return;
  }
  try {
    currentCalibration = await api(`calibrations/${currentCalibration.id}`);
    const error = currentCalibration.error
      ? `<br>${escapeHtml(lookup(currentCalibration.error) ? t(currentCalibration.error) : currentCalibration.error)}`
      : "";
    byId("calStatus").innerHTML = `
      <div class="message">
        ${t("calibration.status")}: <b>${t(`calibration.states.${currentCalibration.status}`)}</b> Â·
        ${t("calibration.remaining", { seconds: currentCalibration.remaining_seconds })} Â·
        ${t("calibration.ap_count", { count: currentCalibration.ap_count })} Â·
        ${t("calibration.sample_count", { count: currentCalibration.sample_count })}${error}
      </div>`;
    if (currentCalibration.status === "running") {
      window.setTimeout(pollCalibration, 1000);
    } else {
      await refresh();
    }
  } catch (error) {
    byId("calStatus").textContent = error.message;
  }
}

byId("deviceForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("devices", {
      method: "POST",
      body: JSON.stringify({
        mac: byId("deviceMac").value,
        name: byId("deviceName").value,
        slug: byId("deviceSlug").value || null,
      }),
    });
    event.target.reset();
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
});

byId("roomForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("rooms", {
      method: "POST",
      body: JSON.stringify({
        name: byId("roomName").value,
        slug: byId("roomSlug").value || null,
      }),
    });
    event.target.reset();
    await refresh();
  } catch (error) {
    window.alert(error.message);
  }
});

byId("calForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    currentCalibration = await api("calibrations/start", {
      method: "POST",
      body: JSON.stringify({
        device_mac: byId("calDevice").value,
        room_slug: byId("calRoom").value,
        duration: Number(byId("calDuration").value),
      }),
    });
    pollCalibration();
  } catch (error) {
    window.alert(error.message);
  }
});

byId("languageSelect").addEventListener("change", async (event) => {
  await loadLanguage(event.target.value);
  await refresh();
});

async function start() {
  await loadLanguage(detectLanguage());
  await refresh();
  window.setInterval(refresh, 4000);
}

start().catch(console.error);
