ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.2.2
FROM ${BUILD_FROM}

# Install requirements for add-on
RUN apk add --no-cache \
    kmod \
    linux-tools-usbip \
    hwids-usb \
    device-mapper-libs

# Copy root filesystem
COPY rootfs /

# Ensure scripts are executable
RUN chmod +x /etc/cont-init.d/*.sh
RUN chmod +x /etc/services.d/usbip/run
RUN chmod +x /etc/services.d/usbip/finish
