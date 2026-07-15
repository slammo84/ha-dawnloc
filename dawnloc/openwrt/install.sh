#!/bin/sh
# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

set -eu

VERSION="0.1.0-rc.2"
SOURCE_BASE="${DAWNLOC_SOURCE_BASE:-https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt}"
MODE="${1:-install}"
TTY="/dev/tty"
[ -r "$TTY" ] || TTY="/dev/stdin"

say() {
  printf '%s\n' "$*"
}

fail() {
  say "Error: $*" >&2
  exit 1
}

prompt() {
  label="$1"
  default="${2:-}"
  if [ -n "$default" ]; then
    printf '%s [%s]: ' "$label" "$default" >"$TTY"
  else
    printf '%s: ' "$label" >"$TTY"
  fi
  IFS= read -r answer <"$TTY" || answer=""
  [ -n "$answer" ] || answer="$default"
  printf '%s' "$answer"
}

prompt_yes_no() {
  label="$1"
  default="${2:-n}"
  answer="$(prompt "$label" "$default")"
  case "$answer" in
    y|Y|yes|YES|j|J|ja|JA) return 0 ;;
    *) return 1 ;;
  esac
}

prompt_secret() {
  label="$1"
  current="${2:-}"
  printf '%s%s: ' "$label" "${current:+ [leave empty to keep current]}" >"$TTY"
  if [ -t 0 ] || [ -e /dev/tty ]; then
    stty -echo <"$TTY" 2>/dev/null || true
    IFS= read -r answer <"$TTY" || answer=""
    stty echo <"$TTY" 2>/dev/null || true
    printf '\n' >"$TTY"
  else
    IFS= read -r answer <"$TTY" || answer=""
  fi
  [ -n "$answer" ] || answer="$current"
  printf '%s' "$answer"
}

[ "$(id -u)" = "0" ] || fail "Run this script as root."
[ -r /etc/openwrt_release ] || fail "This does not appear to be an OpenWrt system."

OPENWRT_VERSION="$(. /etc/openwrt_release; printf '%s' "${DISTRIB_RELEASE:-unknown}")"
say "DAWNLoc OpenWrt installer $VERSION"
say "OpenWrt version: $OPENWRT_VERSION"

if command -v apk >/dev/null 2>&1; then
  PACKAGE_MANAGER="apk"
elif command -v opkg >/dev/null 2>&1; then
  PACKAGE_MANAGER="opkg"
else
  fail "Neither apk nor opkg was found."
fi
say "Package manager: $PACKAGE_MANAGER"

PACKAGE_INDEX_UPDATED=0
update_package_index() {
  [ "$PACKAGE_INDEX_UPDATED" -eq 1 ] && return 0
  if [ "$PACKAGE_MANAGER" = "apk" ]; then
    apk update
  else
    opkg update
  fi
  PACKAGE_INDEX_UPDATED=1
}

install_package() {
  package="$1"
  update_package_index
  if [ "$PACKAGE_MANAGER" = "apk" ]; then
    apk add "$package"
  else
    opkg install "$package"
  fi
}

ensure_command() {
  command_name="$1"
  package="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    say "Installing missing dependency: $package"
    install_package "$package"
  fi
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is still missing."
}

download() {
  url="$1"
  destination="$2"
  if command -v uclient-fetch >/dev/null 2>&1; then
    uclient-fetch -q -O "$destination" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$destination" "$url"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$destination" "$url"
  else
    fail "No supported download tool was found."
  fi
}

uninstall() {
  say "Removing DAWNLoc from this OpenWrt node."
  /etc/init.d/dawnloc stop 2>/dev/null || true
  /etc/init.d/dawnloc disable 2>/dev/null || true
  rm -f /usr/sbin/dawnloc-agent /etc/init.d/dawnloc
  if prompt_yes_no "Keep /etc/config/dawnloc?" "y"; then
    say "Configuration kept at /etc/config/dawnloc."
  else
    rm -f /etc/config/dawnloc
  fi
  say "DAWNLoc has been removed."
}

