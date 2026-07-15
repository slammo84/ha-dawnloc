// SPDX-FileCopyrightText: 2026 slammo84
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(
  /[&<>"']/g,
  char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]),
);

let clients = new Map();
let devices = new Map();
let rooms = new Map();
let apRooms = new Map();
let calibration = null;
let refreshActive = false;

async function api(path, options = {}) {
  const response = await fetch(`api/${path}`, {
    headers: {'Content-Type': 'application/json'},
    ...options,
  });

  if (response.ok) {
    return response.json();
  }

  let message = response.statusText;
  try {
    message = (await response.json()).detail || message;
  } catch {
    // Keep the HTTP status text.
  }
  throw new Error(message);
}

function age(value) {
  if (value == null) return 'nie';
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `vor ${seconds} Sekunden`;
  if (seconds < 3600) return `vor ${Math.round(seconds / 60)} Minuten`;
  return `vor ${Math.round(seconds / 3600)} Stunden`;
}

function replaceSelectOptions(id, optionsHtml) {
  const select = $(id);
  const selected = select.value;
  select.innerHTML = optionsHtml;

  if ([...select.options].some(option => option.value === selected)) {
    select.value = selected;
  }
}

function renderStatus(status) {
  $('status').innerHTML =
    `<span class="pill"><span class="dot ${status.mqtt_connected ? 'ok' : ''}"></span>` +
    `MQTT ${status.mqtt_connected ? 'verbunden' : 'getrennt'}</span>` +
    (status.access_points || []).map(ap =>
      `<span class="ap-chip"><span class="dot ${ap.age_seconds < 15 ? 'ok' : ''}"></span>${esc(ap.hostname)}</span>`
    ).join('');
}

function renderLive(list) {
  const groups = new Map();

  for (const device of list) {
    const room = device.stable_room || 'Unbekannter Standort';
    if (!groups.has(room)) groups.set(room, []);
    groups.get(room).push(device);
  }

  $('live').innerHTML = [...groups].map(([name, items]) =>
    `<section class="room-group">
      <div class="room-heading"><h3>${esc(name)}</h3><strong>${items.length}</strong></div>
      <div class="device-list">
        ${items.map(device =>
          `<article class="device-card">
            <div class="device-head">
              <div>
                <h4>${esc(device.name)}</h4>
                <div class="meta">${esc(device.ip_address || 'Keine IP')} · ${esc(device.device_mac)}</div>
              </div>
              <div>
                <button class="small secondary" onclick="renameDevice('${device.device_mac}')">Umbenennen</button>
                <button class="small danger" onclick="deleteDevice('${device.device_mac}')">Löschen</button>
              </div>
            </div>
            <div class="meter"><span style="width:${Number(device.confidence || 0)}%"></span></div>
            <div class="meta">
              ${esc(device.method || 'none')} · ${Number(device.confidence || 0).toFixed(0)} % ·
              ${esc(device.current_ap || device.strongest_ap || 'kein AP')} ·
              ${device.visible_aps || 0} APs · ${age(device.age_seconds)}
            </div>
            <details>
              <summary>Aktuelle Signalwerte</summary>
              <pre>${esc(JSON.stringify(device.vector, null, 2))}</pre>
            </details>
          </article>`
        ).join('')}
      </div>
    </section>`
  ).join('') || '<section class="card muted">Noch keine Geräte konfiguriert.</section>';
}

function renderClients(list) {
  clients = new Map(list.map(item => [item.mac, item]));
  $('clientCount').textContent = `(${list.length})`;
  $('clients').innerHTML = list.map(client =>
    `<p>
      <strong>${esc(client.hostname || 'Unbekannt')}</strong><br>
      <span class="muted">${esc(client.ip_address)} · ${esc(client.mac)} · ${client.visible_aps} APs</span>
      ${client.configured ? '✓' : `<button class="small secondary" onclick="useClient('${client.mac}')">Übernehmen</button>`}
    </p>`
  ).join('') || '<p class="muted">Keine geeigneten Clients.</p>';
}

function renderRooms(list) {
  rooms = new Map(list.map(room => [room.slug, room]));
  $('roomCount').textContent = `(${list.length})`;
  $('rooms').innerHTML = list.map(room =>
    `<p>
      <strong>${esc(room.name)}</strong> <code>${esc(room.slug)}</code>
      <button class="small secondary" onclick="renameRoom('${room.slug}')">Umbenennen</button>
      <button class="small danger" onclick="deleteRoom('${room.slug}')">Löschen</button>
    </p>`
  ).join('');

  const options =
    '<option value="">–</option>' +
    list.map(room => `<option value="${esc(room.slug)}">${esc(room.name)}</option>`).join('');

  replaceSelectOptions('calRoom', options);
  replaceSelectOptions('referenceRoom', options);
}

function renderDevices(list) {
  devices = new Map(list.map(device => [device.mac, device]));
  const options = list.map(device =>
    `<option value="${device.mac}">${esc(device.name)}${device.device_type === 'reference' ? ' (Raumanker)' : ''}</option>`
  ).join('');
  replaceSelectOptions('calDevice', options);
}

