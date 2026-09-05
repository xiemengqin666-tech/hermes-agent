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
- `patches/0003-runtime-experience-d20a8e4.patch`: latest complete overlay for
  `d20a8e4`, including launchd wrapper-child ownership detection so `/update`
  protects and reconciles the real gateway process instead of treating it as a
  manual process.
- `plugins/openclaw-lark-stream/`: pinned Feishu stream wrapper and source.
- `plugins/weixin-experience/`: Weixin single-message and durable Luckin flow.
- `skills/luckin-cli-ordering/`: deterministic Luckin ordering workflow.
- `scripts/normalize_workspace_rules.py`: removes legacy browser and manual
  skill-ledger rules from connector workflows.
- `scripts/normalize_profile_settings.py`: keeps the default runtime on the
  verified model, reasoning, session-reset, approval, and Edge-only settings;
  it does not create or rewrite collaboration profiles.
- `scripts/configure_skills.py`: preserves skills bundled by the installed
  Hermes version, exposes only official `lark-*` external skills, and permits
  only Luckin and IonBridge as local custom skills. DJI remains an MCP server.
- `scripts/verify_browser_routing.py`: loads the real browser selectors for the
  default runtime and any existing official profile, then checks the subprocess
  environment rather than trusting only the saved Edge path.
- `scripts/normalize_cron_jobs.py`: verifies or restores cron delivery,
  tool-budget, single-card guardrails, runtime script paths, and removal of all
  custom-skill bindings without storing chat IDs.
- `runtime-scripts/`: the nine secret-free scripts required by the preserved
  usage, US-stock, and Horizon cron jobs.
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
- Previous reconciled upstream: commit
  `f58fcc8118d9db092ad60d363d4a28520e08ac5a`; patch SHA-256
  `99eda51b668bdfaf42f617c5809dbfa023efe613ffae590ba763b8fcabbefa6e`.
- Current and latest reconciled upstream: commit
  `d20a8e44755a8e999a2e816ef9f458c438d3e17c`; patch SHA-256
  `5bfac5184a74d53dd0fe2f9d7968d9845592d96cd9e86df48d32976d954a5581`.
- Companion CLIs: Codex `0.153.4`, Lark `1.0.93`, Claude Code `2.1.261`,
  agent-browser `0.36.0`, Agent WeChat `0.12.0`, OpenSpec `1.12.0`,
  openspec-playwright `0.3.86`, and OpenCLI `1.8.7`.
- Feishu stream source: `ColinLu50/openclaw-lark-stream` commit
  `8d89a01b0057411c1d005f71dbcd70ef2b5c3687`
- Weixin experience plugin: `1.1.1`
- Luckin skill: `2.1.2`

## Restore

The verified fresh-install command used the official installer from
`https://hermes-agent.nousresearch.com/install.sh` with
`--skip-setup --skip-browser --skip-computer-use --non-interactive`. Its
SHA-256 on 2026-09-05 was
`5854b15670b51a8daae8f59ddfa917062de9f74be261eb73b4b8d719710f8968`.
This avoids installing Hermes-managed Chromium before the recovery overlay is
applied.

Run from this directory:

```bash
./restore.sh
./verify.sh
```

The scripts auto-select a patch only when `git apply --check` proves an exact
match. They never force a patch and do not copy overlays into
`~/.hermes/update-patches`. Credentials, sessions, orders, chat IDs, and logs
are never overwritten.

The current official `d20a8e44` fresh install defines no collaboration
profiles. Restore therefore removes only the four legacy local profiles
`agencydev`, `agencyresearch`, `agencyreview`, and `agencysynth`; any differently
named profile introduced by a future official Hermes release is left untouched.

Do not run `/update` from the old `f98f5e7` working tree and assume autostash
will preserve the experience: the upstream Feishu adapter changed enough for
stash restoration to conflict. Upgrade through a controlled baseline switch,
then apply the matching `d20a8e4` overlay and run `verify.sh` before restarting
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
- On macOS, `/update` now follows a launchd wrapper to the actual gateway child,
  excludes both from the manual-process sweep, and resolves the child's generic
  `external` socket identity back to `launchd`. This prevents false partial
  receipts, stale restart markers, and accidental termination of the new gateway.
- The default runtime and saved channel/API routes use `gpt-6-astra`, reasoning
  `medium`, normal service tier, and Edge browser execution. Fast mode remains
  disabled, and automatic idle/daily session resets remain disabled. No local
  collaboration profiles are recreated.
- On 2026-09-05 the user selected Hermes' officially recommended balanced
  conversation setting. Main and delegation defaults are `medium`; Fast
  remains off. This uses the official Codex transport without an extra
  reasoning patch. No model or history reset is needed.
- The GPT-6 migration covers the default runtime, pinned channel/API routes,
  delegation, compression, planning/title auxiliaries, and pinned cron models.
  The account's live Codex catalog reports 272,000 context tokens;
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
  verification. After the fresh reinstall, the final messaging/update/coding
  regression set passed `590`, skipped two platform-specific cases, and
  deselected one known non-hermetic upstream Feishu case on `d20a8e44`.
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
- AI 小电拼 Mirror is available as the `ionbridge` custom skill and MCP server.
  DJI is retained as the `dji-mini3` MCP server, without a duplicate custom
  skill. Luckin is the only other custom skill. Device-specific URLs remain in
  local configuration.
- The content-assistant channel uses a 60% compression threshold; mechanical-arm
  and drone channels use 50%. These overrides are reapplied to both fresh and
  reused agents so very large turns compact before the final provider request.
- Twenty-eight official Lark CLI skills are loaded from their individual
  `~/.agents/skills/lark-*` directories. Other global skills, including Draw.io,
  are not exposed to Hermes. Imported OpenClaw Lark aliases are not restored.
- The AI-news and China-video cron jobs are self-contained and have no custom
  skill binding. Kuaishou references and deleted workspace-skill paths are not
  restored.
- Cron failures route to the developer assistant while successful output keeps
  each job's own destination. The video-trend job has a bounded tool/skill
  budget, and update checks use bounded logs and diffs.

## Security

The snapshot excludes app secrets, OAuth tokens, Weixin credentials, session
history, payment data, chat IDs, device-specific MCP URLs, and logs.
Horizon credentials, collected data, and its locally modified checkout are not
published here; they remain only in the local reinstall archive.
