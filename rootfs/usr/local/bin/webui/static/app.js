/* ============================================================
   USB/IP Terminal WebUI — Frontend JavaScript
   ============================================================ */

const API_BASE = (typeof INGRESS_PATH === 'string' ? INGRESS_PATH : '').replace(/\/+$/, '');

function buildApiUrl(path) {
    const value = `${path || ''}`;
    if (!value) return API_BASE || '';
    if (value.startsWith('http://') || value.startsWith('https://')) return value;
    const normalizedPath = value.startsWith('/') ? value : `/${value}`;
    return API_BASE ? `${API_BASE}${normalizedPath}` : normalizedPath;
}
let logPaused = false;
let logFilter = 'all';
let allLogLines = []; // master unfiltered log buffer
// Controls whether the logs auto-scroll: 'when_not_paused' or 'always'
let logAutoScroll = 'when_not_paused';

// ---- Themes ----
const THEMES = ['green', 'amber', 'blue', 'dracula', 'matrix'];
let currentTheme = localStorage.getItem('usbip-theme') || 'green';

function applyTheme(t) {
    currentTheme = t;
    if (t === 'green') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('usbip-theme', t);
}

function cycleTheme() {
    const idx = THEMES.indexOf(currentTheme);
    const next = THEMES[(idx + 1) % THEMES.length];
    applyTheme(next);
    toast(`Theme: ${next.toUpperCase()}`);
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
    applyTheme(currentTheme);
    initTabs();
    startClock();
    refreshDashboard();
    loadConfig();
    // Start log polling immediately
    fetchAndUpdateLogs();
    setInterval(() => { if (!logPaused) fetchAndUpdateLogs(); }, 4000);

    // Initialize tooltip tap/click behavior for touch devices
    initTooltips();
});

// ---- Clock ----
function startClock() {
    const el = document.getElementById('clock');
    const tick = () => {
        const now = new Date();
        el.textContent = now.toLocaleTimeString('en-US', { hour12: false });
    };
    tick();
    setInterval(tick, 1000);
}

// ---- Tabs ----
function initTabs() {
    document.querySelectorAll('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

            // Auto-refresh on tab switch
            const tab = btn.dataset.tab;
            if (tab === 'dashboard') refreshDashboard();
            else if (tab === 'devices') refreshDevices();
            else if (tab === 'events') refreshEvents();
            else if (tab === 'logs') {
                fetchInitialLogs().then(() => {
                    // Ensure we scroll to the latest logs when switching to Logs tab
                    scrollLogToBottom('log-terminal');
                });
            }
        });
    });
}

