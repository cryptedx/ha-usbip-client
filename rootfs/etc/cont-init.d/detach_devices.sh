#!/command/with-contenv bashio
# shellcheck disable=SC1008
# ==============================================================================
# Home Assistant Add-on: HA USBIP Client
# Detach USBIP devices on shutdown
# ==============================================================================

bashio::log.info "Detaching USBIP devices"

# Get the list of attached ports
ports=$(usbip port | grep -E 'Port [0-9]+' | awk '{print $2}' | tr -d ':')

for port in $ports; do
    usbip detach -p "${port}" && bashio::log.info "Detached device on port ${port}"
done
