#!/command/with-contenv bashio
# shellcheck disable=SC1008
# ==============================================================================
# Home Assistant Add-on: HA USBIP Client
# Load client kernel module
# ==============================================================================

bashio::log.info "Loading vhci-hcd kernel module..."
if /sbin/modprobe vhci-hcd; then
    bashio::log.info "Successfully loaded vhci-hcd module."
else
    bashio::log.error "Failed to load vhci-hcd kernel module. Ensure it's available on the host."
    exit 1
fi
