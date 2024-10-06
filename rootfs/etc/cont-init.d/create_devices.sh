#!/command/with-contenv bashio
# shellcheck disable=SC1008

declare server_address
declare bus_id
declare script_directory="/usr/local/bin"
declare mount_script="/usr/local/bin/mount_devices"

bashio::log.info ""
bashio::log.info "----------------------------------------------------------------------"
bashio::log.info "-------------------- Starting USBIP Client Add-on --------------------"
bashio::log.info "----------------------------------------------------------------------"
bashio::log.info ""

if ! bashio::fs.directory_exists "${script_directory}"; then
    bashio::log.info "Creating script directory"
    mkdir -p "${script_directory}" || bashio::exit.nok "Could not create bin folder"
fi

if bashio::fs.file_exists "${mount_script}"; then
    rm "${mount_script}"
fi

touch "${mount_script}"
chmod +x "${mount_script}"
echo '#!/command/with-contenv bashio' >"${mount_script}"
echo 'mount -o remount -t sysfs sysfs /sys' >>"${mount_script}"

for device in $(bashio::config 'devices|keys'); do
    server_address=$(bashio::config "devices[${device}].server_address")
    bus_id=$(bashio::config "devices[${device}].bus_id")
    bashio::log.info "Adding device from server ${server_address} on bus ${bus_id}"

    # Detach any existing attachments
    echo "bashio::log.info \"Detaching device ${bus_id} from server ${server_address} if already attached\"" >>"${mount_script}"
    echo "/usr/sbin/usbip detach -r ${server_address} -b ${bus_id} || true" >>"${mount_script}"

    # Attach the device
    echo "/usr/sbin/usbip attach --remote=${server_address} --busid=${bus_id}" >>"${mount_script}"
done
