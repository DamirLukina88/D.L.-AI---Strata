#!/usr/bin/env bash
# run-code-session.sh - Persistent CLI session for D.L. AI Web Terminal
# Dedicated 100% to CLI (Strata Qwen3.8 Coder Autonomous Agent)
set -e

WORKSPACE_DIR="${STRATA_WORKSPACE_DIR:-$(pwd)}"
SESSION_NAME="${STRATA_SESSION_NAME:-dl-ai-code}"
DL_CLI_BIN="/home/damirl/Desktop/Strata/tools/dl_cli.py"
STRATA_API_KEY="${STRATA_API_KEY:?set STRATA_API_KEY in ~/.config/dl-ai/secrets.env}"

mkdir -p "$WORKSPACE_DIR"
cd "$WORKSPACE_DIR"

export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

CLI_RUNNER="/tmp/dl-ai-cli-runner.sh"
cat << EOF > "$CLI_RUNNER"
#!/usr/bin/env bash
export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export STRATA_URL="http://127.0.0.1:8080"
export STRATA_API_KEY="$STRATA_API_KEY"
export ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
export OPENAI_BASE_URL="http://127.0.0.1:8080/v1"
cd "$WORKSPACE_DIR"

while true; do
    if [ -f "$DL_CLI_BIN" ]; then
        python3 "$DL_CLI_BIN" --workspace "$WORKSPACE_DIR" --url "http://127.0.0.1:8080" --api-key "$STRATA_API_KEY" || true
    else
        echo -e "\033[1;31mError: CLI binary not found ($DL_CLI_BIN)\033[0m"
    fi

    echo -e "\n\033[38;5;244m✦ Session ended.\033[0m Press \033[1;38;5;255m[Enter]\033[0m to restart, or type \033[38;5;208mbash\033[0m for terminal shell:"
    read -r user_choice
    if [ "\$user_choice" = "bash" ] || [ "\$user_choice" = "sh" ]; then
        echo -e "\033[38;5;111mStarting interactive workspace shell (type 'exit' to return)...\033[0m"
        bash -i || true
    fi
    clear
done
EOF
chmod +x "$CLI_RUNNER"

# Check if tmux session already exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME" -n "cli" -c "$WORKSPACE_DIR" "$CLI_RUNNER"
    tmux set-option -t "$SESSION_NAME" mouse on 2>/dev/null || true
    tmux set-option -t "$SESSION_NAME" status off 2>/dev/null || true
else
    # Respawn active window if it died
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^cli$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "cli" -c "$WORKSPACE_DIR" "$CLI_RUNNER"
fi

# Attach client to tmux session
exec tmux attach-session -t "$SESSION_NAME"
