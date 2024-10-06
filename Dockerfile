ARG BUILD_FROM
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
RUN chmod +x /etc/cont-init.d/*.sh \
    && chmod +x /etc/cont-finish.d/*.sh \
    && chmod +x /etc/services.d/*/run \
    && chmod +x /etc/services.d/*/finish
