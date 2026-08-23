# Hermes experience recovery snapshot

This secret-free snapshot preserves the Feishu messaging behavior, Luckin
ordering workflow, and Codex capability alignment used on this machine on
2026-08-23.

## Contents

- `patches/0001-runtime-experience.patch`: Hermes runtime, Feishu, Weixin,
  `/update`, usage-accounting, and regression-test changes.
- `plugins/openclaw-lark-stream/`: the Hermes wrapper around the pinned GitHub
  plugin source.
- `skills/luckin-cli-ordering/`: the deterministic Luckin preview, payment QR,
  delivery, and order-status workflow.
- `config/feishu.example.yaml`: a redacted multi-account configuration example.
- `config/codex-capability-alignment.example.yaml`: the secret-free model,
  reasoning, planning, delegation, approval, and Edge browser alignment.
- `restore.sh`: idempotent restore script. It never restarts the gateway.
- `verify.sh`: checks files, patch compatibility, plugin revision, syntax, and
  focused regression tests.
- `checksums.sha256`: per-file integrity checks.

## Pinned baseline

- Hermes: `v0.20.5` / commit `fd760435c6688a2b6c6b7436dde30e267237baef`
- Feishu stream source: `ColinLu50/openclaw-lark-stream` commit
  `8d89a01b0057411c1d005f71dbcd70ef2b5c3687`
- Luckin skill: `2.0.0`

## Restore

Run from this directory:

```bash
./restore.sh
./verify.sh
```

Override paths when restoring into a non-default installation:

```bash
HERMES_HOME=/path/to/.hermes HERMES_REPO=/path/to/hermes-agent ./restore.sh
```

The script applies the patch only when Git proves it is compatible, pins the
Feishu stream source, restores the Hermes wrapper and Luckin skill, then runs
verification. It does not overwrite `config.yaml`, credentials, sessions, or
orders, and it does not restart the gateway. After verification succeeds,
restart manually with `hermes gateway restart` at an appropriate time.

## Preserved behavior

- Feishu uses one live CardKit message for progress, keeps the typing reaction
  until the real task lifecycle finishes, and switches to done only on final
  completion.
- Progress/tool activity is edited into the live card instead of being emitted
  as separate chat messages; the final card retains only the answer and footer.
- Multi-account Feishu routing replies through the bot account that received the
  message.
- Weixin sends one acknowledgement, consolidates non-streaming model output, and
  clears typing when the lifecycle ends.
- Luckin keeps the model in product/spec interpretation, previews once, creates
  only after confirmation, sends the payment QR in the same reply, and emits
  each paid-order transition once. Post-payment messages do not repeat the
  store or order ID.
- `/update` preserves and reapplies the canonical patch, updates companion CLIs,
  and performs readiness checks without using a stale gateway process.
- All live agents, planning calls, API defaults, and inherited cron jobs use
  `gpt-5.6-sol`. Historical usage records may still name older models, but no
  executable configuration may select `gpt-5.3-codex-spark`.
- Main agents and delegated agents use `high` reasoning, up to 200 turns, 250
  child iterations, and 10 concurrent children with command approvals off.
- Browser automation is enabled through Microsoft Edge only. The Hermes
  engine name remains `chrome` because it denotes the CDP-compatible engine;
  `AGENT_BROWSER_EXECUTABLE_PATH` pins the actual executable to Edge and
  `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` prevents a bundled Chromium download.

## Security

This archive intentionally excludes app secrets, Weixin credentials, OAuth
tokens, chat IDs, session history, order state, payment QR images, and logs.
Use `config/feishu.example.yaml` only as a shape reference and supply secrets
locally through environment variables.
