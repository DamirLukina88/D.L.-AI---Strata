#!/bin/bash
# Watchdog script for Strata D.L. AI server.
# Checks health endpoint every 30 seconds.
# If the HTTP server hangs (unresponsive for >10s) or returns an error 3 consecutive times,
# it issues a systemctl restart to recover immediately.
# A server that was stopped on purpose (systemctl --user stop strata-server) is left alone.
#
# Proton Mail Bridge (protonmail-bridge.service), once that unit is enabled: started again when it is not running
# (killed, crashed past systemd's retries), and restarted when its IMAP port stops answering 3 times in a row.
# The D.L. AI session daemon (dl-ai-sessiond.service, which runs the scheduled jobs): the same, checked on its socket.

FAILURES=0
MAX_FAILURES=3
HEALTH_URL="http://127.0.0.1:8080/health"
BRIDGE_UNIT="protonmail-bridge.service"
BRIDGE_IMAP_PORT="${PROTON_IMAP_PORT:-1143}"
BRIDGE_FAILURES=0

SESSIOND_UNIT="dl-ai-sessiond.service"
SESSIOND_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/dl-ai/sessiond.sock"
SESSIOND_FAILURES=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

check_bridge() {
    systemctl --user is-enabled --quiet "$BRIDGE_UNIT" 2>/dev/null || return 0
    if ! systemctl --user is-active --quiet "$BRIDGE_UNIT"; then
        log "Proton Mail Bridge is not running. Starting it..."
        systemctl --user reset-failed "$BRIDGE_UNIT" 2>/dev/null
        systemctl --user start "$BRIDGE_UNIT"
        BRIDGE_FAILURES=0
        return 0
    fi
    # IMAP greets with "* OK" as soon as the connection opens
    if timeout 10 bash -c "exec 3<>/dev/tcp/127.0.0.1/$BRIDGE_IMAP_PORT && head -c 4 <&3" 2>/dev/null | grep -q '^\* OK'; then
        BRIDGE_FAILURES=0
    else
        BRIDGE_FAILURES=$((BRIDGE_FAILURES + 1))
        log "Proton Mail Bridge IMAP check failed ($BRIDGE_FAILURES/$MAX_FAILURES)"
        if [ "$BRIDGE_FAILURES" -ge "$MAX_FAILURES" ]; then
            log "Proton Mail Bridge is unresponsive. Restarting it..."
            systemctl --user restart "$BRIDGE_UNIT"
            BRIDGE_FAILURES=0
        fi
    fi
}

check_sessiond() {
    systemctl --user is-enabled --quiet "$SESSIOND_UNIT" 2>/dev/null || return 0
    if ! systemctl --user is-active --quiet "$SESSIOND_UNIT"; then
        log "D.L. AI session daemon is not running. Starting it..."
        systemctl --user reset-failed "$SESSIOND_UNIT" 2>/dev/null
        systemctl --user start "$SESSIOND_UNIT"
        SESSIOND_FAILURES=0
        return 0
    fi
    # the daemon answers {"op": "state"} on its socket with one JSON line
    if timeout 10 python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(8); s.connect(sys.argv[1]); s.sendall(b"{\"op\": \"state\"}\n"); sys.exit(0 if b"\"type\"" in s.recv(65536) else 1)' "$SESSIOND_SOCK" 2>/dev/null; then
        SESSIOND_FAILURES=0
    else
        SESSIOND_FAILURES=$((SESSIOND_FAILURES + 1))
        log "D.L. AI session daemon check failed ($SESSIOND_FAILURES/$MAX_FAILURES)"
        if [ "$SESSIOND_FAILURES" -ge "$MAX_FAILURES" ]; then
            log "D.L. AI session daemon is unresponsive. Restarting it..."
            systemctl --user restart "$SESSIOND_UNIT"
            SESSIOND_FAILURES=0
        fi
    fi
}

while true; do
    sleep 30
    check_bridge
    check_sessiond
    systemctl --user is-active --quiet strata-server || { FAILURES=0; continue; }
    if curl -s -m 10 "$HEALTH_URL" | grep -q '"status": "ok"'; then
        FAILURES=0
    else
        FAILURES=$((FAILURES + 1))
        log "Strata health check failed ($FAILURES/$MAX_FAILURES)"
        if [ "$FAILURES" -ge "$MAX_FAILURES" ]; then
            log "Strata is unresponsive. Restarting service..."
            systemctl --user restart strata-server
            FAILURES=0
            sleep 15
        fi
    fi
done