case "$MODE" in
  --uninstall|uninstall)
    uninstall
    exit 0
    ;;
  --update|update|--repair|repair|install|"") ;;
  *) fail "Unknown option: $MODE" ;;
esac

ensure_command ubus ubus
ensure_command uci uci
ensure_command jsonfilter jsonfilter
ensure_command jshn jshn
ensure_command awk busybox
ensure_command logger busybox

if ! ubus call dawn get_hearing_map >/dev/null 2>&1; then
  fail "DAWN is not available. 'ubus call dawn get_hearing_map' failed."
fi

ensure_mqtt_client() {
  use_tls="$1"
  if ! command -v mosquitto_pub >/dev/null 2>&1; then
    if [ "$use_tls" = "1" ]; then
      mqtt_package="mosquitto-client-ssl"
    else
      mqtt_package="mosquitto-client-nossl"
    fi
    say "Installing MQTT client: $mqtt_package"
    install_package "$mqtt_package"
  fi
  if [ "$use_tls" = "1" ] && ! mosquitto_pub --help 2>&1 | grep -q -- '--capath'; then
    say "Installing TLS-capable MQTT client."
    if [ "$PACKAGE_MANAGER" = "apk" ]; then
      apk del mosquitto-client-nossl 2>/dev/null || true
    else
      opkg remove mosquitto-client-nossl 2>/dev/null || true
    fi
    install_package mosquitto-client-ssl
  fi
  command -v mosquitto_pub >/dev/null 2>&1 || fail "mosquitto_pub is missing."
}

TMP_DIR="$(mktemp -d /tmp/ha-dawnloc.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

download "$SOURCE_BASE/dawnloc-agent" "$TMP_DIR/dawnloc-agent"
download "$SOURCE_BASE/dawnloc.init" "$TMP_DIR/dawnloc.init"
sh -n "$TMP_DIR/dawnloc-agent" || fail "Downloaded dawnloc-agent has invalid shell syntax."
sh -n "$TMP_DIR/dawnloc.init" || fail "Downloaded init script has invalid shell syntax."

for target in /usr/sbin/dawnloc-agent /etc/init.d/dawnloc; do
  if [ -f "$target" ]; then
    cp "$target" "$target.bak"
  fi
done
cp "$TMP_DIR/dawnloc-agent" /usr/sbin/dawnloc-agent
cp "$TMP_DIR/dawnloc.init" /etc/init.d/dawnloc
chmod 0755 /usr/sbin/dawnloc-agent /etc/init.d/dawnloc

mkdir -p /etc/config
if [ ! -e /etc/config/dawnloc ]; then
  : > /etc/config/dawnloc
fi
chmod 0600 /etc/config/dawnloc

service_is_registered() {
  ubus call service list '{"name":"dawnloc"}' 2>/dev/null | grep -q '"dawnloc"'
}

enable_and_start_service() {
  /etc/init.d/dawnloc enable
  if service_is_registered; then
    /etc/init.d/dawnloc restart
  else
    /etc/init.d/dawnloc start
  fi
}

if [ "$MODE" = "--update" ] || [ "$MODE" = "update" ]; then
  if uci -q get dawnloc.main >/dev/null 2>&1; then
    update_tls="$(uci -q get dawnloc.main.tls || true)"
    [ -n "$update_tls" ] || update_tls="0"
    ensure_mqtt_client "$update_tls"
    enable_and_start_service
    say "DAWNLoc was updated and restarted."
    exit 0
  fi
fi

current_broker="$(uci -q get dawnloc.main.broker || true)"
current_port="$(uci -q get dawnloc.main.port || true)"
current_username="$(uci -q get dawnloc.main.username || true)"
current_password="$(uci -q get dawnloc.main.password || true)"
current_topic="$(uci -q get dawnloc.main.topic || true)"
current_interval="$(uci -q get dawnloc.main.interval || true)"
current_tls="$(uci -q get dawnloc.main.tls || true)"
current_node="$(uci -q get dawnloc.main.node_name || true)"

