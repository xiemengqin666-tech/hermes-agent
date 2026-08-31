# Luckin 默认门店更新实操札记（会话级）

## 触发场景

- 用户明确说“默认门店改成/更新为 X”
- 用户明确说“记住默认门店/送达门店为 X”

## 稳定流程（本会话验证）

1. 解析目标门店名
2. 用官方店铺查询确认 deptId 与营业状态（避免沿用旧默认）

示例：

```bash
mcp_luckin_queryShopList 22.593041 114.131038 布吉万象汇
```

返回结果应确认：
- `deptId`: `383791`
- `deptName`: `布吉万象汇店`
- `address`: `龙岗区深圳布吉万象汇负一层B131号`

3. 将 `~/.luckin/default_order_store.json` 覆盖为目标门店对象（含别名/时间/坐标）

```json
{
  "deptId": 383791,
  "deptName": "布吉万象汇店",
  "alias": ["布吉万象汇", "布吉万象汇店"],
  "address": "龙岗区深圳布吉万象汇负一层B131号",
  "longitude": 114.131038,
  "latitude": 22.593041,
  "workTimeStart": "10:00",
  "workTimeEnd": "22:30",
  "number": "(No.12137)",
  "source": "Hermes Weixin Luckin fast path",
  "purpose": "default_order_store_for_luckin_cli"
}
```

4. 立即复核

- `read_file ~/.luckin/default_order_store.json`
- 再次 `mcp_luckin_queryShopList`/`luckin queryShopList`（同座标+名称）
- 仅在两者一致时确认“更新成功”

## 常见坑点

- 旧会话常常只在 `.luckin/default_order_store.json` 改一半或没校验，导致下单又回到旧店。
- 别只改 `memory/USER.md`；用户常要求“下单先用这个默认店”，实际执行入口是 CLI 配置文件。
- 用户未指明门店时，才使用默认门店；若明确点名店名，应优先直查点名门店。
