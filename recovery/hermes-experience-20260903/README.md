# Hermes experience recovery snapshot

This secret-free snapshot preserves the verified Hermes messaging and cron
experience used on this machine and revalidated on 2026-09-05. Runtime patches are tied to a
tested Git baseline instead of relying on a cross-version autostash.

## Contents

- `patches/0001-runtime-experience-f98f5e7.patch`: current-runtime overlay for
  Feishu, Weixin, `/update`, usage accounting, cron compatibility, and tests.
- `patches/0002-runtime-experience-f58fcc8.patch`: current reduced overlay reconciled
  and tested against the latest upstream commit available during this audit,
  including the unified Feishu stream, Weixin delivery, `/update`, Codex-style
  one-shot workspace inheritance, verification stop behavior, and a targeted
  pending-restart cleanup that cannot kill a freshly relaunched gateway.
- `plugins/openclaw-lark-stream/`: pinned Feishu stream wrapper and source.
- `plugins/weixin-experience/`: Weixin single-message and durable Luckin flow.
- `skills/luckin-cli-ordering/`: deterministic Luckin ordering workflow.
- `scripts/normalize_workspace_rules.py`: removes legacy browser and manual
  skill-ledger rules from connector workflows.
- `scripts/normalize_profile_settings.py`: keeps every profile on the verified
  model, reasoning, session-reset, approval, and Edge-only settings.
- `scripts/verify_browser_routing.py`: loads the real browser selectors in each
  profile and checks the subprocess environment, not just the saved Edge path.
- `scripts/normalize_cron_jobs.py`: verifies or restores cron delivery,
  tool-budget, and single-card guardrails without storing chat IDs.
- `skills/ai-news-workflow/`: corrected single-card AI-news workflow.
- `skills/ionbridge-mcp/`: secret-free AI 小电拼 Mirror control skill.
- `config/suppressed-skills.txt`: skills intentionally removed and prevented
  from being re-seeded by Hermes updates.
- `config/ionbridge.example.yaml`: secret-free MCP configuration shape; the
  live device URL remains only in local Hermes configuration.
- `config/*.example.yaml`: secret-free configuration references.
- `restore.sh` and `verify.sh`: idempotent restore and verification scripts.

## Tested baselines

- Legacy rollback baseline: `v0.21.0` / commit
  `f98f5e74e00e54c36088fa2e78171e2a408ba7c9`; patch SHA-256
  `76d9ad46d4bb9d1fd54d04d67e2006e8cd3171b883fe2ffc654cc0d7d0cd08a8`.
- Current and latest reconciled upstream: commit
  `f58fcc8118d9db092ad60d363d4a28520e08ac5a`; patch SHA-256
  `99eda51b668bdfaf42f617c5809dbfa023efe613ffae590ba763b8fcabbefa6e`.
- Companion CLIs: Codex `0.153.4`, Lark `1.0.93`, Claude Code `2.1.261`,
  agent-browser `0.36.0`, Agent WeChat `0.12.0`, OpenSpec `1.12.0`,
  openspec-playwright `0.3.86`, and OpenCLI `1.8.7`.
- Feishu stream source: `ColinLu50/openclaw-lark-stream` commit
  `8d89a01b0057411c1d005f71dbcd70ef2b5c3687`
- Weixin experience plugin: `1.1.1`
- Luckin skill: `2.1.2`

## Restore

Run from this directory:

```bash
./restore.sh
./verify.sh
```

The scripts auto-select a patch only when `git apply --check` proves an exact
match. They never force a patch and do not copy overlays into
`~/.hermes/update-patches`. Credentials, sessions, orders, chat IDs, and logs
are never overwritten.

Do not run `/update` from the old `f98f5e7` working tree and assume autostash
will preserve the experience: the upstream Feishu adapter changed enough for
stash restoration to conflict. Upgrade through a controlled baseline switch,
then apply the matching `f58fcc8` overlay and run `verify.sh` before restarting
the gateway.

## Preserved behavior

- Feishu uses one rolling CardKit progress card. Tool/status activity appears
  before streamed answer text, retains only the latest six progress lines, and
  is removed at finalization so the final card contains only the answer and
  usage footer. The typing reaction remains until terminal completion and is
  then replaced with done.
- A delivered provider/tool error remains a failed turn: typing is removed but
  done is never attached merely because the error notice was delivered.
- Tool/progress activity stays in the rolling card; the final card retains only
  the answer and usage footer. Multi-account replies use the receiving bot.
