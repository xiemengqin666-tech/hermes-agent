# 葡萄冰茶（超大杯）不另外加糖

## Intent mapping

When the user asks for `葡萄冰茶超大杯不加糖`, treat `不加糖` as the menu attribute `不另外加糖`. Do not silently substitute `葡萄鲜切柠檬茶`; it is a different product whose minimum sweetness may be `微甜`.

## Lookup and verification nuance

A live `luckin product <deptId> 葡萄冰茶` lookup may return only the default SKU (for example `大杯/冰/微甜`) even while the exact `超大杯/冰/不另外加糖` SKU remains orderable. Do not treat the narrow product result as proof that the requested variant disappeared.

When a previously verified exact tuple exists:

1. Run the required live product lookup to confirm the product is still sold at the store.
2. Preview the previously verified exact SKU once.
3. Accept it only if the fresh preview succeeds and `productInfoList[].additionDesc` exactly matches `超大杯/冰/不另外加糖` plus the intended flavor/toppings.
4. Use only the coupon and payable amount returned by that fresh preview.

This keeps the fast path while making the money-path preview the authoritative availability and attribute check.

## Verified examples

At store `601936`（创智云城二期C4栋店）:

- 2026-07-30:
  - Product: `葡萄冰茶`
  - `productId`: `5542`
  - `skuCode`: `SP3962-00023`
  - Attributes: `超大杯/冰/不另外加糖/茉莉花香/常规葡萄果肉`
  - Original price: `¥18.00`
  - Coupon: `SY119808101187404248`
  - Preview payable: `¥15.45`
- 2026-08-03:
  - Same product/SKU/attributes
  - Coupon: `SY119831689282079775`
  - Preview payable: `¥14.25`
- 2026-08-07:
  - Same product/SKU/attributes
  - Coupon: `SY119854955522563129`
  - Preview payable: `¥13.90`
- 2026-08-13:
  - Live product lookup exposed only default `SP3962-00012` (`大杯/冰/微甜`)
  - Fresh preview of `5542:SP3962-00023:1` succeeded with exact attributes `超大杯/冰/不另外加糖/茉莉花香/常规葡萄果肉`
  - Coupon: `SY119886127589787028`
  - Preview payable: `¥12.90`
  - Order creation and immediate detail verification succeeded; status was `待付款`, amount `¥12.90`

These examples confirm that the SKU can remain unchanged while the visible default search result, coupon, and payable amount vary. Historical identifiers are disambiguation hints, never permanent checkout data; always require a fresh exact preview.

## Confirmation summary

Before creation, send a normal chat summary with product, quantity, all attributes, store, original price, discount, and payable amount, then ask the user to reply `确认下单`. A plain follow-up `确认` after that unchanged preview is sufficient authorization to create the order.