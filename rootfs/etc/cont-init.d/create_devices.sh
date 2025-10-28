#!/command/with-contenv bashio
# shellcheck disable=SC1008
bashio::config.require 'log_level'
bashio::log.level "$(bashio::config 'log_level')"

declare usbipd_server_address
declare bus_id
declare script_directory="/usr/local/bin"
declare mount_script="/usr/local/bin/mount_devices"
declare usbipd_server_address

usbipd_server_address=$(bashio::config 'usbipd_server_address')

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
echo '#!/command/with-contenv bashio' >"${mount_script}"
echo 'mount -o remount -t sysfs sysfs /sys' >>"${mount_script}"
bashio::log.debug "Mount script initialization complete."

# Discover available devices
bashio::log.info "Discovering devices from server ${usbipd_server_address}."
device_info_file="/tmp/device_details.txt"
rm -f "$device_info_file"

if available_devices=$(usbip list -r "${usbipd_server_address}" 2>/dev/null); then
    if [ -z "$available_devices" ]; then
        bashio::log.warning "No devices found on server ${usbipd_server_address}."
    else
        bashio::log.info "Available devices from ${usbipd_server_address}:"
        echo "$available_devices" | while read -r line; do
            bashio::log.info "$line"
            
            # Parse device information: "bus_id: vendor : device_name (device_id)"
            # Example: "1-1.2: Sigma Designs, Inc. : Aeotec Z-Stick Gen5 (ZW090) - UZB (0658:0200)"
            if echo "$line" | grep -q '^[0-9.-]\+:\s.*\s([0-9a-fA-F]\+:[0-9a-fA-F]\+)$'; then
                bus_id=$(echo "$line" | sed -E 's/^([0-9.-]+):.*/\1/')
                device_id=$(echo "$line" | sed -E 's/.*\(([0-9a-fA-F]+:[0-9a-fA-F]+)\)$/\1/')
                # Extract device name: everything after "bus_id: " and before " (device_id)"
                temp_line=$(echo "$line" | sed -E "s/^${bus_id}: //")
                device_name=$(echo "$temp_line" | sed -E "s/ \\(${device_id}\\)$//" | sed 's/^\s*//;s/\s*$//')
                
                if [ -n "$bus_id" ] && [ -n "$device_name" ] && [ -n "$device_id" ]; then
                    echo "${bus_id}|${device_name}|${device_id}" >> "$device_info_file"
                    bashio::log.debug "Stored device info: Bus=${bus_id}, Name='${device_name}', ID=${device_id}"
                fi
            fi
        done
    fi
else
    bashio::log.error "Failed to retrieve device list from server ${usbipd_server_address}."
fi

# Loop through configured devices
bashio::log.info "Iterating over configured devices."
devices_count=$(bashio::config 'devices|length')
bashio::log.debug "Found ${devices_count} configured devices"

for ((i = 0; i < devices_count; i++)); do
    device_name=$(bashio::config "devices[${i}].name")
    device_or_bus_id=$(bashio::config "devices[${i}].device_or_bus_id")

    bashio::log.debug "Device ${i} (${device_name}): identifier='${device_or_bus_id}'"

    # Validate configuration
    if [ -z "$device_or_bus_id" ] || [ "$device_or_bus_id" = "null" ]; then
        bashio::log.warning "Device ${i} (${device_name}): device_or_bus_id is empty, skipping"
        continue
    fi

    # Auto-detect format: device_id looks like XXXX:XXXX, bus_id looks like X-X.X or X-X.X.X
    if [[ "$device_or_bus_id" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$ ]]; then
        # It's a device_id in format XXXX:XXXX
        bashio::log.info "Device ${i} (${device_name}): Detected device_id format (${device_or_bus_id})"
        
        # Find the bus_id by matching device_id in discovered devices
        bus_id=$(grep "${device_or_bus_id}" "$device_info_file" 2>/dev/null | cut -d'|' -f1)
        
        if [ -z "$bus_id" ]; then
            bashio::log.warning "Device ${i} (${device_name}): device_id ${device_or_bus_id} not found on server ${usbipd_server_address}"
            continue
        fi
        bashio::log.info "Device ${i} (${device_name}): Found bus_id ${bus_id} for device_id ${device_or_bus_id}"
        
    else
        # Assume it's a bus_id in format like 1-1.2 or 1-1.1.3
        bashio::log.info "Device ${i} (${device_name}): Using bus_id format (${device_or_bus_id})"
        bus_id="$device_or_bus_id"
    fi

    # Detach any existing attachments
    bashio::log.debug "Device ${i} (${device_name}): Detaching device ${bus_id} from server ${usbipd_server_address} if already attached."
    echo "/usr/sbin/usbip detach -r ${usbipd_server_address} -b ${bus_id} >/dev/null 2>&1 || true" >>"${mount_script}"

    # Attach the device
    bashio::log.debug "Device ${i} (${device_name}): Attaching device ${bus_id} from server ${usbipd_server_address}."
    echo "/usr/sbin/usbip attach --remote=${usbipd_server_address} --busid=${bus_id}" >>"${mount_script}"
done

bashio::log.info "Device configuration complete. Ready to attach devices."
