#!/command/with-contenv bashio
# shellcheck disable=SC1008
bashio::config.require 'log_level'
bashio::log.level "$(bashio::config 'log_level')"

# Logging before attempting to load the kernel module
bashio::log.info "Attempting to load vhci-hcd kernel module..."
if /sbin/modprobe vhci-hcd; then
    bashio::log.info "Successfully loaded vhci-hcd module."
    bashio::log.debug "Kernel modules currently loaded: $(lsmod | grep vhci)"
else
    bashio::log.error "Failed to load vhci-hcd kernel module. Ensure it's available on the host."
    exit 1
fi
