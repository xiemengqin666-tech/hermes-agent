# 葡萄鲜切柠檬茶（超大杯）不加糖处理记录

Session learning from a WeChat Luckin order at default store `601936`（创智云城二期C4栋店）.

## Product lookup pitfall

Searching with the fully constrained phrase `葡萄柠檬茶 不加糖 超大杯` or `葡萄鲜切柠檬茶 超大杯 不加糖` returned unrelated products such as `苦瓜轻体果蔬茶` and `葡萄冰茶`.

Better approach:

1. Search with the shorter canonical category keyword:
   - `柠檬茶`
2. Pick `葡萄鲜切柠檬茶（超大杯）`, productId `5585`, default sku `SP4005-00002`.
3. Query full product detail before deciding whether the user's requested option exists.

## Attribute facts observed

For `productId=5585` at `deptId=601936`:

- Cup: `超大杯` (`attributeId=64`, subAttr `592`)
- Temperature: `冰` (`attributeId=17`, subAttr `57`)
- Sugar options (`attributeId=18`):
  - `标准甜` (`60`)
  - `少甜` (`112`, default selected on `SP4005-00002`)
  - `少少甜` (`59`)
  - `微甜` (`254`)
- Tea flavor: `青露` (`attributeId=100`, subAttr `773`)
- Coffee liquid (`attributeId=105`):
  - `不含轻咖` (`643`, default)
  - `含轻咖` (`644`)

There was **no** `不加糖` / `不另外加糖` sugar option. Lowest selectable sugar was `微甜`.

Switching sugar to `微甜` via `switchProduct` with `operation: 3` returned sku `SP4005-00004`.

Preview confirmed:

- Product: `葡萄鲜切柠檬茶（超大杯）`
- SKU: `SP4005-00004`
- Addition: `超大杯/冰/微甜/青露/不含轻咖`
- Price observed: `¥14.5` after discount, no couponCodeList returned

## User confirmation semantics

If the agent has already previewed and clearly stated the closest available substitution (e.g. “没有不加糖，最低微甜；如果接受回确认下单”), a reply like `确认` is enough authorization to create the order with that exact previewed SKU. Do not ask again unless price/store/product changed.
