#!/command/with-contenv bashio
# shellcheck disable=SC1008
bashio::config.require 'log_level'
bashio::log.level "$(bashio::config 'log_level')"

declare default_server
declare script_directory="/usr/local/bin"
declare mount_script="/usr/local/bin/mount_devices"
declare device_info_file="/tmp/device_details.txt"
declare attach_delay

default_server=$(bashio::config 'usbipd_server_address')

# Read attach_delay with default of 2 seconds
if bashio::config.exists 'attach_delay'; then
    attach_delay=$(bashio::config 'attach_delay')
else
    attach_delay=2
fi

bashio::log.info ""
bashio::log.info "-----------------------------------------------------------------------"
bashio::log.info "-------------------- Starting USB/IP Client Add-on --------------------"
bashio::log.info "-----------------------------------------------------------------------"
bashio::log.info ""

# Check if the script directory exists and log details
bashio::log.debug "Checking if script directory ${script_directory} exists."
if ! bashio::fs.directory_exists "${script_directory}"; then
    bashio::log.info "Creating script directory at ${script_directory}."
    mkdir -p "${script_directory}" || bashio::exit.nok "Could not create bin folder"
else
    bashio::log.debug "Script directory ${script_directory} already exists."
fi

# Create or clean the mount script
bashio::log.debug "Checking if mount script ${mount_script} exists."
if bashio::fs.file_exists "${mount_script}"; then
    bashio::log.info "Mount script already exists. Removing old script."
    rm "${mount_script}"
fi
bashio::log.info "Creating new mount script at ${mount_script}."
touch "${mount_script}" || bashio::exit.nok "Could not create mount script"
chmod +x "${mount_script}"

# Write initial content to the mount script
cat > "${mount_script}" << 'SCRIPT_HEADER'
#!/command/with-contenv bashio
mount -o remount -t sysfs sysfs /sys
sleep 0.5

ATTACH_DELAY=ATTACH_DELAY_PLACEHOLDER
ATTACH_RETRIES=3
FAILED=0
SUCCEEDED=0

attach_device() {
    local server="$1"
    local bus_id="$2"
    local device_name="$3"
    local attempt=0

    # Detach first if already attached
    /usr/sbin/usbip detach -r "${server}" -b "${bus_id}" >/dev/null 2>&1 || true

    while [ $attempt -lt $ATTACH_RETRIES ]; do
        attempt=$((attempt + 1))
        bashio::log.debug "Attaching ${device_name} (${bus_id}) from ${server} - attempt ${attempt}/${ATTACH_RETRIES}"

        if /usr/sbin/usbip attach --remote="${server}" --busid="${bus_id}" 2>/dev/null; then
            bashio::log.info "Successfully attached: ${device_name} (${bus_id}) from ${server}"
            SUCCEEDED=$((SUCCEEDED + 1))
            return 0
        fi

        bashio::log.warning "Attach attempt ${attempt}/${ATTACH_RETRIES} failed for ${device_name} (${bus_id}) from ${server}"
        if [ $attempt -lt $ATTACH_RETRIES ]; then
            sleep "${ATTACH_DELAY}"
        fi
    done

    bashio::log.error "Failed to attach ${device_name} (${bus_id}) from ${server} after ${ATTACH_RETRIES} attempts"
    FAILED=$((FAILED + 1))
    return 1
}

SCRIPT_HEADER

# Replace delay placeholder in the mount script
sed -i "s/ATTACH_DELAY_PLACEHOLDER/${attach_delay}/" "${mount_script}"

bashio::log.debug "Mount script initialization complete."
bashio::log.info "Attach delay between devices: ${attach_delay}s"

# ---- Collect unique server addresses ----
devices_count=$(bashio::config 'devices|length')
bashio::log.debug "Found ${devices_count} configured devices"

declare -A server_set
server_set["${default_server}"]=1

for ((i = 0; i < devices_count; i++)); do
    device_server=$(bashio::config "devices[${i}].server" 2>/dev/null) || device_server=""
    if [ -n "$device_server" ] && [ "$device_server" != "null" ]; then
        server_set["${device_server}"]=1
    fi
done

unique_servers="${!server_set[*]}"
bashio::log.debug "Unique servers to discover: ${unique_servers}"

# ---- Discover available devices from all servers ----
rm -f "$device_info_file"

