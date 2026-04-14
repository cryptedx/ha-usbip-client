FROM ghcr.io/home-assistant/base:latest

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt

# Install requirements for app
RUN apk add --no-cache \
    kmod \
    linux-tools-usbip \
    hwids-usb \
    device-mapper-libs \
    python3 \
    py3-pip \
    && pip3 install --no-cache-dir --break-system-packages \
    -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy root filesystem
COPY rootfs /

# Make usbip_lib importable from all scripts
ENV PYTHONPATH=/usr/local/lib

# Ensure scripts are executable
RUN chmod +x /etc/cont-init.d/*.py \
    && chmod +x /etc/cont-finish.d/*.py \
    && chmod +x /etc/services.d/*/run \
    && chmod +x /etc/services.d/*/finish