function renderAPs(list) {
  const selectedRooms = new Map(
    [...$('aps').querySelectorAll('select[data-host]')].map(select => [
      select.dataset.host.toLowerCase(),
      select.value,
    ]),
  );

  const grouped = new Map();
  for (const ap of list) {
    if (!grouped.has(ap.hostname)) grouped.set(ap.hostname, []);
    grouped.get(ap.hostname).push(ap);
  }

  $('apCount').textContent = `(${grouped.size})`;
  $('aps').innerHTML = [...grouped].map(([host, radios]) => {
    const key = host.toLowerCase();
    const assigned = apRooms.get(key)?.room_slug || '';
    const selected = selectedRooms.has(key) ? selectedRooms.get(key) : assigned;

    return `<div class="ap-group">
      <div>
        <strong>${esc(host)}</strong>
        <div class="radios">
          ${radios.map(radio =>
            `${esc(radio.band)} · ${esc(radio.bssid)} · ${age(radio.age_seconds)}`
          ).join('<br>')}
        </div>
      </div>
      <select data-host="${esc(host)}">
        <option value="">Keinem Raum zugeordnet</option>
        ${[...rooms.values()].map(room =>
          `<option value="${esc(room.slug)}" ${room.slug === selected ? 'selected' : ''}>${esc(room.name)}</option>`
        ).join('')}
      </select>
    </div>`;
  }).join('');

  $('aps').querySelectorAll('select[data-host]').forEach(select => {
    select.addEventListener('change', () => assignAP(select.dataset.host, select.value));
  });
}

function renderFingerprints(list) {
  $('fingerprintCount').textContent = `(${list.length})`;
  $('fingerprints').innerHTML =
    `<table>
      <thead>
        <tr>
          <th>Gerät</th>
          <th>Typ</th>
          <th>Raum</th>
          <th>Zeitpunkt</th>
          <th>APs</th>
          <th>Messwerte</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${list.map(fingerprint =>
          `<tr>
            <td>${esc(fingerprint.device_name || fingerprint.device_mac)}</td>
            <td>${fingerprint.device_type === 'reference' ? 'Raumanker' : 'Ortungsgerät'}</td>
            <td>${esc(fingerprint.room_name || fingerprint.room_slug)}</td>
            <td>${new Date(fingerprint.created_at * 1000).toLocaleString('de-DE')}</td>
            <td>${Object.keys(fingerprint.vector || {}).length}</td>
            <td>${Number(fingerprint.sample_count || 0)}</td>
            <td><button class="small danger" onclick="deleteFP(${fingerprint.id})">Löschen</button></td>
          </tr>`
        ).join('')}
      </tbody>
    </table>`;
}

function calibrationError(error) {
  return {
    'errors.no_observations': 'Keine Messwerte empfangen.',
    'errors.not_enough_access_points': 'Zu wenige Access Points für einen Fingerprint.',
  }[error] || error || 'Unbekannter Fehler';
}

function renderCalibration(result) {
  const deviceName =
    result.device_name ||
    devices.get(result.device_mac)?.name ||
    result.device_mac;
  const roomName =
    result.room_name ||
    rooms.get(result.room_slug)?.name ||
    result.room_slug;
  const statusLabel = {
    running: 'Kalibrierung läuft',
    complete: 'Kalibrierung abgeschlossen',
    failed: 'Kalibrierung fehlgeschlagen',
  }[result.status] || result.status;

  const counts = result.sample_counts || {};
  const signalRows = Object.entries(result.vector || {}).map(([label, rssi]) =>
    `<tr>
      <td>${esc(label)}</td>
      <td>${Number(rssi).toFixed(1)} dBm</td>
      <td>${Number(counts[label] || 0)}</td>
    </tr>`
  ).join('');

  let message = '';
  if (result.status === 'complete') {
    message = `<p class="calibration-ok">Fingerprint #${result.fingerprint_id} gespeichert.</p>`;
  } else if (result.status === 'failed') {
    message = `<p class="calibration-error">${esc(calibrationError(result.error))}</p>`;
  }

  $('calStatus').innerHTML =
    `<div class="calibration-panel">
      <div class="calibration-heading">
        <strong>${esc(statusLabel)}</strong>
        <span>${Math.max(0, Math.ceil(Number(result.remaining_seconds || 0)))} s</span>
      </div>
      <div class="calibration-facts">
        <div><span>Gerät</span><strong>${esc(deviceName)}</strong></div>
        <div><span>Raum</span><strong>${esc(roomName)}</strong></div>
        <div><span>Access Points</span><strong>${Number(result.ap_count || 0)}</strong></div>
        <div><span>Messwerte</span><strong>${Number(result.sample_count || 0)}</strong></div>
      </div>
      ${signalRows
        ? `<table class="calibration-table">
            <thead><tr><th>AP / Band</th><th>Median</th><th>Samples</th></tr></thead>
            <tbody>${signalRows}</tbody>
          </table>`
        : '<p class="muted">Noch keine verwertbaren Messwerte.</p>'}
      ${message}
    </div>`;
}