for server_ip in $unique_servers; do
    bashio::log.info "Discovering devices from server ${server_ip}."

    if available_devices=$(usbip list -r "${server_ip}" 2>/dev/null); then
        if [ -z "$available_devices" ]; then
            bashio::log.warning "No devices found on server ${server_ip}."
        else
            bashio::log.info "Available devices from ${server_ip}:"
            echo "$available_devices" | while read -r line; do
                bashio::log.info "$line"

                # Parse device information: "bus_id: vendor : device_name (device_id)"
                if echo "$line" | grep -q '^[0-9.-]\+:\s.*\s([0-9a-fA-F]\+:[0-9a-fA-F]\+)$'; then
                    bus_id=$(echo "$line" | sed -E 's/^([0-9.-]+):.*/\1/')
                    device_id=$(echo "$line" | sed -E 's/.*\(([0-9a-fA-F]+:[0-9a-fA-F]+)\)$/\1/')
                    temp_line=$(echo "$line" | sed -E "s/^${bus_id}: //")
                    device_name=$(echo "$temp_line" | sed -E "s/ \\(${device_id}\\)$//" | sed 's/^\s*//;s/\s*$//')

                    if [ -n "$bus_id" ] && [ -n "$device_name" ] && [ -n "$device_id" ]; then
                        echo "${server_ip}|${bus_id}|${device_name}|${device_id}" >> "$device_info_file"
                        bashio::log.debug "Stored device info: Server=${server_ip}, Bus=${bus_id}, Name='${device_name}', ID=${device_id}"
                    fi
                fi
            done
        fi
    else
        bashio::log.error "Failed to retrieve device list from server ${server_ip}."
    fi
done

# ---- Loop through configured devices and generate mount script ----
bashio::log.info "Iterating over configured devices."

for ((i = 0; i < devices_count; i++)); do
    device_name=$(bashio::config "devices[${i}].name")
    device_or_bus_id=$(bashio::config "devices[${i}].device_or_bus_id")

    # Determine server for this device (per-device override or global default)
    device_server=$(bashio::config "devices[${i}].server" 2>/dev/null) || device_server=""
    if [ -z "$device_server" ] || [ "$device_server" = "null" ]; then
        device_server="${default_server}"
    fi

    bashio::log.debug "Device ${i} (${device_name}): identifier='${device_or_bus_id}', server='${device_server}'"

    # Validate configuration
    if [ -z "$device_or_bus_id" ] || [ "$device_or_bus_id" = "null" ]; then
        bashio::log.warning "Device ${i} (${device_name}): device_or_bus_id is empty, skipping"
        continue
    fi

    # Auto-detect format: device_id looks like XXXX:XXXX, bus_id looks like X-X.X or X-X.X.X
    if [[ "$device_or_bus_id" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$ ]]; then
        bashio::log.info "Device ${i} (${device_name}): Detected device_id format (${device_or_bus_id})"

        # Find the bus_id by matching device_id + server in discovered devices
        bus_id=$(grep "^${device_server}|" "$device_info_file" 2>/dev/null | grep "${device_or_bus_id}" | cut -d'|' -f2)

        if [ -z "$bus_id" ]; then
            bashio::log.warning "Device ${i} (${device_name}): device_id ${device_or_bus_id} not found on server ${device_server}"
            continue
        fi
        bashio::log.info "Device ${i} (${device_name}): Found bus_id ${bus_id} for device_id ${device_or_bus_id}"
    else
        bashio::log.info "Device ${i} (${device_name}): Using bus_id format (${device_or_bus_id})"
        bus_id="$device_or_bus_id"
    fi

    # Add attach call to mount script with delay between devices
    bashio::log.info "Adding device from server ${device_server} on bus ${bus_id}"
    if [ "$i" -gt 0 ]; then
        echo "sleep \${ATTACH_DELAY}" >> "${mount_script}"
    fi
    echo "attach_device '${device_server}' '${bus_id}' '${device_name}'" >> "${mount_script}"
done

# Write summary footer to mount script
cat >> "${mount_script}" << 'SCRIPT_FOOTER'

bashio::log.info "${SUCCEEDED} device(s) attached, ${FAILED} failed."
if [ $FAILED -gt 0 ]; then
    exit 1
fi
exit 0
SCRIPT_FOOTER

bashio::log.info "Device configuration complete. Ready to attach devices."
