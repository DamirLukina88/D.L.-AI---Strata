#!/usr/bin/env bash
# run-code-session.sh - Persistent Multi-Scaffold CLI session for D.L. AI Web Terminal
# Supports Claude Code CLI, Antigravity (AGY) Autonomous CLI, DeepSeek CLI, and OpenAI Codex CLI
set -e

WORKSPACE_DIR="${STRATA_WORKSPACE_DIR:-$(pwd)}"
SESSION_NAME="${STRATA_SESSION_NAME:-dl-ai-code}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")}"
AGY_BIN="${AGY_BIN:-$(command -v agy 2>/dev/null || echo "$HOME/.local/bin/agy")}"
DEEPSEEK_BIN="${DEEPSEEK_BIN:-$(command -v deepseek 2>/dev/null || echo "$HOME/.local/bin/deepseek")}"
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || echo "$HOME/.local/bin/codex")}"
STRATA_API_KEY="${STRATA_API_KEY:-}"
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
    echo -e "\033[1;36m=====================================================\033[0m"
    echo -e "\033[1;32m  D.L. AI — Claude Code CLI on Local Strata Engine  \033[0m"
    echo -e "\033[0;37m  Workspace: $WORKSPACE_DIR\033[0m"
    echo -e "\033[0;37m  Model:     $STRATA_MODEL (Local)\033[0m"
    echo -e "\033[1;36m=====================================================\033[0m\n"

    if [ -x "$CLAUDE_BIN" ]; then
        "$CLAUDE_BIN" --model "$STRATA_MODEL" || true
    elif command -v claude >/dev/null 2>&1; then
        claude --model "$STRATA_MODEL" || true
    else
        echo -e "\033[1;31mError: claude binary not found ($CLAUDE_BIN)\033[0m"
    fi

    echo -e "\n\033[1;33mClaude Code session ended.\033[0m"
    echo -e "Press \033[1m[Enter]\033[0m to restart, or type \033[1mbash\033[0m for terminal:"
    read -r user_choice
    if [ "\$user_choice" = "bash" ] || [ "\$user_choice" = "sh" ]; then
        echo -e "\033[1;34mStarting interactive workspace shell (type 'exit' to return)...\033[0m"
        bash -i || true
    fi
    clear
done
EOF
chmod +x "$CLAUDE_RUNNER"

# 2. Antigravity CLI runner
AGY_RUNNER="/tmp/dl-ai-agy-runner.sh"
cat << EOF > "$AGY_RUNNER"
#!/usr/bin/env bash
export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
cd "$WORKSPACE_DIR"

while true; do
    echo -e "\033[1;36m=====================================================\033[0m"
    echo -e "\033[1;35m  D.L. AI — Google Antigravity (AGY) Autonomous CLI  \033[0m"
    echo -e "\033[0;37m  Workspace: $WORKSPACE_DIR\033[0m"
    echo -e "\033[0;37m  Engine:    Antigravity 2.0 Multi-Agent System      \033[0m"
    echo -e "\033[1;36m=====================================================\033[0m\n"

    if [ -x "$AGY_BIN" ]; then
        "$AGY_BIN" || true
    elif command -v agy >/dev/null 2>&1; then
        agy || true
    else
        echo -e "\033[1;31mError: agy binary not found ($AGY_BIN)\033[0m"
    fi

    echo -e "\n\033[1;33mAntigravity CLI session ended.\033[0m"
    echo -e "Press \033[1m[Enter]\033[0m to restart, or type \033[1mbash\033[0m for terminal:"
    read -r user_choice
    if [ "\$user_choice" = "bash" ] || [ "\$user_choice" = "sh" ]; then
        echo -e "\033[1;34mStarting interactive workspace shell (type 'exit' to return)...\033[0m"
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
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-sk-fb960c94b0144a11954e085e98079b43}"
cd "$WORKSPACE_DIR"

