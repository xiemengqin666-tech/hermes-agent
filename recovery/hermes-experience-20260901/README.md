# Hermes experience recovery snapshot

This secret-free snapshot preserves the verified Hermes messaging experience
used on this machine on 2026-09-01 while keeping the runtime overlay small and
compatible with the official updater.

## Contents

- `patches/0001-runtime-experience.patch`: 15-file runtime overlay for Feishu,
  Weixin, `/update`, usage accounting, cron delivery, and regression tests.
- `plugins/openclaw-lark-stream/`: pinned Feishu stream wrapper and source.
- `skills/luckin-cli-ordering/`: deterministic Luckin ordering workflow.
- `skills/ionbridge-mcp/`: secret-free AI 小电拼 Mirror control skill.
- `config/suppressed-skills.txt`: skills intentionally removed and prevented
  from being re-seeded by Hermes updates.
- `config/ionbridge.example.yaml`: secret-free MCP configuration shape; the
  live device URL remains only in local Hermes configuration.
- `config/*.example.yaml`: secret-free configuration references.
- `restore.sh` and `verify.sh`: idempotent restore and verification scripts.

## Pinned baseline

- Hermes: `v0.21.0` / commit
  `f98f5e74e00e54c36088fa2e78171e2a408ba7c9`
- Runtime patch SHA-256:
  `2485f0f147c7d1e54b1c896127dcbff187cf636777a2cafb0cad9a6f537dbc1b`
- Companion CLIs: Codex `0.151.0`, Lark `1.0.92`, Claude Code `2.1.252`,
  agent-browser `0.35.2`, Agent WeChat `0.12.0`, OpenSpec `1.11.0`,
  openspec-playwright `0.3.82`, and OpenCLI `1.8.7`.
- Feishu stream source: `ColinLu50/openclaw-lark-stream` commit
  `8d89a01b0057411c1d005f71dbcd70ef2b5c3687`
- Luckin skill: `2.0.0`

## Restore

Run from this directory:

```bash
./restore.sh
./verify.sh
```

The runtime overlay is applied only after `git apply --check` succeeds. It is
not copied into `~/.hermes/update-patches`: official `hermes update` and the
Feishu `/update` command preserve it through Hermes' native autostash flow.
Credentials, sessions, orders, chat IDs, and logs are never overwritten.

## Preserved behavior

- Feishu uses one rolling CardKit progress card, keeps the typing reaction
  until terminal completion, then replaces it with done.
- Tool/progress activity stays in the rolling card; the final card retains only
  the answer and usage footer. Multi-account replies use the receiving bot.
- Weixin acknowledges immediately, consolidates non-streaming output into one
  reply, clears typing on completion, and keeps Luckin QR/status delivery.
- `/update` uses official autostash and also checks companion CLIs without
  updating the live Feishu stream plugin or downloading Chromium.
- All agents use `gpt-5.6-sol`, high reasoning, normal service tier, and Edge
  browser execution. Fast mode remains disabled.
- Ponytail and Superpowers-derived skills are removed. Hermes' native
  `.curator_suppressed` mechanism prevents them from returning after updates.
- AI 小电拼 Mirror is available as `ionbridge` in the default agent and all
  four Hermes profiles. Its device-specific URL is read from local config.

## Security

The snapshot excludes app secrets, OAuth tokens, Weixin credentials, session
history, payment data, chat IDs, device-specific MCP URLs, and logs.
