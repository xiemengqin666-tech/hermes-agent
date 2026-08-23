# 瑞幸：葡萄鲜切柠檬茶甜度歧义速查

## 现象
- 之前 `queryMenu/searchProduct` 返回的条目只显示 `少甜`。
- 再换关键词（含“微甜”）后发现存在另一 SKU：
  - `葡萄鲜切柠檬茶（超大杯）`
  - `productId`: 5585
  - `skuCode`: `SP4005-00004`
  - `糖度`: `微甜`
- 另一个同类 SKU：
  - `skuCode`: `SP4005-00002`
  - `糖度`: `少甜`

## 处理结论
1. 同一商品名下可出现多甜度 SKU；不能用单次查询结果断言“没有微甜/不加糖”。
2. 若用户要求甜度，先并行抓取关键词变体：`葡萄鲜切柠檬茶`、`葡萄鲜切柠檬茶 微甜`、`葡萄鲜切柠檬茶 不加糖`。
3. 对每个候选 SKU 做 `preview` 并核对：`productId / skuCode / additionDesc / 价格`。
4. 将可确认结果明确展示给用户，再在用户指令“下单 X”后创建对应 SKU。

## 该会话中的可复用动作
- 使用如下确认流程可避免误选：
  - `mcp_luckin_searchProductForMcp(deptId, query)` 两类关键词检索
  - `mcp_luckin_queryMenu(deptId, query)` 对照展示项
  - `mcp_luckin_previewOrder(deptId, [productId:sku:qty])` 确认最终口味描述