// ---- Toast notifications ----
function toast(msg, type = '') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type ? 'toast-' + type : ''}`;
    el.textContent = `> ${msg}`;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// ---- API helper ----
async function api(path, opts = {}) {
    const url = buildApiUrl(path);
    try {
        const resp = await fetch(url, {
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
            },
            ...opts,
        });
        const raw = await resp.text();
        let data = {};
        if (raw) {
            try {
                data = JSON.parse(raw);
            } catch (e) {
                const msg = `Invalid API response (${resp.status}) from ${path}`;
                toast(msg, 'error');
                return { ok: false, error: msg, status: resp.status, url };
            }
        }

        if (!data || typeof data !== 'object') {
            data = {};
        }

        if (!resp.ok && data.ok === undefined) {
            data.ok = false;
        }
        if (!resp.ok && !data.error) {
            data.error = `HTTP ${resp.status}`;
        }
        return data;
    } catch (e) {
        toast(`Network error: ${e.message}`, 'error');
        return { ok: false, error: e.message };
    }
}

// ---- Dashboard ----
async function refreshDashboard() {
    const [status, health] = await Promise.all([
        api('/api/status'),
        api('/api/health'),
    ]);

    // Servers
    const serversEl = document.getElementById('dash-servers');
    if (health.ok && health.servers) {
        const entries = Object.entries(health.servers);
        if (entries.length === 0) {
            serversEl.innerHTML = '<span class="dim">No servers configured</span>';
        } else {
            serversEl.innerHTML = entries.map(([ip, s]) => {
                const latClass = !s.online ? 'latency-bad' : s.latency_ms < 50 ? 'latency-good' : s.latency_ms < 200 ? 'latency-mid' : 'latency-bad';
                const icon = s.online ? '●' : '○';
                const lat = s.online ? `${s.latency_ms}ms` : 'OFFLINE';
                return `<div class="item"><span>${icon} ${ip}</span><span class="${latClass}">${lat}</span></div>`;
            }).join('');
        }
    } else {
        serversEl.innerHTML = '<span class="dim">Health check pending...</span>';
    }

    // Devices
    const countEl = document.getElementById('dash-device-count');
    const summaryEl = document.getElementById('dash-device-summary');
    if (status.ok) {
        const devs = status.devices || [];
        countEl.textContent = devs.length;
        if (devs.length === 0) {
            summaryEl.innerHTML = '<span class="dim">No devices attached</span>';
        } else {
            summaryEl.innerHTML = devs.map(d => {
                const name = d.usb_name || d.device_id || `port ${d.port}`;
                const srv = d.server || '?';
                return `<div class="item"><span>Port ${d.port}: ${esc(name)}</span><span class="dim">${esc(srv)}</span></div>`;
            }).join('');
        }
    } else {
        countEl.textContent = '?';
        summaryEl.innerHTML = '<span class="dim">Could not fetch status</span>';
    }

    // Badge
    const badge = document.getElementById('status-badge');
    if (status.ok && (status.devices || []).length > 0) {
        badge.className = 'badge badge-ok';
        badge.textContent = '● ONLINE';
    } else {
        badge.className = 'badge badge-warn';
        badge.textContent = '○ NO DEVICES';
    }

    // Dependent apps health
    const appsEl = document.getElementById('dash-apps');
    const appHealth = await api('/api/app-health');
    const dependentApps = appHealth.apps || appHealth.addons || [];
    if (appHealth.ok && dependentApps.length > 0) {
        appsEl.innerHTML = dependentApps.map(a => {
            const isUp = a.state === 'started';
            const icon = isUp ? '●' : '○';
            const cls = isUp ? 'badge-ok' : 'badge-error';
            return `<div class="item">
                <span>${icon} ${esc(a.name)}</span>
                <span><span class="badge ${cls}">${esc(a.state.toUpperCase())}</span>
                ${!isUp ? `<button class="btn btn-xs" onclick="restartApp('${esc(a.slug)}','${esc(a.name)}')">RESTART</button>` : ''}
                </span>
            </div>`;
        }).join('');
    } else if (appHealth.ok && dependentApps.length === 0) {
        appsEl.innerHTML = '<span class="dim">No dependent apps configured</span>';
    } else {
        appsEl.innerHTML = `<span class="dim">App health unavailable: ${esc(appHealth.error || 'unknown error')}</span>`;
    }
}

// Auto-refresh dashboard every 15s when visible
setInterval(() => {
    if (document.getElementById('tab-dashboard').classList.contains('active')) {
        refreshDashboard();
    }
}, 15000);

// ---- Devices ----
async function refreshDevices() {
    const data = await api('/api/status');
    const tbody = document.getElementById('attached-body');
    if (!data.ok || !data.devices || data.devices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="dim">No devices attached</td></tr>';
        return;
    }
    tbody.innerHTML = data.devices.map(d => {
        const name = d.usb_name || d.info || '-';
        return `<tr>
      <td><input type="checkbox" class="dev-check" data-port="${d.port}"></td>
      <td>${d.port}</td>
      <td>${esc(name)}</td>
      <td>${esc(d.device_id || '-')}</td>
      <td>${esc(d.server || d.remote_busid || '-')}</td>
      <td><span class="badge badge-ok">${esc(d.status || 'attached')}</span></td>
      <td><button class="btn btn-warn btn-xs" onclick="detachOne(${d.port})">DETACH</button></td>
    </tr>`;
    }).join('');
}

function toggleSelectAll(master, tableId) {
    const checks = document.querySelectorAll(`#${tableId} .dev-check`);
    checks.forEach(c => c.checked = master.checked);
}

async function detachOne(port) {
    const data = await api('/api/detach', { method: 'POST', body: JSON.stringify({ port }) });
    toast(data.ok ? `Port ${port} detached` : `Detach failed: ${data.detail}`, data.ok ? '' : 'error');
    refreshDevices();
    refreshDashboard();
}