async function refresh() {
  if (refreshActive) return;
  refreshActive = true;

  try {
    const [status, live, discovered, configuredDevices, configuredRooms, fingerprints, assignments] =
      await Promise.all([
        api('status'),
        api('live'),
        api('discovered'),
        api('devices'),
        api('rooms'),
        api('fingerprints'),
        api('access-point-rooms'),
      ]);

    apRooms = new Map(assignments.map(item => [item.hostname.toLowerCase(), item]));
    renderStatus(status);
    renderRooms(configuredRooms);
    renderDevices(configuredDevices);
    renderLive(live);
    renderClients(discovered.clients);
    renderAPs(discovered.access_points);
    renderFingerprints(fingerprints);
  } catch (error) {
    console.error(error);
  } finally {
    refreshActive = false;
  }
}

function useClient(mac) {
  const client = clients.get(mac);
  $('deviceMac').value = mac;
  $('deviceName').value = client?.hostname || '';
  $('deviceName').focus();
}

async function assignAP(hostname, roomSlug) {
  await api(`access-point-rooms/${encodeURIComponent(hostname)}`, {
    method: 'PUT',
    body: JSON.stringify({room_slug: roomSlug || null}),
  });
  await refresh();
}

async function renameDevice(mac) {
  const device = devices.get(mac);
  const name = prompt('Neuer Name', device?.name || '');
  if (name) {
    await api(`devices/${encodeURIComponent(mac)}`, {
      method: 'PATCH',
      body: JSON.stringify({name: name.trim()}),
    });
  }
  await refresh();
}

async function deleteDevice(mac) {
  if (confirm('Gerät und zugehörige Fingerprints wirklich löschen?')) {
    await api(`devices/${encodeURIComponent(mac)}`, {method: 'DELETE'});
    await refresh();
  }
}

async function renameRoom(slug) {
  const room = rooms.get(slug);
  const name = prompt('Neuer Raumname', room?.name || '');
  if (name) {
    await api(`rooms/${encodeURIComponent(slug)}`, {
      method: 'PATCH',
      body: JSON.stringify({name: name.trim()}),
    });
  }
  await refresh();
}

async function deleteRoom(slug) {
  if (confirm('Raum wirklich löschen?')) {
    await api(`rooms/${encodeURIComponent(slug)}`, {method: 'DELETE'});
    await refresh();
  }
}

async function deleteFP(id) {
  if (confirm('Fingerprint löschen?')) {
    await api(`fingerprints/${id}`, {method: 'DELETE'});
    await refresh();
  }
}

$('deviceForm').addEventListener('submit', async event => {
  event.preventDefault();
  await api('devices', {
    method: 'POST',
    body: JSON.stringify({
      mac: $('deviceMac').value,
      name: $('deviceName').value,
      slug: $('deviceSlug').value || null,
      device_type: $('deviceType').value,
      reference_room_slug:
        $('deviceType').value === 'reference'
          ? $('referenceRoom').value || null
          : null,
    }),
  });
  event.target.reset();
  syncReferenceRoomState();
  await refresh();
});

$('roomForm').addEventListener('submit', async event => {
  event.preventDefault();
  await api('rooms', {
    method: 'POST',
    body: JSON.stringify({
      name: $('roomName').value,
      slug: $('roomSlug').value || null,
    }),
  });
  event.target.reset();
  await refresh();
});

$('calForm').addEventListener('submit', async event => {
  event.preventDefault();
  calibration = await api('calibrations/start', {
    method: 'POST',
    body: JSON.stringify({
      device_mac: $('calDevice').value,
      room_slug: $('calRoom').value,
      duration: Number($('calDuration').value),
    }),
  });
  renderCalibration(calibration);
  void pollCalibration();
});

async function pollCalibration() {
  if (!calibration) return;

  try {
    calibration = await api(`calibrations/${calibration.id}`);
    renderCalibration(calibration);

    if (calibration.status === 'running') {
      setTimeout(() => void pollCalibration(), 1000);
    } else {
      await refresh();
    }
  } catch (error) {
    $('calStatus').innerHTML =
      `<div class="calibration-panel calibration-error">${esc(error.message)}</div>`;
  }
}

$('importForm').addEventListener('submit', async event => {
  event.preventDefault();
  const formData = new FormData();
  formData.append('file', $('importFile').files[0]);

  const response = await fetch('api/import', {
    method: 'POST',
    body: formData,
  });
  const data = await response.json();

  $('importStatus').textContent = response.ok
    ? `Importiert: ${JSON.stringify(data.imported)}`
    : data.detail || 'Import fehlgeschlagen';

  if (response.ok) await refresh();
});

function syncReferenceRoomState() {
  $('referenceRoom').disabled = $('deviceType').value !== 'reference';
}

$('deviceType').addEventListener('change', syncReferenceRoomState);
syncReferenceRoomState();
void refresh();
setInterval(() => void refresh(), 5000);
