#!/usr/bin/env bash
# run-code-session.sh - Persistent Multi-Scaffold CLI session for D.L. AI Web Terminal
# Supports Claude Code CLI, Antigravity (AGY) Autonomous CLI, and DeepSeek CLI
set -e

WORKSPACE_DIR="${STRATA_WORKSPACE_DIR:-$(pwd)}"
SESSION_NAME="${STRATA_SESSION_NAME:-dl-ai-code}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")}"
AGY_BIN="${AGY_BIN:-$(command -v agy 2>/dev/null || echo "$HOME/.local/bin/agy")}"
DEEPSEEK_BIN="${DEEPSEEK_BIN:-$(command -v deepseek 2>/dev/null || echo "$HOME/.local/bin/deepseek")}"
STRATA_API_KEY="${STRATA_API_KEY:-REDACTED}"
STRATA_MODEL="${STRATA_MODEL:-haiku}"

mkdir -p "$WORKSPACE_DIR"
cd "$WORKSPACE_DIR"

export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

# 1. Claude Code runner
CLAUDE_RUNNER="/tmp/dl-ai-claude-runner.sh"
cat << EOF > "$CLAUDE_RUNNER"
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
    echo -e "\033[38;5;238m╭─────────────────────────────────────────────────────────────────────────────╮\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[1;38;5;208m✦ D.L. AI\033[0m  \033[38;5;244m·\033[0m  \033[38;5;250mClaude Code CLI on Local Strata Engine\033[0m                    \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m├─────────────────────────────────────────────────────────────────────────────┤\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mModel\033[0m     : \033[38;5;255m$STRATA_MODEL\033[0m \033[38;5;244m(Local Qwen3.8-Flash-Next Coder)\033[0m                 \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mEngine\033[0m    : \033[38;5;250mhttp://127.0.0.1:8080\033[0m  \033[38;5;78m[ROCm GPU Active]\033[0m                     \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mWorkspace\033[0m : \033[38;5;250m$WORKSPACE_DIR\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mStatus\033[0m    : \033[38;5;78m[Connected]\033[0m  \033[38;5;215m[Fit Max Tokens Active]\033[0m                           \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m╰─────────────────────────────────────────────────────────────────────────────╯\033[0m\n"

    if [ -x "$CLAUDE_BIN" ]; then
        "$CLAUDE_BIN" --model "$STRATA_MODEL" || true
    elif command -v claude >/dev/null 2>&1; then
        claude --model "$STRATA_MODEL" || true
    else
        echo -e "\033[1;31mError: claude binary not found ($CLAUDE_BIN)\033[0m"
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
chmod +x "$CLAUDE_RUNNER"

# 2. D.L. CLI Autonomous Agent runner (Local Strata Qwen Engine)
AGY_RUNNER="/tmp/dl-ai-agy-runner.sh"
DL_CLI_BIN="/home/damirl/Desktop/Strata/tools/dl_cli.py"
cat << EOF > "$AGY_RUNNER"
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
        echo -e "\033[1;31mError: D.L. CLI binary not found ($DL_CLI_BIN)\033[0m"
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
chmod +x "$AGY_RUNNER"

# 3. DeepSeek CLI runner
DEEPSEEK_RUNNER="/tmp/dl-ai-deepseek-runner.sh"
cat << EOF > "$DEEPSEEK_RUNNER"
#!/usr/bin/env bash
export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export DEEPSEEK_BASE_URL="http://127.0.0.1:8080/v1"
export DEEPSEEK_API_KEY="$STRATA_API_KEY"
cd "$WORKSPACE_DIR"

while true; do
    echo -e "\033[38;5;238m╭─────────────────────────────────────────────────────────────────────────────╮\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[1;38;5;208m✦ D.L. AI\033[0m  \033[38;5;244m·\033[0m  \033[38;5;250mDeepSeek CLI on Local Strata Engine\033[0m                       \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m├─────────────────────────────────────────────────────────────────────────────┤\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mEngine\033[0m    : \033[38;5;255mStrata Qwen3.8 Coder via /v1/chat\033[0m                           \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mEndpoint\033[0m  : \033[38;5;250mhttp://127.0.0.1:8080/v1\033[0m  \033[38;5;78m[ROCm GPU Active]\033[0m                  \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mWorkspace\033[0m : \033[38;5;250m$WORKSPACE_DIR\033[0m"
    echo -e "\033[38;5;238m│\033[0m  \033[38;5;244mStatus\033[0m    : \033[38;5;78m[Connected]\033[0m  \033[38;5;215m[Native Chat Mode]\033[0m                                \033[38;5;238m│\033[0m"
    echo -e "\033[38;5;238m╰─────────────────────────────────────────────────────────────────────────────╯\033[0m\n"

    if [ -x "$DEEPSEEK_BIN" ]; then
        "$DEEPSEEK_BIN" -s --think || true
    elif command -v deepseek >/dev/null 2>&1; then
        deepseek -s --think || true
    else
        echo -e "\033[1;31mError: deepseek binary not found ($DEEPSEEK_BIN)\033[0m"
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
chmod +x "$DEEPSEEK_RUNNER"

# Check if tmux session already exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME" -n "claude" -c "$WORKSPACE_DIR" "$CLAUDE_RUNNER"
    tmux new-window -d -t "$SESSION_NAME" -n "agy" -c "$WORKSPACE_DIR" "$AGY_RUNNER"
    tmux new-window -d -t "$SESSION_NAME" -n "deepseek" -c "$WORKSPACE_DIR" "$DEEPSEEK_RUNNER"
    tmux set-option -t "$SESSION_NAME" mouse on 2>/dev/null || true
    tmux set-option -t "$SESSION_NAME" status off 2>/dev/null || true
else
    # Ensure all 3 windows exist
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^claude$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "claude" -c "$WORKSPACE_DIR" "$CLAUDE_RUNNER"
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^agy$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "agy" -c "$WORKSPACE_DIR" "$AGY_RUNNER"
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^deepseek$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "deepseek" -c "$WORKSPACE_DIR" "$DEEPSEEK_RUNNER"
fi

# Attach client to tmux session
exec tmux attach-session -t "$SESSION_NAME"