async function detachSelected() {
    const checks = document.querySelectorAll('#attached-table .dev-check:checked');
    if (checks.length === 0) { toast('No devices selected', 'warn'); return; }
    for (const c of checks) {
        await api('/api/detach', { method: 'POST', body: JSON.stringify({ port: parseInt(c.dataset.port) }) });
    }
    toast(`Detached ${checks.length} device(s)`);
    refreshDevices();
    refreshDashboard();
}

async function attachSingle() {
    const server = document.getElementById('attach-server').value.trim();
    const busid = document.getElementById('attach-busid').value.trim();
    const name = document.getElementById('attach-name').value.trim() || busid;
    if (!server || !busid) { toast('Server and Bus ID required', 'warn'); return; }

    toast('Attaching...', '');
    const data = await api('/api/attach', { method: 'POST', body: JSON.stringify({ server, busid, name }) });
    toast(data.ok ? `Attached ${name}` : `Failed: ${data.detail}`, data.ok ? '' : 'error');
    refreshDevices();
    refreshDashboard();
}

async function attachAll() {
    toast('Attaching all configured devices...', '');
    const data = await api('/api/attach-all', { method: 'POST' });
    if (data.ok) {
        const ok = data.results.filter(r => r.ok).length;
        const fail = data.results.filter(r => !r.ok).length;
        toast(`Attached: ${ok}, Failed: ${fail}`, fail > 0 ? 'warn' : '');
    } else {
        toast('Attach-all failed', 'error');
    }
    refreshDevices();
    refreshDashboard();
}

async function detachAll() {
    toast('Detaching all devices...', '');
    const data = await api('/api/detach-all', { method: 'POST' });
    if (data.ok) {
        toast(`Detached ${data.detached} device(s)`);
    } else {
        toast('Detach-all failed', 'error');
    }
    refreshDevices();
    refreshDashboard();
}

// ---- Discovery ----
async function discoverDevices() {
    const server = document.getElementById('discover-server').value.trim();
    if (!server) { toast('Enter a server IP', 'warn'); return; }

    const tbody = document.getElementById('discover-body');
    tbody.innerHTML = '<tr><td colspan="5" class="dim"><span class="spinner"></span> Discovering...</td></tr>';

    const data = await api(`/api/discover?server=${encodeURIComponent(server)}`);
    if (!data.ok || !data.devices || data.devices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="dim">No devices found</td></tr>';
        return;
    }
    tbody.innerHTML = data.devices.map(d => `<tr>
    <td>${esc(d.busid)}</td>
    <td>${esc(d.name)}</td>
    <td>${esc(d.device_id)}</td>
    <td class="dim">${esc(d.usb_name || '-')}</td>
    <td><button class="btn btn-xs" onclick="quickAttach('${esc(d.server)}','${esc(d.busid)}','${esc(d.name)}')">▶ ATTACH</button></td>
  </tr>`).join('');
}

function quickAttach(server, busid, name) {
    document.getElementById('attach-server').value = server;
    document.getElementById('attach-busid').value = busid;
    document.getElementById('attach-name').value = name;
    // Switch to devices tab
    document.querySelector('[data-tab="devices"]').click();
    setTimeout(() => attachSingle(), 100);
}

async function scanNetwork() {
    const subnet = document.getElementById('scan-subnet').value.trim();
    if (!subnet) { toast('Enter a subnet', 'warn'); return; }

    const el = document.getElementById('scan-results');
    el.innerHTML = '<span class="spinner"></span> Scanning... (this may take a moment)';

    const data = await api('/api/scan', { method: 'POST', body: JSON.stringify({ subnet }) });
    if (!data.ok) {
        el.innerHTML = `<span class="dim">Error: ${esc(data.error || 'unknown')}</span>`;
        return;
    }
    if (data.servers.length === 0) {
        el.innerHTML = '<span class="dim">No USB/IP servers found</span>';
        return;
    }
    el.innerHTML = data.servers.map(s => {
        const devList = (s.devices || []).map(d =>
            `<div class="item"><span>${esc(d.busid)} — ${esc(d.name)}</span><span class="dim">${esc(d.device_id)}</span></div>`
        ).join('') || '<span class="dim">No devices exported</span>';
        return `<div class="scan-server">
      <div class="scan-server-header" onclick="this.nextElementSibling.classList.toggle('open')">
        <span>● ${esc(s.server)}</span>
        <span class="latency-good">${s.latency_ms}ms — ${s.devices.length} device(s)</span>
      </div>
      <div class="scan-devices">${devList}</div>
    </div>`;
    }).join('');
}

