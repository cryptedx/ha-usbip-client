ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install requirements for app
RUN apk add --no-cache \
    kmod \
    linux-tools-usbip \
    hwids-usb \
    device-mapper-libs \
    python3 \
    py3-pip \
    && pip3 install --no-cache-dir --break-system-packages \
    flask==3.1.0 \
    flask-socketio==5.5.1 \
    gevent==24.11.1 \
    gevent-websocket==0.10.1

# Copy root filesystem
COPY rootfs /

# Ensure scripts are executable
RUN chmod +x /etc/cont-init.d/*.sh \
    && chmod +x /etc/cont-finish.d/*.sh \
    && chmod +x /etc/services.d/*/run \
    && chmod +x /etc/services.d/*/finish
