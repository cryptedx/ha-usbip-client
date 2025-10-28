#!/command/with-contenv bashio
# shellcheck disable=SC1008

bashio::log.info "🔴 Container stopping - detaching USB/IP devices"

# Check if usbip command is available
if ! command -v usbip >/dev/null 2>&1; then
    bashio::log.warning "usbip command not found, cannot detach devices"
    exit 0
fi

# Read device information from the file created during attachment
device_info_file="/tmp/attached_devices.txt"
if [ ! -f "$device_info_file" ]; then
    bashio::log.info "No device information file found. Checking for attached devices..."
    # Fallback to parsing usbip port output if file doesn't exist
    if ! ports_output=$(usbip port 2>/dev/null); then
        bashio::log.warning "Failed to get USB/IP port information"
        exit 0
    fi
    
    # Parse the output to extract port and device information
    ports=""
    port_device_list=""
    
    current_port=""
    while IFS= read -r line; do
        # Look for port lines
        if echo "$line" | grep -q '^Port [0-9]\+:'; then
            current_port=$(echo "$line" | sed -E 's/^Port ([0-9]+):.*/\1/')
            ports="$ports $current_port"
        # Look for device description lines (typically follow port lines)
        elif [ -n "$current_port" ] && echo "$line" | grep -q '^\s*[0-9.-]\+:\s'; then
            device_desc=$(echo "$line" | sed 's/^\s*//;s/\s*$//')
            port_device_list="${port_device_list}${current_port}|${device_desc}\n"
            current_port=""  # Reset after finding device info
        fi
    done <<< "$ports_output"
    
    ports=$(echo "$ports" | sed 's/^ *//')
    
    if [ -z "$ports" ]; then
        bashio::log.info "No USB/IP devices currently attached."
    else
        bashio::log.info "Found attached devices on ports: $ports"
        detached_count=0
        failed_count=0
        
        for port in $ports; do
            # Find device description for this port
            device_desc=$(printf '%s\n' "$port_device_list" | grep "^$port|" | cut -d'|' -f2)
            if [ -z "$device_desc" ]; then
                device_desc="Unknown device"
            fi
            bashio::log.debug "Attempting to detach device on port ${port}: ${device_desc}"
            if usbip detach -p "${port}" 2>/dev/null; then
                bashio::log.info "Successfully detached device on port ${port}: ${device_desc}"
                detached_count=$((detached_count + 1))
            else
                bashio::log.warning "Failed to detach device on port ${port}: ${device_desc}"
                failed_count=$((failed_count + 1))
            fi
        done
        
        bashio::log.info "Detach operation complete: $detached_count detached, $failed_count failed"
    fi
else
    # Read device information from file and detach all ports with descriptions
    bashio::log.info "Reading device information from attachment file..."
    detached_count=0
    failed_count=0
    
    # Get current attached ports
    if ports_output=$(usbip port 2>/dev/null); then
        current_ports=$(echo "$ports_output" | grep -E '^Port [0-9]+:' | sed -E 's/^Port ([0-9]+):.*/\1/')
        
        # Read device descriptions from file
        device_index=0
        while IFS='|' read -r bus_id server_ip device_name device_id; do
            if [ -n "$bus_id" ] && [ -n "$server_ip" ]; then
                device_desc="${device_name} (${device_id}) - Bus ID: ${bus_id}, Server: ${server_ip}"
                
                # Get the corresponding port (ports are assigned in order)
                port=$(echo "$current_ports" | sed -n "$((device_index + 1))p")
                
                if [ -n "$port" ]; then
                    bashio::log.debug "Attempting to detach device on port ${port}: ${device_desc}"
                    if usbip detach -p "${port}" 2>/dev/null; then
                        bashio::log.info "Successfully detached device on port ${port}:\\n\t${device_desc}"
                        detached_count=$((detached_count + 1))
                    else
                        bashio::log.warning "Failed to detach device on port ${port}:\\n\t${device_desc}"
                        failed_count=$((failed_count + 1))
                    fi
                else
                    bashio::log.warning "No corresponding port found for device: ${device_desc}"
                    failed_count=$((failed_count + 1))
                fi
                
                device_index=$((device_index + 1))
            fi
        done < "$device_info_file"
    else
        bashio::log.warning "Could not get port information for device detachment"
    fi
    
    bashio::log.info "Detach operation complete: $detached_count detached, $failed_count failed"
    rm -f "$device_info_file"
fi

bashio::log.info "USB/IP device cleanup finished"
bashio::log.info "🔴 Container stopped"