// ---- Logs (polling-based, client-side filtering) ----
async function fetchAndUpdateLogs() {
    // Always fetch ALL logs (no server-side filter)
    const data = await api('/api/logs');
    if (!data.ok || !data.lines) return;

    allLogLines = data.lines;

    // Apply client-side filter for the main Logs tab
    const filtered = getFilteredLines(allLogLines);
    renderLogTerminal('log-terminal', filtered);
    // If the Logs tab is active, ensure we're scrolled to latest based on preference
    const logsTab = document.getElementById('tab-logs');
    const logsVisible = logsTab && logsTab.classList.contains('active');
    if (logsVisible) {
        if (logAutoScroll === 'always' || (logAutoScroll === 'when_not_paused' && !logPaused)) {
            scrollLogToBottom('log-terminal');
        }
    }
}

function getFilteredLines(lines) {
    if (logFilter === 'all') return lines;
    return lines.filter(ln => {
        const lower = ln.toLowerCase();
        // Bashio format: [HH:MM:SS] LEVEL: msg  |  s6 format: s6-rc: info: ...
        if (logFilter === 'error') return lower.includes(' error') || lower.includes(' fatal');
        if (logFilter === 'warning') return lower.includes(' warning') || lower.includes(' warn');
        if (logFilter === 'info') return lower.includes('] info:') || lower.includes(': info:');
        if (logFilter === 'debug') return lower.includes(' debug');
        if (logFilter === 'trace') return lower.includes(' trace');
        return true;
    });
}

function renderLogTerminal(elementId, lines) {
    const el = document.getElementById(elementId);
    if (!el) return;

    // Build a content hash to avoid unnecessary re-renders
    const hash = lines.length + ':' + (lines.length > 0 ? lines[lines.length - 1].substring(0, 40) : '');
    if (el.dataset.contentHash === hash) return;
    el.dataset.contentHash = hash;

    const fragment = document.createDocumentFragment();
    if (lines.length === 0) {
        const div = document.createElement('div');
        div.className = 'log-line dim';
        div.textContent = logFilter !== 'all'
            ? `No ${logFilter.toUpperCase()} level logs found.`
            : 'Waiting for logs...';
        fragment.appendChild(div);
    } else {
        for (const line of lines) {
            const div = document.createElement('div');
            div.className = `log-line ${getLogLevelClass(line)}`;
            div.textContent = line;
            fragment.appendChild(div);
        }
    }
    el.innerHTML = '';
    el.appendChild(fragment);
}

function getLogLevelClass(line) {
    const lower = line.toLowerCase();
    // Bashio format: [HH:MM:SS] LEVEL: msg  |  s6 format: s6-rc: info: ...
    if (lower.includes(' error') || lower.includes(' fatal')) return 'level-error';
    if (lower.includes(' warning')) return 'level-warning';
    if (lower.includes('] info:') || lower.includes(': info:')) return 'level-info';
    if (lower.includes(' debug')) return 'level-debug';
    if (lower.includes(' trace')) return 'level-trace';
    return '';
}

function scrollLogToBottom(elementId = 'log-terminal') {
    const el = document.getElementById(elementId);
    if (!el) return;
    // Immediate scroll attempt
    el.scrollTop = el.scrollHeight;
    // Deferred scroll to handle post-layout recalc (important inside iframes)
    requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
        // Final fallback after browser paint
        setTimeout(() => { el.scrollTop = el.scrollHeight; }, 50);
    });
}

async function fetchInitialLogs() {
    await fetchAndUpdateLogs();
}

// ---- Log controls ----
function toggleLogPause() {
    logPaused = !logPaused;
    const btn = document.getElementById('log-pause-btn');
    if (btn) btn.textContent = logPaused ? '▶ RESUME' : '⏸ PAUSE';
    toast(logPaused ? 'Log paused' : 'Log resumed');
}

