# Hermes experience recovery snapshot

This secret-free snapshot preserves the verified Hermes messaging experience
used on this machine on 2026-08-27 while keeping the runtime overlay small and
compatible with the official updater.

## Contents

- `patches/0001-runtime-experience.patch`: 15-file runtime overlay for Feishu,
  Weixin, `/update`, usage accounting, cron delivery, and regression tests.
- `plugins/openclaw-lark-stream/`: pinned Feishu stream wrapper and source.
- `skills/luckin-cli-ordering/`: deterministic Luckin ordering workflow.
- `config/suppressed-skills.txt`: skills intentionally removed and prevented
  from being re-seeded by Hermes updates.
- `config/*.example.yaml`: secret-free configuration references.
- `restore.sh` and `verify.sh`: idempotent restore and verification scripts.

## Pinned baseline

- Hermes: `v0.20.6` / commit
  `82e18567205ebd0a119b7e322e5470b9363de91b`
- Runtime patch SHA-256:
  `f95f288e876a15c533a7393b8bd09d79f1b12196c675ed7d75864b31f993dd1c`
- Companion CLIs: Codex `0.150.1`, Lark `1.0.90`, Claude Code `2.1.247`,
  agent-browser `0.35.1`, OpenSpec `1.11.0`, and OpenCLI `1.8.7`.
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

## Security

The snapshot excludes app secrets, OAuth tokens, Weixin credentials, session
history, payment data, chat IDs, and logs.
