# Luckin attribute switching via raw MCP

Use this when the `luckin product/menu` wrapper only shows the currently selected/default SKU but the user requests a different selectable attribute such as lower sugar or adding/removing 轻咖.

## Why

`luckin product <deptId> <keyword>` may return a SKU with only the selected attribute values, while `queryProductDetailInfo` exposes all selectable sub-attributes and `switchProduct` returns the new SKU.

Example from 葡萄鲜切柠檬茶（超大杯） at deptId `601936`:

- Product default SKU: `SP4005-00002`
- Full detail showed sugar options: 标准甜 / 少甜 / 少少甜 / 微甜
- Full detail showed coffee liquid options: 不含轻咖 / 含轻咖
- Switching sugar to 微甜 returned SKU `SP4005-00004`
- Then switching coffee liquid to 含轻咖 returned SKU `SP4005-00008`
- Preview confirmed: `超大杯/冰/微甜/青露/含轻咖`

## Raw MCP calls

Endpoint discovered from the CLI binary/configured bridge:

- `POST https://gwmcp.lkcoffee.com/order/user/mcp`
- Header: `Authorization: Bearer $LUCKIN_MCP_ORDER_TOKEN`
- Header: `Content-Type: application/json`
- Header: `Accept: application/json, text/event-stream`

Never print the token. Load it from `~/.luckin/.env`.

### 1. Query full product detail

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "queryProductDetailInfo",
    "arguments": {"deptId": 601936, "productId": 5585}
  }
}
```

Read `data.productAttrs[]` for `attributeId`, selectable `productSubAttrs[].attributeId`, `attributeName`, and `selected`.

### 2. Switch one attribute at a time

For `switchProduct`, the attribute operation that worked was `operation: 3`. Other attempted values (`0`, `1`, `2`, `4`, `-1`) returned `非法参数` in this session.

Switch sugar to 微甜:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "switchProduct",
    "arguments": {
      "deptId": 601936,
      "productId": 5585,
      "skuCode": "SP4005-00002",
      "amount": 1,
      "attrOperationParam": {
        "attributeId": 18,
        "subAttr": {"attributeId": 254, "operation": 3}
      }
    }
  }
}
```

Then use the returned `data.skuCode` for the next switch. Example: switch coffee liquid to 含轻咖:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "switchProduct",
    "arguments": {
      "deptId": 601936,
      "productId": 5585,
      "skuCode": "SP4005-00004",
      "amount": 1,
      "attrOperationParam": {
        "attributeId": 105,
        "subAttr": {"attributeId": 644, "operation": 3}
      }
    }
  }
}
```

### 3. Preview final SKU

Use normal preview with the final SKU, or call raw MCP `previewOrder`:

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "previewOrder",
    "arguments": {
      "deptId": 601936,
      "productList": [{"productId": 5585, "skuCode": "SP4005-00008", "amount": 1}]
    }
  }
}
```

## Pitfalls

- Do not assume the first product/menu result lists all choices. Query detail before saying an option is unavailable.
- Apply switches sequentially. Each switch can change the SKU; pass the latest SKU into the next switch.
- Always preview the final SKU before order creation and quote the final `additionDesc` back to the user.