while true; do
    echo -e "\033[1;36m=====================================================\033[0m"
    echo -e "\033[1;34m  D.L. AI — DeepSeek CLI Coding Engine               \033[0m"
    echo -e "\033[0;37m  Workspace: $WORKSPACE_DIR\033[0m"
    echo -e "\033[0;37m  Engine:    DeepSeek V4 Coder / Reasoning (/think)  \033[0m"
    echo -e "\033[1;36m=====================================================\033[0m\n"

    if [ -x "$DEEPSEEK_BIN" ]; then
        "$DEEPSEEK_BIN" || true
    elif command -v deepseek >/dev/null 2>&1; then
        deepseek || true
    else
        echo -e "\033[1;31mError: deepseek binary not found ($DEEPSEEK_BIN)\033[0m"
    fi

    echo -e "\n\033[1;33mDeepSeek CLI session ended.\033[0m"
    echo -e "Press \033[1m[Enter]\033[0m to restart, or type \033[1mbash\033[0m for terminal:"
    read -r user_choice
    if [ "\$user_choice" = "bash" ] || [ "\$user_choice" = "sh" ]; then
        echo -e "\033[1;34mStarting interactive workspace shell (type 'exit' to return)...\033[0m"
        bash -i || true
    fi
    clear
done
EOF
chmod +x "$DEEPSEEK_RUNNER"

# 4. OpenAI Codex CLI runner
CODEX_RUNNER="/tmp/dl-ai-codex-runner.sh"
cat << EOF > "$CODEX_RUNNER"
#!/usr/bin/env bash
export TERM="xterm-256color"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export OPENAI_BASE_URL="http://127.0.0.1:8080/v1"
export OPENAI_API_KEY="$STRATA_API_KEY"
cd "$WORKSPACE_DIR"

while true; do
    echo -e "\033[1;36m=====================================================\033[0m"
    echo -e "\033[1;33m  D.L. AI — OpenAI Codex CLI Coding Engine           \033[0m"
    echo -e "\033[0;37m  Workspace: $WORKSPACE_DIR\033[0m"
    echo -e "\033[0;37m  Engine:    Codex CLI on Strata Responses / OpenAI  \033[0m"
    echo -e "\033[1;36m=====================================================\033[0m\n"

    if [ -x "$CODEX_BIN" ]; then
        "$CODEX_BIN" || true
    elif command -v codex >/dev/null 2>&1; then
        codex || true
    else
        echo -e "\033[1;31mError: codex binary not found ($CODEX_BIN)\033[0m"
    fi

    echo -e "\n\033[1;33mCodex CLI session ended.\033[0m"
    echo -e "Press \033[1m[Enter]\033[0m to restart, or type \033[1mbash\033[0m for terminal:"
    read -r user_choice
    if [ "\$user_choice" = "bash" ] || [ "\$user_choice" = "sh" ]; then
        echo -e "\033[1;34mStarting interactive workspace shell (type 'exit' to return)...\033[0m"
        bash -i || true
    fi
    clear
done
EOF
chmod +x "$CODEX_RUNNER"

# Check if tmux session already exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME" -n "claude" -c "$WORKSPACE_DIR" "$CLAUDE_RUNNER"
    tmux new-window -d -t "$SESSION_NAME" -n "agy" -c "$WORKSPACE_DIR" "$AGY_RUNNER"
    tmux new-window -d -t "$SESSION_NAME" -n "deepseek" -c "$WORKSPACE_DIR" "$DEEPSEEK_RUNNER"
    tmux new-window -d -t "$SESSION_NAME" -n "codex" -c "$WORKSPACE_DIR" "$CODEX_RUNNER"
    tmux set-option -t "$SESSION_NAME" mouse on 2>/dev/null || true
    tmux set-option -t "$SESSION_NAME" status off 2>/dev/null || true
else
    # Ensure all 4 windows exist
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^claude$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "claude" -c "$WORKSPACE_DIR" "$CLAUDE_RUNNER"
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^agy$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "agy" -c "$WORKSPACE_DIR" "$AGY_RUNNER"
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^deepseek$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "deepseek" -c "$WORKSPACE_DIR" "$DEEPSEEK_RUNNER"
    tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' | grep -q "^codex$" || \
        tmux new-window -d -t "$SESSION_NAME" -n "codex" -c "$WORKSPACE_DIR" "$CODEX_RUNNER"
fi

# Attach client to tmux session
exec tmux attach-session -t "$SESSION_NAME"
