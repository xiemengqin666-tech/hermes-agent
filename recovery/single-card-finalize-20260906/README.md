# Single-card finalize recovery

## Incident and cause

A completed Feishu CardKit answer was followed by a second ordinary message.
The gateway's five-second stream flush deadline can cancel the awaiting
coroutine while the SDK request continues in its worker thread. The remote
card update may land, but the consumer never records its acknowledgement.
The unconfirmed-delivery branch previously only logged the risk and allowed
a new final send.

## Fix

Commit: `cda3c48a6005b3ff683b55775dbf0f61573015a9`.
Parent baseline: `2413295687bffe8b1a2a01470b48565eab1848bd`.

Reuse the existing in-place reconciliation helper for an unconfirmed editable
card on adapters opting into `STREAM_PROGRESS_IN_CONTENT`. Preserve its
routing/footer metadata. Set `already_sent` only after the reconciliation
actually succeeds; a missing/deleted card, split delivery or failed turn must
not silently suppress unseen output. No model, reaction timing, streaming
animation, or Weixin policy was changed.

## Verification

- New regression reproduced two failures before the fix; all six cases passed
  afterward. Tests use the real gateway reconciliation method and stream
  consumer, with the installed Feishu adapter's capability declaration.
- Four related streaming/contract test files: 101 passed.
- A broader first run: 185 passed, one existing Feishu dedup isolation failure.
  `TestDedupTTL.test_concurrent_dedup_persists_land_in_order` clears environment
  isolation and reads the real persisted dedup cache. It was not changed or
  counted as passing.
- Real Feishu API replay through the installed multi-account wrapper: created
  one labelled test card, applied the remote final update, injected lost local
  acknowledgement, reconciled the same message, and read back final text plus
  footer. Normal final send was suppressed. The test card was recalled through
  the bot's native message-delete API after the adapter's delete method returned
  false. No user message was deleted.
- User-approved gateway restart loaded the fixed commit; Feishu, Weixin and API
  reported connected, and local `/v1/health` returned OK.

This is targeted API/behavior verification, not a visual revalidation of all
client animation states, nor a new full `/update` benchmark.

## Restore

The accompanying Git patch contains the fix and regression tests, without
credentials, sessions or real chat/message identifiers. It is incremental,
not a replacement for the older complete recovery snapshots.

Review the patch and use `git apply --check` against the intended checkout
before applying. Do not force it across conflicts. Preserve local commits on
the maintained experience branch so future updates can merge them explicitly.
Run `scripts/run_tests.sh tests/gateway/test_single_card_finalize_recovery.py`
after restoration. Restart only with authorization and after active work drains.

CodeGraph was initialized locally at the user's request. Its database is
excluded through `.git/info/exclude`, not a tracked runtime-source modification.
