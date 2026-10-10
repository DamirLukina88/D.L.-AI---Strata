#!/bin/sh
# strata.sh - start, stop and check the local Strata server (this PC's Coder IQ1_M install).
#
#   ./strata.sh start     start in the background and wait until the model is loaded
#   ./strata.sh stop      stop the server (the engine and image encoder end with it)
#   ./strata.sh restart   stop, then start
#   ./strata.sh status    running or not, and what /health says
#   ./strata.sh logs      follow the server output (Ctrl+C to leave)
#
# RUN_SCRIPT and PORT can be overridden from the environment, e.g. RUN_SCRIPT=./run-iq2_xs.sh ./strata.sh start

cd "$(dirname "$0")" || exit 1
RUN_SCRIPT="${RUN_SCRIPT:-./run-coder-iq1_m.sh}"
PORT="${PORT:-8080}"
OUT="strata-server.out"
PIDFILE="strata-server.pid"
START_TIMEOUT="${START_TIMEOUT:-300}"

pid() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        cat "$PIDFILE"
        return 0
    fi
    # started some other way: find the server process by its script
    pgrep -f "serve/server.py --engine strata" | head -n 1
}

health() {
    curl -s -m 3 "http://127.0.0.1:$PORT/health"
}

start() {
    p=$(pid)
    if [ -n "$p" ]; then
        echo "Strata is already running (pid $p)."
        return 0
    fi
    if [ ! -x "$RUN_SCRIPT" ]; then
        echo "No start script $RUN_SCRIPT - run ./setup.sh first." >&2
        return 1
    fi
    echo "Starting Strata ($RUN_SCRIPT, port $PORT) ..."
    echo "The PC can be slow for 1-3 minutes while the model loads into RAM."
    nohup "$RUN_SCRIPT" > "$OUT" 2>&1 &
    echo $! > "$PIDFILE"
    waited=0
    while [ "$waited" -lt "$START_TIMEOUT" ]; do
        if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Strata stopped while starting. The end of $OUT:" >&2
            tail -n 20 "$OUT" >&2
            rm -f "$PIDFILE"
            return 1
        fi
        if health | grep -q '"status": *"ok"'; then
            echo "Strata is ready after ${waited}s: http://127.0.0.1:$PORT (API: /v1)"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    echo "Not ready after ${START_TIMEOUT}s; still loading? Check: ./strata.sh logs" >&2
    return 1
}

stop() {
    p=$(pid)
    if [ -z "$p" ]; then
        echo "Strata is not running."
        rm -f "$PIDFILE"
        return 0
    fi
    echo "Stopping Strata (pid $p) ..."
    kill "$p"
    waited=0
    while kill -0 "$p" 2>/dev/null && [ "$waited" -lt 30 ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if kill -0 "$p" 2>/dev/null; then
        echo "Still running after 30s; forcing it." >&2
        kill -9 "$p"
    fi
    # the engine ends with the server; make sure nothing is left holding the GPU
    sleep 1
    left=$(pgrep -f "/engine/strata( |-vision|$)")
    if [ -n "$left" ]; then
        echo "Ending leftover engine processes: $left" >&2
        kill $left 2>/dev/null
    fi
    rm -f "$PIDFILE"
    echo "Strata stopped."
}

status() {
    p=$(pid)
    if [ -z "$p" ]; then
        echo "Strata is not running."
        return 3
    fi
    echo "Strata is running (pid $p)."
    h=$(health)
    if [ -n "$h" ]; then
        echo "$h"
    else
        echo "No answer on port $PORT yet (still loading?)."
    fi
}

case "$1" in
    start)
        if [ -n "$2" ]; then
            for s in run-*.sh; do
                if echo "$s" | grep -qi "$2"; then
                    RUN_SCRIPT="./$s"
                    break
                fi
            done
        fi
        start
        ;;
    select)
        echo "Installed model configurations:"
        models=$(ls run-*.sh 2>/dev/null)
        if [ -z "$models" ]; then
            echo "No run-*.sh scripts found." >&2
            exit 1
        fi
        echo "$models"
        echo ""
        echo "To start a specific model, run: ./strata.sh start <name>"
        ;;
    stop) stop ;;
    restart) stop && start ;;
    status) status ;;
    logs) tail -f "$OUT" ;;
    *) echo "Usage: $0 {start [model]|stop|restart|status|select|logs}" >&2; exit 2 ;;
esac
