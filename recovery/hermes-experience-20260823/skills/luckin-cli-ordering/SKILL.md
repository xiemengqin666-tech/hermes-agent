---
name: luckin-cli-ordering
description: "Use the local Luckin CLI for store lookup, product selection, preview, confirmed order creation, payment QR delivery, and status watching."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [luckin, coffee, ordering, cli, payment, weixin]
    category: productivity
---

# Luckin CLI Ordering

Use this skill for 瑞幸门店、菜单、商品、优惠券、订单预览、下单、取消和订单状态查询。

## Fixed conversation contract

- Keep the model in the loop for product/store/spec interpretation. Do not bypass semantic parsing with a gateway rule.
- Weixin sends its platform acknowledgement separately. Do not repeat “已收到，思考中” in the model answer.
- Before money is spent, send one ordinary preview message containing store, product, quantity, every selected attribute, original price, discount and payable amount. End with `内容正确请回复：确认下单`.
- A subsequent `确认` or `确认下单` authorizes the unchanged preview. Do not ask again and do not reload unrelated skills.
- After confirmation, run the fast create script once, then send one consolidated payment reply with the payable amount and payment QR. State in that same message that payment must complete within 5 minutes and that Luckin will automatically cancel an unpaid order without a separate cancellation notification. Do not repeat the store or order ID after creation, and do not expose tool/model progress as separate messages.
- Never create an order for a lookup-only or preview-only request.
- During a live order, never edit this skill, its scripts, Hermes source, or user memory. Complete the deterministic recovery first; engineering changes belong in a separate maintenance turn.

Target latency: a clear request should reach preview in about one minute; confirmation should reach the payment QR in about 20 seconds under normal network conditions.

## 1. Resolve store

- If the user explicitly names a store/location, it overrides every saved default. Prefer direct name lookup, then verify open status.
- Otherwise read `~/.luckin/default_order_store.json` with normal JSON I/O and use its `deptId`.
- Do not browse for a clearly named/default store.

Commands:

```bash
luckin queryShopList <lat> <lng> <shopName>
luckin store <lat> <lng>
```

## 2. Resolve exact product and SKU

Use one product/menu lookup first:

```bash
luckin product <deptId> <keyword>
luckin menu <deptId> <keyword>
```

- Treat size, temperature, sweetness, flavor and toppings as hard constraints.
- Query full detail or switch attributes only when the first result does not prove the requested combination.
- `葡萄冰茶超大杯不加糖` maps to `葡萄冰茶 / 超大杯 / 冰 / 不另外加糖`; do not substitute 葡萄鲜切柠檬茶. Load `references/grape-ice-tea-no-added-sugar.md` for that exact variant.
- Historical SKU identifiers are disambiguation hints only. A fresh preview is always authoritative for availability, attributes, coupon and price.

## 3. Preview once

```bash
luckin order preview <deptId> -p <productId>:<skuCode>:<amount>
```

Verify `productInfoList[].additionDesc`, store, coupon, original price, discount and payable amount. If exact and unambiguous, immediately send the single preview message and wait for confirmation.

## 4. Confirmed Weixin order

Reuse the exact tuple and coupon from the preview. If store/spec/quantity/price changed or the preview is older than 15 minutes, preview again; otherwise do not repeat store/menu/product lookups.

Run exactly one post-confirmation tool command:

```bash
python3 ~/.hermes/skills/productivity/luckin-cli-ordering/scripts/create_luckin_order_fast.py \
  --dept <deptId> --lat <store_lat> --lng <store_lng> \
  -p <productId:skuCode:amount> --coupon <couponCode> \
  --target 'weixin:<origin_chat_id>' --no-send
```

The script creates the order, verifies order detail and QR readability, and starts the watcher. Trust a `success=true, verified=true` result; do not add separate detail, image, process or usage-log tool turns. Then send one final response with `MEDIA:<payQrPath>`.

If the script returns an error after creating an order, inspect that order before retrying so duplicate paid orders cannot be created.

## 5. Delivery and watcher

- Payment and pickup QR must return to the originating channel only.
- A valid local QR does not prove Weixin received it. The Weixin adapter retries transient CDN connection/timeout failures three times at the encrypted-upload step; if all retries still fail, keep the existing live order and resend the same QR with `hermes send --json --to 'weixin:<origin_chat_id>' 'MEDIA:<absolute_path>'`. Require `success=true`, the exact `chat_id`, and `context_token_used=true`; do not recreate the order merely because media upload failed.
- Notify each real order transition exactly once: order accepted, production started, and pickup-ready. Never split one transition into multiple text messages.
- After payment, keep user-visible transitions minimal: `下单成功`, `制作中`, then `可以取餐了` with the pickup code and QR. Do not repeat the store name or order ID in these lifecycle messages or on the pickup QR card; retain them only in internal state and logs.
- If an order moves directly from `待付款` to `已取消`, treat it as Luckin's unpaid expiry: stop watching and do not send another standalone message. The payment QR message already disclosed the five-minute deadline. A cancellation after payment or production remains a real exception and must be reported once.
- At pickup-ready, send one concise ready message containing the numeric pickup code plus the native QR image. On Weixin, text plus one QR must use one native message payload.
- If the user says the QR is missing, the Weixin plugin resends the chat-scoped delivery manifest directly; do not enter a full diagnostic model loop.

## Cancellation

- `取消` before creation discards only the preview; no API cancellation is needed and no charge occurred.
- Cancel an actual order only when an `orderId` exists and the user explicitly authorizes cancellation.

## References

- `references/grape-ice-tea-no-added-sugar.md`: exact 葡萄冰茶 variant.
- `references/attribute-switching-via-mcp.md`: non-default attributes.
- `references/store-default-update-playbook.md`: changing the saved store.
- `references/feishu-payment-qr-pitfalls.md`: Feishu native QR delivery.
- `references/luckin-order-workflow-notes.md`: lower-level MCP and routing pitfalls.
