#!/usr/bin/env bash
# run-code-session.sh - Persistent Claude Code CLI session for D.L. AI Web Terminal
set -e

WORKSPACE_DIR="${STRATA_WORKSPACE_DIR:-$(pwd)}"
SESSION_NAME="${STRATA_SESSION_NAME:-dl-ai-code}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")}"
STRATA_API_KEY="${STRATA_API_KEY:-}"
STRATA_MODEL="${STRATA_MODEL:-haiku}"

mkdir -p "$WORKSPACE_DIR"
cd "$WORKSPACE_DIR"

export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
export ANTHROPIC_AUTH_TOKEN="$STRATA_API_KEY"
export ANTHROPIC_MODEL="$STRATA_MODEL"
export CLAUDE_CODE_AUTO_MODE_SERVER="0"

# Inner runner loop executed inside tmux
INNER_RUNNER="/tmp/dl-ai-code-runner.sh"
cat << EOF > "$INNER_RUNNER"
#!/usr/bin/env bash
export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
export ANTHROPIC_AUTH_TOKEN="$STRATA_API_KEY"
export ANTHROPIC_MODEL="$STRATA_MODEL"
export CLAUDE_CODE_AUTO_MODE_SERVER="0"
cd "$WORKSPACE_DIR"

while true; do
    echo -e "\033[1;36m=====================================================\033[0m"
    echo -e "\033[1;32m  D.L. AI — Claude Code CLI on Local Strata Engine  \033[0m"
    echo -e "\033[0;37m  Workspace: $WORKSPACE_DIR\033[0m"
    echo -e "\033[0;37m  Model:     $STRATA_MODEL (Local)\033[0m"
    echo -e "\033[1;36m=====================================================\033[0m\n"

    # Launch Claude Code CLI with local Strata model
    if [ -x "$CLAUDE_BIN" ]; then
        "$CLAUDE_BIN" --model "$STRATA_MODEL" || true
    elif command -v claude >/dev/null 2>&1; then
        claude --model "$STRATA_MODEL" || true
    else
        echo -e "\033[1;31mError: claude binary not found ($CLAUDE_BIN)\033[0m"
    fi

    echo -e "\n\033[1;33mClaude Code session ended.\033[0m"
    echo -e "Press \033[1m[Enter]\033[0m to restart Claude, or type \033[1mbash\033[0m for terminal shell:"
    read -r user_choice
    if [ "\$user_choice" = "bash" ] || [ "\$user_choice" = "sh" ]; then
        echo -e "\033[1;34mStarting interactive workspace shell (type 'exit' to return to Claude)...\033[0m"
        bash -i || true
    fi
    clear
done
EOF

chmod +x "$INNER_RUNNER"

# Check if tmux session already exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME" -c "$WORKSPACE_DIR" "$INNER_RUNNER"
    # Set useful tmux options for web terminal
    tmux set-option -t "$SESSION_NAME" mouse on 2>/dev/null || true
    tmux set-option -t "$SESSION_NAME" status off 2>/dev/null || true
fi

# Attach client to tmux session
exec tmux attach-session -t "$SESSION_NAME"
