#!/bin/bash
# Watchdog script for Strata D.L. AI server.
# Checks health endpoint every 30 seconds.
# If the HTTP server hangs (unresponsive for >10s) or returns an error 3 consecutive times,
# it issues a systemctl restart to recover immediately.

FAILURES=0
MAX_FAILURES=3
HEALTH_URL="http://127.0.0.1:8080/health"

while true; do
    sleep 30
    if curl -s -m 10 "$HEALTH_URL" | grep -q '"status": "ok"'; then
        FAILURES=0
    else
        FAILURES=$((FAILURES + 1))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Strata health check failed ($FAILURES/$MAX_FAILURES)"
        if [ "$FAILURES" -ge "$MAX_FAILURES" ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Strata is unresponsive. Restarting service..."
            systemctl --user restart strata-server
            FAILURES=0
            sleep 15
        fi
    fi
done
