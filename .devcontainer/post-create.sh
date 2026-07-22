#!/usr/bin/env bash
set -euxo pipefail

# Write Claude Code settings so it picks up Bedrock env vars
mkdir -p ~/.claude
cat > ~/.claude/settings.json <<EOF
{
  "env": {
    "ENABLE_TOOL_SEARCH": "${ENABLE_TOOL_SEARCH}",
    "CLAUDE_CODE_EFFORT_LEVEL": "${CLAUDE_CODE_EFFORT_LEVEL}",
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "${CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING}",
    "MAX_THINKING_TOKENS": "${MAX_THINKING_TOKENS}",
    "CLAUDE_CODE_USE_BEDROCK": "${CLAUDE_CODE_USE_BEDROCK}",
    "ANTHROPIC_MODEL": "${ANTHROPIC_MODEL}",
    "ANTHROPIC_SMALL_FAST_MODEL": "${ANTHROPIC_SMALL_FAST_MODEL}",
    "AWS_PROFILE": "${AWS_PROFILE}"
  }
}
EOF

# Install liteparse (local PDF/document parser)
uv tool install liteparse
