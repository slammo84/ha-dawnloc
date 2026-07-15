# SPDX-FileCopyrightText: 2026 slammo84
# SPDX-License-Identifier: Apache-2.0

ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

ARG BUILD_VERSION

LABEL \
  org.opencontainers.image.title="Home Assistant App: DAWNLoc" \
  org.opencontainers.image.description="Room-level Wi-Fi location tracking from OpenWrt DAWN data" \
  org.opencontainers.image.version="${BUILD_VERSION}" \
  org.opencontainers.image.source="https://github.com/slammo84/ha-dawnloc" \
  org.opencontainers.image.authors="slammo84" \
  org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY app /opt/dawnloc/app
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

WORKDIR /opt/dawnloc
CMD ["/run.sh"]