function copyLogs() {
    const terminal = document.getElementById('log-terminal');
    const text = Array.from(terminal.querySelectorAll('.log-line')).map(l => l.textContent).join('\n');
    navigator.clipboard.writeText(text).then(() => toast('Logs copied to clipboard'));
}

function clearLogView() {
    document.getElementById('log-terminal').innerHTML = '';
    toast('Log view cleared');
}

function setLogFilter(level, btn) {
    logFilter = level;
    document.querySelectorAll('.log-filter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    // Apply filter client-side immediately from cached data
    const filtered = getFilteredLines(allLogLines);
    // Clear content hash to force re-render
    document.getElementById('log-terminal').dataset.contentHash = '';
    renderLogTerminal('log-terminal', filtered);
}

// ---- Events ----
async function refreshEvents() {
    const data = await api('/api/events');
    const el = document.getElementById('events-timeline');
    if (!data.ok || !data.events || data.events.length === 0) {
        el.innerHTML = '<span class="dim">No events recorded</span>';
        return;
    }
    // Show newest first
    const events = data.events.reverse();
    el.innerHTML = events.map(e => {
        const ts = new Date(e.ts).toLocaleString();
        return `<div class="event-entry">
      <span class="event-ts">${esc(ts)}</span>
      <span class="event-type ${esc(e.type)}">${esc(e.type)}</span>
      <span class="event-detail">${esc(e.device || '')} ${esc(e.server || '')} — ${esc(e.detail)}</span>
    </div>`;
    }).join('');
}

async function clearEvents() {
    await api('/api/events/clear', { method: 'POST' });
    toast('Events cleared');
    refreshEvents();
}

// ---- Config ----
async function loadConfig() {
    const data = await api('/api/config');
    if (!data.ok || !data.config) return;
    const cfg = data.config;

    document.getElementById('cfg-log-level').value = cfg.log_level || 'info';
    document.getElementById('cfg-server').value = cfg.usbipd_server_address || '';
    document.getElementById('cfg-delay').value = cfg.attach_delay ?? 2;

    // Populate discover server field too
    const discSrv = document.getElementById('discover-server');
    if (!discSrv.value) discSrv.value = cfg.usbipd_server_address || '';

    // Populate attach server field
    const attSrv = document.getElementById('attach-server');
    if (!attSrv.value) attSrv.value = cfg.usbipd_server_address || '';

    // Populate scan subnet
    const scanSub = document.getElementById('scan-subnet');
    if (!scanSub.value && cfg.usbipd_server_address) {
        const parts = cfg.usbipd_server_address.split('.');
        if (parts.length === 4) scanSub.value = `${parts[0]}.${parts[1]}.${parts[2]}.0/24`;
    }

    // Devices
    const container = document.getElementById('cfg-devices-list');
    container.innerHTML = '';
    (cfg.devices || []).forEach(d => addDeviceRow(d.name, d.device_or_bus_id, d.server || ''));

    // Monitoring settings
    const monInterval = document.getElementById('cfg-monitor-interval');
    if (monInterval) monInterval.value = cfg.monitor_interval ?? 30;
    const reattRetries = document.getElementById('cfg-reattach-retries');
    if (reattRetries) reattRetries.value = cfg.reattach_retries ?? 3;
    const restRetries = document.getElementById('cfg-restart-retries');
    if (restRetries) restRetries.value = cfg.restart_retries ?? 3;

    // Log auto-scroll preference
    const autoScrollVal = cfg.log_auto_scroll || 'when_not_paused';
    logAutoScroll = autoScrollVal;
    const autoScrollEl = document.getElementById('cfg-log-auto-scroll');
    if (autoScrollEl) autoScrollEl.value = autoScrollVal;

    // Load dependent apps selection
    loadDependentAppsConfig(cfg.dependent_apps || cfg.dependent_addons || []);
}

function addDeviceRow(name = '', devId = '', server = '') {
    const container = document.getElementById('cfg-devices-list');
    const row = document.createElement('div');
    row.className = 'device-row';
    row.innerHTML = `
    <input type="text" placeholder="Name" value="${esc(name)}" class="cfg-dev-name">
    <input type="text" placeholder="Device/Bus ID" value="${esc(devId)}" class="cfg-dev-id">
    <input type="text" placeholder="Server (optional)" value="${esc(server)}" class="cfg-dev-server">
    <button class="btn btn-xs btn-error" onclick="this.parentElement.remove()">✕</button>
  `;
    container.appendChild(row);
}

async function saveConfig() {
    const devices = [];
    document.querySelectorAll('.device-row').forEach(row => {
        const name = row.querySelector('.cfg-dev-name').value.trim();
        const id = row.querySelector('.cfg-dev-id').value.trim();
        const server = row.querySelector('.cfg-dev-server').value.trim();
        if (name || id) {
            const dev = { name: name || id, device_or_bus_id: id };
            if (server) dev.server = server;
            devices.push(dev);
        }
    });

    const delayVal = parseInt(document.getElementById('cfg-delay').value);

    // Read auto-scroll preference and apply it immediately
    const autoScrollEl = document.getElementById('cfg-log-auto-scroll');
    const autoScrollVal = autoScrollEl ? autoScrollEl.value : 'when_not_paused';
    logAutoScroll = autoScrollVal;

    const config = {
        log_level: document.getElementById('cfg-log-level').value,
        usbipd_server_address: document.getElementById('cfg-server').value.trim(),
        attach_delay: isNaN(delayVal) ? 2 : delayVal,
        monitor_interval: parseInt(document.getElementById('cfg-monitor-interval')?.value) || 30,
        reattach_retries: parseInt(document.getElementById('cfg-reattach-retries')?.value) || 3,
        restart_retries: parseInt(document.getElementById('cfg-restart-retries')?.value) || 3,
        log_auto_scroll: autoScrollVal,
        devices,
    };

    // Preserve dependent_apps from current config (saved separately)
    const curCfg = await api('/api/config');
    if (curCfg.ok && curCfg.config) {
        config.dependent_apps = curCfg.config.dependent_apps || curCfg.config.dependent_addons || [];
    }

    toast('Saving configuration...');
    const data = await api('/api/config', { method: 'POST', body: JSON.stringify(config) });
    toast(data.ok ? 'Configuration saved! Restart app to apply.' : 'Save failed', data.ok ? '' : 'error');
}

async function backupConfig() {
    const data = await api('/api/config/backup');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `usbip-config-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast('Config exported');
}

function restoreConfig(input) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const config = JSON.parse(e.target.result);
            const data = await api('/api/config/restore', { method: 'POST', body: JSON.stringify(config) });
            toast(data.ok ? 'Config restored! Restart app to apply.' : 'Restore failed', data.ok ? '' : 'error');
            loadConfig();
        } catch (err) {
            toast('Invalid JSON file', 'error');
        }
    };
    reader.readAsText(file);
    input.value = '';
}

// ---- Utilities ----
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

// ---------------------------------------------------------------------------
// Tooltips: enable tap-to-toggle on touch devices and accessible hide-on-outside/Escape
// ---------------------------------------------------------------------------
function initTooltips() {
    // Toggle tooltip visibility on click/tap
    document.querySelectorAll('.hint').forEach(h => {
        h.setAttribute('aria-expanded', 'false');
        // Click/tap handler
        h.addEventListener('click', (ev) => {
            // Toggle visible state
            const visible = h.classList.toggle('tooltip-visible');
            h.setAttribute('aria-expanded', visible ? 'true' : 'false');
            // Close other tooltips
            if (visible) {
                document.querySelectorAll('.hint.tooltip-visible').forEach(other => {
                    if (other !== h) {
                        other.classList.remove('tooltip-visible');
                        other.setAttribute('aria-expanded', 'false');
                    }
                });
            }
            // Prevent click from bubbling to document handler immediately
            ev.stopPropagation();
        });

        // Close tooltip when it loses focus (keyboard users)
        h.addEventListener('blur', () => {
            h.classList.remove('tooltip-visible');
            h.setAttribute('aria-expanded', 'false');
        });
    });

    // Click outside closes any visible tooltips
    document.addEventListener('click', (ev) => {
        if (!ev.target.closest('.hint')) {
            document.querySelectorAll('.hint.tooltip-visible').forEach(h => {
                h.classList.remove('tooltip-visible');
                h.setAttribute('aria-expanded', 'false');
            });
        }
    });

    // Escape closes tooltips
    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') {
            document.querySelectorAll('.hint.tooltip-visible').forEach(h => {
                h.classList.remove('tooltip-visible');
                h.setAttribute('aria-expanded', 'false');
            });
        }
    });
}


// ---- Dependent Apps ----
let _selectedDependentApps = []; // current selection

async function restartApp(slug, name) {
    toast(`Restarting ${name}...`);
    const data = await api('/api/app-restart', { method: 'POST', body: JSON.stringify({ slug }) });
    toast(data.ok ? `${name} restarted` : `Restart failed`, data.ok ? '' : 'error');
    refreshDashboard();
}

function loadDependentAppsConfig(apps) {
    _selectedDependentApps = apps || [];
    renderDependentAppsList();
}

function renderDependentAppsList() {
    const el = document.getElementById('cfg-dependent-apps-list');
    if (!el) return;
    if (_selectedDependentApps.length === 0) {
        el.innerHTML = '<span class="dim">No apps selected. Click DISCOVER to find installed apps.</span>';
        return;
    }
    el.innerHTML = _selectedDependentApps.map((a, i) => `
        <div class="device-row">
            <input type="text" value="${esc(a.name)}" class="dep-app-name" readonly>
            <input type="text" value="${esc(a.slug)}" class="dep-app-slug" readonly>
            <button class="btn btn-xs btn-error" onclick="removeDependentApp(${i})">\u2715</button>
        </div>
    `).join('');
}

function removeDependentApp(index) {
    _selectedDependentApps.splice(index, 1);
    renderDependentAppsList();
}

async function loadAvailableApps() {
    toast('Discovering installed apps...');
    const data = await api('/api/apps');
    const installedApps = data.apps || data.addons || [];
    if (!data.ok || !installedApps) {
        toast('Could not fetch apps', 'error');
        return;
    }
    // Filter out self and show selection dialog
    const available = installedApps.filter(a => a.slug !== 'local_ha_usbip_client' && a.slug !== 'ha_usbip_client');
    if (available.length === 0) {
        toast('No other apps found');
        return;
    }
    // Build a selection overlay
    const selectedSlugs = new Set(_selectedDependentApps.map(a => a.slug));
    const el = document.getElementById('cfg-dependent-apps-list');
    el.innerHTML = `
        <div style="max-height:300px;overflow-y:auto;border:1px solid var(--dim);padding:.5rem;margin-bottom:.5rem">
        ${available.map(a => {
        const checked = selectedSlugs.has(a.slug) ? 'checked' : '';
        const stateClass = a.state === 'started' ? 'badge-ok' : 'badge-error';
        return `<label style="display:flex;align-items:center;gap:.5rem;padding:.2rem 0;cursor:pointer">
                <input type="checkbox" class="dep-app-check" data-slug="${esc(a.slug)}" data-name="${esc(a.name)}" ${checked}>
                <span>${esc(a.name)}</span>
                <span class="badge ${stateClass}" style="font-size:.7rem">${esc(a.state)}</span>
                <span class="dim" style="font-size:.7rem">${esc(a.slug)}</span>
            </label>`;
    }).join('')}
        </div>
        <button class="btn btn-sm" onclick="applyAppSelection()">\u2713 APPLY SELECTION</button>
    `;
    toast(`Found ${available.length} app(s)`);
}

function applyAppSelection() {
    const checks = document.querySelectorAll('.dep-app-check:checked');
    _selectedDependentApps = Array.from(checks).map(c => ({
        name: c.dataset.name,
        slug: c.dataset.slug,
    }));
    renderDependentAppsList();
    toast(`${_selectedDependentApps.length} app(s) selected`);
}

async function saveDependentApps() {
    toast('Saving dependent apps...');
    const data = await api('/api/dependent-apps', {
        method: 'POST',
        body: JSON.stringify({ dependent_apps: _selectedDependentApps }),
    });
    toast(data.ok ? 'Dependent apps saved!' : 'Save failed', data.ok ? '' : 'error');
}
