# Luckin CLI Session Notes — Default Store + Coupon Order

## What was learned

- The local `luckin` CLI can query stores/products, preview orders, create orders, and fetch order detail.
- The CLI help does **not** expose an official default-store setter.
- A safe default-store pattern is to write `~/.luckin/default_order_store.json` instead of adding unknown fields to `~/.luckin/config.json`.
- `order preview` can return a `couponCodeList`; pass that code to `order create --coupon` when the user requested coupon use.
- `order create` returns a WeChat payment link and QR URL; the order remains `待付款` until user pays.

## Default store example (historical / reference)

```json
{
  "deptId": 601936,
  "deptName": "创智云城二期C4栋店",
  "alias": ["创智云城C4店", "创智云城C4栋店", "天空之城附近C4店"],
  "address": "南山区西丽社区兴科一路创智云城二期项目4栋裙楼商业二层15号",
  "longitude": 113.940853,
  "latitude": 22.577015,
  "workTimeStart": "07:30",
  "workTimeEnd": "20:30",
  "number": "No.17768",
  "purpose": "default_store_for_luckin_cli"
}
```

> In current sessions, user preference may override this; verify the latest preferred store before use (check `store-default-update-playbook.md`).

## Example product/order flow

Product search:

```bash
luckin product 601936 葡萄冰茶
```

Returned:

- `productId`: `5542`
- `productName`: `葡萄冰茶`
- `skuCode`: `SP3962-00023`
- attributes: `超大杯/冰/不另外加糖/茉莉花香/常规葡萄果肉`
- initial price: `18.0`
- estimate price: `15.3`

Preview:

```bash
luckin order preview 601936 -p 5542:SP3962-00023:1
```

Useful preview fields:

- `couponCodeList`: e.g. `SY119525307185937416`
- `privilegeMoney`: `2.7`
- `discountPrice`: `15.3`

Create with coupon:

```bash
luckin order create 601936 --lat 22.577015 --lng 113.940853 \
  -p 5542:SP3962-00023:1 \
  --coupon SY119525307185937416
```

Verify:

```bash
luckin order detail <orderId>
```

## Response pattern

- Say order created only after `order create` succeeds.
- Say “待付款” if detail shows `orderStatusName: 待付款`.
- In Feishu, send the QR as a Feishu native image message and report `message_id`; do not rely on `MEDIA:/tmp/...` or a local file path.
- Include order id, amount due, product/spec, store, and payment status.
- Warn that Luckin unpaid orders auto-cancel quickly; if the user reports a failed QR/link, check `order detail` before retrying.
- If Feishu opens WeChat but does not enter payment page, do not keep regenerating the same `weixin://wxpay/...` QR. Explain the limitation and either resend the official payment QR or use the stable fallback: Luckin app/mini-program → orders → pending payment.
