# Feishu payment QR pitfalls for Luckin MCP

Session learning from ordering 葡萄冰茶超大杯 via `luckin` CLI in Feishu.

## What worked

- Default store file pattern worked: `~/.luckin/default_order_store.json` with `deptId`, store coordinates, aliases.
- Product lookup worked:
  - `luckin product 601936 葡萄冰茶`
  - productId `5542`, skuCode `SP3962-00023`
  - spec: 超大杯 / 冰 / 不另外加糖 / 茉莉花香 / 常规葡萄果肉
- Preview returned coupon code and discount:
  - `luckin order preview 601936 -p 5542:SP3962-00023:1`
  - `couponCodeList` contained `SY119525307185937416`
  - final price 15.3 after 2.7 discount
- Order creation worked with coupon:
  - `luckin order create 601936 --lat 22.577015 --lng 113.940853 -p 5542:SP3962-00023:1 --coupon <coupon>`

## Feishu delivery lesson

Do not send payment QR as a local path or plain `MEDIA:/tmp/...` when the user is in Feishu. Use native Feishu image upload/send and report `message_id`.

Preferred QR preparation:

- Download `payOrderQrCodeUrl`.
- Upscale QR to 1024px+ with white border.
- Send via `feishu-file-send` native image script/OpenAPI.

## Payment-link failure mode

Luckin create output returns:

- `payOrderUrl`: `weixin://wxpay/bizpayurl?pr=...`
- `payOrderQrCodeUrl`: `https://open.lkcoffee.com/transfer/qrcode?token=...`

Observed behavior in Feishu:

- Clicking/scanning may jump to WeChat but not enter the payment page.
- Directly encoding `weixin://wxpay/bizpayurl?...` as a QR did not solve it.
- The Luckin `/transfer?token=...` page is a Luckin MCP/open-platform page, not necessarily a mini-program order page.
- User wanted: Feishu scan → WeChat → Luckin mini-program order page → user taps pay. Current MCP response did not expose a real mini-program URL Link/Scheme for that.

Conclusion: do not claim this elegant mini-program flow is available unless the MCP response adds a field like `orderMiniProgramUrl`, `payMiniProgramUrl`, `urlLink`, or equivalent official WeChat mini-program URL.

## Order expiry

Unpaid orders auto-cancel quickly. Before sending/re-sending payment QR, always run:

```bash
luckin order detail <orderId>
```

If status is `已取消`, create a new order and send a fresh QR.

## User-experience rule for Pigger

Pigger dislikes clunky “save QR to album then scan from WeChat” workarounds. Use the best native Feishu image flow first; if the remaining blocker is WeChat/Luckin link semantics, explain that clearly and avoid repeated experiments with the same deep link.