[ -n "$current_port" ] || current_port="1883"
[ -n "$current_topic" ] || current_topic="dawnloc/raw/hearing_map"
[ -n "$current_interval" ] || current_interval="3"
[ -n "$current_tls" ] || current_tls="0"
[ -n "$current_node" ] || current_node="$(uci -q get system.@system[0].hostname || hostname)"

say ""
say "MQTT configuration"
mqtt_broker="$(prompt "MQTT broker IP address or hostname" "$current_broker")"
[ -n "$mqtt_broker" ] || fail "MQTT broker is required."
mqtt_port="$(prompt "MQTT port" "$current_port")"
mqtt_username="$(prompt "MQTT username (optional)" "$current_username")"
mqtt_password="$(prompt_secret "MQTT password (optional)" "$current_password")"
if [ "$current_tls" = "1" ]; then
  tls_default="y"
else
  tls_default="n"
fi
if prompt_yes_no "Use MQTT TLS?" "$tls_default"; then
  mqtt_tls="1"
  install_package ca-bundle
else
  mqtt_tls="0"
fi
ensure_mqtt_client "$mqtt_tls"
mqtt_topic="$(prompt "MQTT topic" "$current_topic")"
interval="$(prompt "Publish interval in seconds" "$current_interval")"
node_name="$(prompt "Name of this OpenWrt access point" "$current_node")"

uci -q delete dawnloc.main 2>/dev/null || true
uci set dawnloc.main='dawnloc'
uci set dawnloc.main.enabled='1'
uci set "dawnloc.main.broker=$mqtt_broker"
uci set "dawnloc.main.port=$mqtt_port"
uci set "dawnloc.main.topic=$mqtt_topic"
uci set "dawnloc.main.interval=$interval"
uci set "dawnloc.main.tls=$mqtt_tls"
uci set "dawnloc.main.node_name=$node_name"
if [ -n "$mqtt_username" ]; then
  uci set "dawnloc.main.username=$mqtt_username"
else
  uci -q delete dawnloc.main.username 2>/dev/null || true
fi
if [ -n "$mqtt_password" ]; then
  uci set "dawnloc.main.password=$mqtt_password"
else
  uci -q delete dawnloc.main.password 2>/dev/null || true
fi
uci commit dawnloc
chmod 0600 /etc/config/dawnloc

mqtt_test() {
  if [ "$mqtt_tls" = "1" ] && [ -n "$mqtt_username" ]; then
    mosquitto_pub -h "$mqtt_broker" -p "$mqtt_port" -u "$mqtt_username" -P "$mqtt_password" \
      --capath /etc/ssl/certs -t dawnloc/status/install-test -m "$node_name"
  elif [ "$mqtt_tls" = "1" ]; then
    mosquitto_pub -h "$mqtt_broker" -p "$mqtt_port" --capath /etc/ssl/certs \
      -t dawnloc/status/install-test -m "$node_name"
  elif [ -n "$mqtt_username" ]; then
    mosquitto_pub -h "$mqtt_broker" -p "$mqtt_port" -u "$mqtt_username" -P "$mqtt_password" \
      -t dawnloc/status/install-test -m "$node_name"
  else
    mosquitto_pub -h "$mqtt_broker" -p "$mqtt_port" \
      -t dawnloc/status/install-test -m "$node_name"
  fi
}

if mqtt_test; then
  say "MQTT connection test succeeded."
else
  say "Warning: MQTT connection test failed." >&2
  if ! prompt_yes_no "Continue anyway?" "n"; then
    fail "Installation cancelled. Check the MQTT settings and run the installer again."
  fi
fi

enable_and_start_service
sleep 2

if ubus call service list '{"name":"dawnloc"}' 2>/dev/null | grep -q '"running": true'; then
  say ""
  say "DAWNLoc was installed successfully."
  say "Node: $node_name"
  say "MQTT broker: $mqtt_broker:$mqtt_port"
  say "Topic: $mqtt_topic"
  say "Service: running"
else
  fail "The files were installed, but the dawnloc service is not running."
fi
