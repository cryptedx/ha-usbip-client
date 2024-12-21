#!/command/with-contenv bashio
# shellcheck disable=SC1008

bashio::log.info "Detaching USB/IP devices"

# Get the list of attached ports
ports=$(usbip port 2>/dev/null | grep -E 'Port [0-9]+' | awk '{print $2}' | tr -d ':')

if bashio::var.is_empty "$ports"; then
    bashio::log.info "No USB/IP devices to detach."
else
    for port in $ports; do
        if usbip detach -p "${port}"; then
            bashio::log.info "Detached device on port ${port}"
        else
            bashio::log.warning "Failed to detach device on port ${port}"
        fi
    done
fi
