---
name: ai-news-workflow
description: AI新闻TOP10每日推送（RSS+深度润色）。四板块结构：AI新闻Top10 + 机器人融资 + 厂商动态 + 国内机器人估值排行。
---

# AI新闻TOP10工作流（RSS+深度润色版 v6）

## 执行方式

1. **RSS抓取** → 4个RSS源当日新闻
2. **JSON输出** → 三类新闻分开
3. **深度润色** → 星巴克按Bloomberg风格整合四板块
4. **返回正文** → 由当前 Hermes 会话或 cron 统一投递，不直接调用飞书发送工具

## 可选升级：Horizon 新闻雷达

当用户要求“详细分析并安装部署”AI 热点抓取/新闻雷达/中英双语日报/多源信息过滤工具时，可以用 Horizon 作为本工作流的增强或替代方案。它比当前 RSS-only 流程多了 Hacker News、Reddit、Telegram、GitHub/OSSInsight、可选 Twitter/OpenBB、AI 打分过滤、去重、背景补充、评论摘要、GitHub Pages、Webhook 和 MCP。部署和配置要点见 `references/horizon-deployment.md`。

首次部署建议：先本地 `uv sync` + 关闭 webhook/Twitter/OpenBB + 启用 HN/RSS/Reddit/OSSInsight + 验证 `data/config.json` 可加载，再接飞书或 Hermes cronjob 自动推送。

生产拆分为“慢预热 + 快推送”时，优先查看 `references/horizon-cron-detached-precompute.md`：它记录了 Pigger 当前 Horizon AI 新闻双 cron、后台预热 wrapper、日志/锁目录和验证清单。

当用户要求“每日整理若干公司的正面和负面新闻，并用 Horizon 增强”时，参考 `references/horizon-company-news-cron.md`：用快速 pre-run 脚本读取 Horizon 摘要 + Google News RSS 候选，最终报告按公司拆分正面/负面并过滤噪音。

当日报漏掉国产大模型发布/接入/开源/融资/上市动态（如 MiniMax M3、智谱 GLM、DeepSeek、Kimi、Qwen、豆包）时，先按 `references/horizon-china-model-source-coverage.md` 排查“源层未抓到”还是“生成层未选入”。常见修复是增加中文模型专项 Google News 源，而不是只扩大英文 global AI 查询。

日报投递后的单条追问（例如“详细解读第3条”）参考 `references/followup-deep-dive.md`：先定位原日报条目和上游来源，核验原文/图表，再按“是什么→为什么重要→行业/投资/监管/中国玩家影响→局限→一句话判断”展开。

## 日报条目追问 / 深度解读

当 Pigger 在日报后追问“第 N 条”“详细解读某条新闻”时：

1. 先定位最近一次已投递日报中的对应条目；上下文不足时，用 `session_search` 搜索最近 AI 新闻 cron 输出或标题关键词，不要凭记忆猜“第 N 条”。
2. 找到该条目的原始来源链接和上游摘要；至少核验一个原文或权威来源，必要时读取图表/图片中的任务清单或指标。
3. 输出不是复述日报，而是解释它的行业含义：它是什么、为什么重要、对商业化/投资/监管/中国玩家的影响、风险与局限。
4. 保持 Pigger 偏好：中文、emoji、bullet list、不要表格；不要在正文中附加 `done`、发送状态或任务状态词。

## 飞书投递稳定性规则（2026-05-21，2026-06-26补充）

Pigger 已明确否决“只推 Top10 短版”，AI 新闻日报默认必须恢复完整四板块：

- 【全球 AI 新闻 Top10】
- 【机器人板块融资情况】
- 【厂商动态】
- 【国内机器人公司估值参考排行】

如果飞书 Interactive/CardKit 长消息再次出现“这条不全”，优先解决卡片更新和渲染方式，不要擅自删板块、不要把默认日报改成短版，也不要由模型主动拆成多条消息。

2026-06-26 修复经验：Feishu 长消息/回复预览会异常截断，且 cron 注入上下文里的本地路径可能被模型误带出。生产 cron `ae8b36822205` 已采用两层防护，并按 Pigger 最新要求改成长版：

- 生成层：不再使用任何单条短上限；默认输出完整四板块长版，不为了压缩成单条删信息。模型只返回一个完整最终正文，由 Feishu/Hermes 在同一张卡片中完成渲染；不得主动拆成多条消息。仍禁止输出 `/Users/`、`localhost`、`127.0.0.1`、`file://`、cron 输出路径、脚本路径和调试日志。
- 数据层：`~/.hermes/scripts/horizon_ai_news_context.py` 在 stdout 注入前递归清洗本地路径/本地 URL，并移除 `summary_path`、`stdout_tail`、`stderr_tail` 等调试字段。
- 新鲜度层（2026-07-24、2026-08-09 补充）：`horizon_ai_news_context.py` 会读取最近 7 期 `ae8b36822205` 已投递正文，生成 `previous_report_dedupe.recent_report_titles`，并把明显重复事件从 `horizon.summary_markdown` 和 `rss.json` 中剔除到 `excluded_previous_report_duplicates`。历史事件必须覆盖 Top10、融资、厂商动态和估值板块的编号/项目符号粗体标题；跨中英文用“主体/产品 + 事件类型 + 版本号”识别同一事件。日报正文必须逐条对照近 7 期；换标题、换来源、评论或小版本更新不算新事件，只有明确新增事实才可续写。同时在上下文注入前彻底过滤 `llama.cpp` 和 AI 安全/安全治理/提示注入/红队/对齐风险相关候选，摘要、正文、来源列表均不得出现；过滤后不足 10 条就少写，宁缺毋滥，禁止用旧闻或低价值条目凑数。
- 验证命令：`python3 ~/.hermes/scripts/horizon_ai_news_context_fast.py` 后检查 stdout 中不含本地地址，JSON 可解析，`rss_ok=True`，且 `horizon.summary_markdown` 不包含上一期已排除标题。

