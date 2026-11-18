#!/bin/sh
# strata.sh - start, stop and check the local Strata server (this PC's Coder IQ1_M install).
#
#   ./strata.sh start [model]  start in the background and wait until the model is loaded (model: part of a
#                              run-*.sh name, e.g. q2_0, which runs that script instead of the unit)
#   ./strata.sh stop      stop the server (the engine and image encoder end with it)
#   ./strata.sh restart   stop, then start
#   ./strata.sh status    running or not, and what /health says
#   ./strata.sh select    list the installed run-*.sh model scripts
#   ./strata.sh logs      follow the server output (Ctrl+C to leave)
#
# With the systemd user unit strata-server.service installed (tools/systemd/), start, stop, restart and logs go
# through it (STRATA_UNIT names another).  RUN_SCRIPT and PORT can be overridden from the environment, e.g.
# RUN_SCRIPT=./run-q2_0.sh ./strata.sh start

cd "$(dirname "$0")" || exit 1
[ -n "$RUN_SCRIPT" ] && CHOSEN=1               # a script from the environment runs as given, not through the unit
RUN_SCRIPT="${RUN_SCRIPT:-./run-coder-iq1_m.sh}"
PORT="${PORT:-8080}"
OUT="strata-server.out"
PIDFILE="strata-server.pid"
START_TIMEOUT="${START_TIMEOUT:-300}"
# the systemd user unit that runs the server on this PC (Restart=always): stop, start and restart go through it when
# it is there, or systemd starts the server again 5 s after a kill and a nohup copy races it for the port
UNIT="${STRATA_UNIT:-strata-server.service}"

unit_known() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user cat "$UNIT" >/dev/null 2>&1
}

pid() {
    # a pid file only counts while it names a Strata server: a stale one (the server died, or systemd started it)
    # could name any process once the kernel reuses the number, and stop would kill that
    if [ -f "$PIDFILE" ]; then
        p=$(cat "$PIDFILE")
        if kill -0 "$p" 2>/dev/null && tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q "serve/server.py"; then
            echo "$p"
            return 0
        fi
        rm -f "$PIDFILE"
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
    if [ -z "$CHOSEN" ] && unit_known; then
        echo "Starting Strata ($UNIT, port $PORT) ..."
        echo "The PC can be slow for 1-3 minutes while the model loads into RAM."
        systemctl --user start "$UNIT" || return 1
        wait_ready unit
        return $?
    fi
    if [ ! -x "$RUN_SCRIPT" ]; then
        echo "No start script $RUN_SCRIPT - run ./setup.sh first." >&2
        return 1
    fi
    echo "Starting Strata ($RUN_SCRIPT, port $PORT) ..."
    echo "The PC can be slow for 1-3 minutes while the model loads into RAM."
    nohup "$RUN_SCRIPT" > "$OUT" 2>&1 &
    echo $! > "$PIDFILE"
    wait_ready pidfile
}

wait_ready() {                                  # unit: the systemd unit is running it; pidfile: our nohup child
    waited=0
    while [ "$waited" -lt "$START_TIMEOUT" ]; do
        if [ "$1" = unit ]; then
            if ! systemctl --user is-active --quiet "$UNIT"; then
                echo "Strata stopped while starting. See: journalctl --user -u $UNIT" >&2
                return 1
            fi
        elif ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
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
    if unit_known && systemctl --user is-active --quiet "$UNIT"; then
        echo "Stopping Strata ($UNIT) ..."
        systemctl --user stop "$UNIT"
        p=$(pid)                                # a copy started by hand beside it
        if [ -z "$p" ]; then
            end_leftovers
            rm -f "$PIDFILE"
            echo "Strata stopped."
            return 0
        fi
    fi
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
    end_leftovers
    rm -f "$PIDFILE"
    echo "Strata stopped."
}

end_leftovers() {
    # the engine ends with the server; make sure nothing is left holding the GPU
    sleep 1
    left=$(pgrep -f "/engine/strata( |-vision|$)")
    if [ -n "$left" ]; then
        echo "Ending leftover engine processes: $left" >&2
        kill $left 2>/dev/null
    fi
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
                    CHOSEN=1                    # a model chosen by name runs from its own script, not the unit
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
    restart)
        if unit_known && systemctl --user is-active --quiet "$UNIT"; then
            echo "Restarting Strata ($UNIT) ..."
            systemctl --user restart "$UNIT" && wait_ready unit
        else
            stop && start
        fi
        ;;
    status) status ;;
    logs)
        # the unit's output goes to the journal; strata-server.out is only the nohup start's
        if unit_known; then journalctl --user -u "$UNIT" -f; else tail -f "$OUT"; fi
        ;;
    *) echo "Usage: $0 {start [model]|stop|restart|status|select|logs}" >&2; exit 2 ;;
esac
