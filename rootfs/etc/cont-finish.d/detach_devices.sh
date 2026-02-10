#!/command/with-contenv bashio
# shellcheck disable=SC1008

bashio::log.info "🔴 Container stopping - detaching USB/IP devices"

# Check if usbip command is available
if ! command -v usbip >/dev/null 2>&1; then
    bashio::log.warning "usbip command not found, cannot detach devices"
    exit 0
fi

# Always use 'usbip port' to determine what is actually attached
# This is the most reliable method — no dependency on temp files or index matching
detached_count=0
failed_count=0

if ! ports_output=$(usbip port 2>/dev/null); then
    bashio::log.warning "Failed to get USB/IP port information. Attempting blind detach..."
    # Fallback: try detaching ports 0-15 blindly
    for port in $(seq 0 15); do
        usbip detach -p "${port}" >/dev/null 2>&1 && detached_count=$((detached_count + 1))
    done
    if [ "$detached_count" -gt 0 ]; then
        bashio::log.info "Blind detach recovered ${detached_count} device(s)."
    fi
else
    # Parse all port numbers from usbip port output
    ports=$(echo "$ports_output" | grep -oE '^Port [0-9]+:' | grep -oE '[0-9]+')

    if [ -z "$ports" ]; then
        bashio::log.info "No USB/IP devices currently attached."
    else
        bashio::log.info "Found attached USB/IP ports: $(echo $ports | tr '\n' ' ')"

        for port in $ports; do
            # Try to get device description from the port output for logging
            device_desc=$(echo "$ports_output" | grep -A2 "^Port ${port}:" | tail -1 | sed 's/^\s*//;s/\s*$//')
            if [ -z "$device_desc" ]; then
                device_desc="Unknown device"
            fi

            bashio::log.debug "Detaching port ${port}: ${device_desc}"
            if usbip detach -p "${port}" 2>/dev/null; then
                bashio::log.info "Successfully detached port ${port}: ${device_desc}"
                detached_count=$((detached_count + 1))
            else
                bashio::log.warning "Failed to detach port ${port}: ${device_desc}"
                failed_count=$((failed_count + 1))
            fi

            # Small delay between detach operations to avoid race conditions
            sleep 0.5
        done
    fi
fi

bashio::log.info "Detach operation complete: ${detached_count} detached, ${failed_count} failed"

# Write detach event for WebUI
echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"type\":\"detach_all\",\"device\":\"\",\"server\":\"\",\"detail\":\"Container stop: ${detached_count} detached, ${failed_count} failed\"}" >> /tmp/usbip_events.jsonl 2>/dev/null || true

# Clean up temp files
rm -f /tmp/attached_devices.txt /tmp/device_details.txt

bashio::log.info "USB/IP device cleanup finished"
bashio::log.info "🔴 Container stopped"