## 手动重跑今日日报（2026-05-25 补充）

当 Pigger 说“重新跑一次今天的每日AI新闻”或类似请求时，优先按生产拆分链路重跑并验证；
快速补充兜底请先看 `references/horizon-rerun-fallback.md`。

1. `cronjob(action="list")`：确认 ID、状态与最近运行是否正常：
   - `ae8b36822205`（日报推送）
   - `7621f267d61c`（Horizon 预热）
2. 先起预热：`cronjob(action="run", job_id="7621f267d61c")`。
3. 检查 `~/.hermes/logs/horizon-precompute/` 最新日志（允许先无输出，日志可能先是 0 字节）：
   - 确认出现 `✅ Horizon AI news precompute complete`
   - 期望看到 `rss_ok=True`
   - `horizon_ok=True` 为理想；若 `horizon_ok=False timeout=True`，通常代表 Horizon 阶段超时，非致命。
4. 设定容错分支（关键）：
   - 若 step3 在窗口内无信号，或 `horizon_ok=False timeout=True` 且 `rss_ok=True`，执行
     `python3 ~/.hermes/scripts/horizon_ai_news_context_fast.py` 做立即回填。
5. 仅当 step3 成功且 Horizon 选择链路正常时，执行推送：`cronjob(action="run", job_id="ae8b36822205")`。
6. 交付“今天新闻”时，优先用 JSON 输出按本地时区过滤（>= 当日 00:00）并去重（同事件多源只保留1条）。
7. 核实推送结果：
   - push job `last_status=ok`
   - `last_delivery_error=null`
8. 给 Pigger 回报时只报关键时间点与是否投递成功，不附加 `done` 或其他任务状态词。

### 快速兜底（Horizon 未就绪 / 卡住时）

当只要求“今天新闻”且需要立刻可见结果，且出现以下任一情况时：

- `summary_is_stale` 为 `true`（Horizon 快照非当天）
- 预热过程持续无输出或长期阻塞

可执行 RSS-only 快速命令（避免旧数据被误当今日）：

```bash
python3 /Users/xiemengqin/.hermes/scripts/horizon_ai_news_context_fast.py
```

并在输出中按本地时间窗过滤“今天”条目。遇到同一事件多源重复（如 Qwen-Robot 系列）时，日报需去重保留 1 条主文。

## 四板块格式

### 板块1：【全球AI新闻 Top 10】
综合AI圈当日最重要的10条新闻
```
💰/🔥/📈/🦾/🤖/📱 + 加粗标题
— 1-2句话描述
*来源：来源名，日期*
```

### 板块2：【机器人板块融资情况】
专门汇总当日机器人/具身智能领域的融资新闻
```
💰/🦾 + 公司名 + 融资轮次
— 简要描述
*来源：来源名，日期*
```

### 板块3：【厂商动态】
重点跟踪四家公司的当日动态
```
🔴 Anthropic / 🟠 OpenAI / 🔵 MiniMax / 🟣 GLM
当日新闻或"今日暂无新动态。（蒸馏门/IPO后续等备注）"
```

### 板块4：【国内机器人公司估值参考排行】
定期更新的估值参考排行（来源：公开融资+招股书+媒体报道）
```
T0 已上市/IPO中：
🦾 公司名 — 估值/市值（数据来源）

T1 独角兽级（10亿+）：
🤖 公司名 — 估值（融资轮次）

T2 成长期：
🦿 公司名 — 估值（融资轮次）

T3 今日新动态：
- 公司名：（今日融资/估值变动）
```

**估值排行口径（2026-07-03 修正）：**
- 不再使用固定“已知估值参考”数字作为事实来源；国内机器人估值变化快，必须以当日/近30日公开来源校准。
- 优先源：`robot_valuation_sources`（Google News China Robot Valuation / China Humanoid Funding / China Robot IPO Market Cap）、`rss.ROBOT_NEWS`、Horizon 原始条目。
- 输出估值时必须带来源；多源冲突时写“约/区间/媒体报道”，不要写成精确事实。
- 已上市公司（如优必选）优先写二级市场市值/上市状态；IPO 中公司写 IPO 进度和媒体报道估值；没有公开来源支撑的公司不要硬列入排行。

## RSS源（4个）

- 36氪：`https://www.36kr.com/feed`
- TechCrunch AI：`https://techcrunch.com/category/artificial-intelligence/feed/`
- TechCrunch Robotics：`https://techcrunch.com/category/robotics/feed/`
- Robot Report：`https://www.therobotreport.com/feed/`

## 定时任务

每天 08:10（cron id: 800aec2a-e9b2-4eb2-a13d-70b1603d9fbd）

## 机器人关键词

机器人/具身/人形/机械臂/无人机/自动驾驶/robot/humanoid/宇树/智元/Figure/MagicLab/逐际/AMR/AGV/灵巧手/四足/协作机器人/bipedal/autonomous/drone/embodied/白犀牛/无界/傅利叶/开普勒/帕西尼/星动纪元/有鹿/千寻
