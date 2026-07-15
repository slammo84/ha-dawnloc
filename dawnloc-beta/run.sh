#!/usr/bin/with-contenv bashio
# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

export MQTT_HOST="$(bashio::services mqtt host)"
export MQTT_PORT="$(bashio::services mqtt port)"
export MQTT_USERNAME="$(bashio::services mqtt username)"
export MQTT_PASSWORD="$(bashio::services mqtt password)"
export DAWNLOC_OPTIONS="/data/options.json"
export DAWNLOC_DB="/data/dawnloc.db"

bashio::log.info "Starting DAWNLoc"
exec python3 -m app.main
