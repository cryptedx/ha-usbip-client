#!/command/with-contenv bashio
# shellcheck disable=SC1008
bashio::config.require 'log_level'
bashio::log.level "$(bashio::config 'log_level')"

declare server_address
declare bus_id
declare script_directory="/usr/local/bin"
declare mount_script="/usr/local/bin/mount_devices"
declare discovery_server_address

discovery_server_address=$(bashio::config 'discovery_server_address')

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
bashio::log.info "Discovering devices from server ${discovery_server_address}."
device_info_file="/tmp/device_details.txt"
rm -f "$device_info_file"

if available_devices=$(usbip list -r "${discovery_server_address}" 2>/dev/null); then
    if [ -z "$available_devices" ]; then
        bashio::log.warning "No devices found on server ${discovery_server_address}."
    else
        bashio::log.info "Available devices from ${discovery_server_address}:"
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
    bashio::log.error "Failed to retrieve device list from server ${discovery_server_address}."
fi

# Loop through configured devices
bashio::log.info "Iterating over configured devices."
for device in $(bashio::config 'devices|keys'); do
    server_address=$(bashio::config "devices[${device}].server_address")
    bus_id=$(bashio::config "devices[${device}].bus_id")

    bashio::log.info "Adding device from server ${server_address} on bus ${bus_id}"

    # Detach any existing attachments
    bashio::log.debug "Detaching device ${bus_id} from server ${server_address} if already attached."
    echo "/usr/sbin/usbip detach -r ${server_address} -b ${bus_id} >/dev/null 2>&1 || true" >>"${mount_script}"

    # Attach the device
    bashio::log.debug "Attaching device ${bus_id} from server ${server_address}."
    echo "/usr/sbin/usbip attach --remote=${server_address} --busid=${bus_id}" >>"${mount_script}"
done

bashio::log.info "Device configuration complete. Ready to attach devices."