- Weixin acknowledges immediately, consolidates non-streaming output into one
  reply, clears typing on completion, and keeps Luckin QR/status delivery.
- Luckin requests remain model-guided, but one command performs live product
  validation plus exact preview in about 10 seconds and persists confirmation
  across `/new`. Confirmation is atomically claimed to prevent duplicate paid
  orders, then one reply carries the payment QR. An expired preview is refreshed
  and requires a new confirmation instead of silently losing context or using an
  old price. Transient EOF/timeouts are retried only for read-only product and
  preview calls; order creation is never blindly retried.
- Legacy workspace rules no longer force browser/image searches or a manual
  skill-usage terminal call during Luckin ordering.
- `/update` uses official autostash and also checks companion CLIs without
  updating the live Feishu stream plugin or downloading Chromium. The
  companion updater is bound before the source checkout so the same `/update`
  invocation can finish after Hermes replaces its working tree.
- Interrupted-update catch-up restarts only terminate PIDs that existed before
  the supervisor restart and are still alive afterward. Fresh launchd/systemd
  gateway PIDs are preserved, preventing supervisor backoff and delayed recovery.
- All agents use `gpt-6-astra`, reasoning `medium`, normal service tier, and Edge
  browser execution. Fast mode remains disabled, and automatic idle/daily
  session resets remain disabled for the default and collaboration profiles.
- On 2026-09-05 the user selected Hermes' officially recommended balanced
  conversation setting. Main and delegation defaults are `medium`; Fast
  remains off. This uses the official Codex transport without an extra
  reasoning patch. No model or history reset is needed.
- The subsequent GPT-6 migration covers all five profiles, pinned channel/API
  routes, delegation, compression, planning/title auxiliaries, and pinned cron
  models. The account's live Codex catalog reports 272,000 context tokens;
  do not substitute the public API's larger context window.
- Coding uses native `coding_context: auto`, completion/parallel-call guidance,
  and `verify_on_stop: auto` with at most two nudges after unverified code edits
  on interactive coding surfaces. Messaging avoids synthetic re-verification
  turns; its coding workflow still requires actual checks before completion.
  Scoped SOUL rules cover coding requests in messaging channels too. Ordinary
  chat and Luckin ordering keep their own workflows. Read the target repo,
  use explicit workspace paths, apply small patches, preserve user edits, and
  run focused checks before reporting completion. Do not force delegation for
  simple fixes or load debugging skills on every reply. One-shot coding runs
  now bind both system-prompt context and file/terminal tools to the launch
  directory, while preserving configured gateway workspaces. Conventional
  Python unittest suites are detected as canonical verification; `python` and
  `python3` invocations are equivalent, and a fresh passing suite ends the
  verification loop unless later edits or failures justify another run.
- A clean GPT-6 blind coding rerun on 2026-09-05 completed on its first attempt:
  public tests `12/12`, hidden tests `11/11`, exactly two allowed files
  changed, sentinel SHA-256 unchanged, and no post-pass ad-hoc or duplicate
  verification. The final messaging/update/coding regression set passed
  `522/522` on upstream `f58fcc81`.
- Edge-only requires explicit `browser.backend: 'off'`, local provider, no
  CDP override, and `use_real_profile: false`, in addition to the Edge executable
  environment variables. Here `off` selects the built-in browser tools; it does
  not disable browsing. An unset backend now selects Browser Use and its local
  Chrome harness, which ignores the Edge executable pin and prompts for remote
  debugging approval (verified in the 2026-09-03 13:12 browser_exec failure).
  Never approve that prompt. Legacy imported browser-search skills must not
  instruct agents to attach to Chrome or download bundled Chromium.
- Ponytail and Superpowers-derived skills are removed. Hermes' native
  `.curator_suppressed` mechanism prevents them from returning after updates.
- AI 小电拼 Mirror is available as `ionbridge` in the default agent and all
  four Hermes profiles. Its device-specific URL is read from local config.
- The content-assistant channel uses a 60% compression threshold; mechanical-arm
  and drone channels use 50%. These overrides are reapplied to both fresh and
  reused agents so very large turns compact before the final provider request.
- Imported OpenClaw `lark-doc` is retained under the distinct
  `openclaw-lark-doc` name, while the current official `lark-doc` stays active.
- Cron failures route to the developer assistant while successful output keeps
  each job's own destination. The video-trend job has a bounded tool/skill
  budget, and update checks use bounded logs and diffs.

## Security

The snapshot excludes app secrets, OAuth tokens, Weixin credentials, session
history, payment data, chat IDs, device-specific MCP URLs, and logs.
