# 提示词维护说明

## 分工

- SOUL.md：身份、语气与诚实原则，保持短小。
- workspace/AGENTS.md：执行、证据、工程、收尾及最小平台约定。
- memories/USER.md：用户确认的长期偏好，仅本地保存，不随公共恢复覆盖。
- memories/MEMORY.md：已验证且仍有用的记忆；当前清空状态保留，不从备份回灌。
- workspace/docs/MESSAGING.md：消息与瑞幸体验的按需验收标准。
- UPDATE_GUARDRAILS.md：升级/重启的按需手册。
- workspace/docs/RULES.md：本说明；不需要每轮读取。
- agent.coding_instructions：仅指向共享执行规则，保留 Hermes 原生 coding_context、工具和验证能力，不复制另一份长提示词。

当前 Hermes 在新会话构建时加载身份和上下文规则，已有会话可能沿用缓存。修改后可在目标会话 /new，让新规则完整加载；不批量清空历史，也不为此重启 gateway。工具、session_override、系统提示缓存与实际模型请求要分别核验，不能仅凭文件内容宣称全部生效。

## 维护方法

规则冲突时核对用户最新要求和适用范围：一个阶段合并回复不等于禁止业务阶段通知；任务闭环不等于把询问当作修改授权；持续执行不等于无界测试或循环重启。新增规则应有具体失误和可测验收点，优先修改已有条款而非追加“最高优先级”口号。日志、历史事故和临时版本号不要塞入常驻提示词。

本轮保留官方框架代码与模型参数，仅整理规则和去重配置中的 coding 指引。对齐目标是查证、实施、验证、交付的工作方式；提示词不能复制 Codex 的完整工具运行环境、权限、调度及产品能力。

原则参考：[OpenAI 模型提示指导](https://developers.openai.com/api/docs/guides/latest-model)（2026-09-05 查阅），采用按任务校准自主性、委派与测试的建议；不强制固定思考步骤或公开隐藏推理。

## 规则单独恢复

在恢复存档根目录运行 scripts/normalize_workspace_rules.py，参数为目标 workspace/AGENTS.md 和 --souls-home 指定的 HERMES_HOME。它从 rules/ Markdown 模板恢复五个公开规则文件；覆盖前备份有差异的文件。--check 只比较，缺失也报错，绝不写入。

这是显式快照恢复，不是开机或 /update 自动覆写器。若现场已有合理的新要求，应先人工合并进模板再恢复，不因 --check 不匹配就删除用户定制。USER.md、MEMORY.md、config.yaml 和 session 文件不在此脚本覆盖范围内。完整 restore.sh 还会涉及代码、插件和配置，不用于单纯更新提示词。

验收至少包含：实时状态问题会查证；分析请求不改文件；小代码任务完成适量测试后停止；用户取消不会重启旧任务；微信付款阶段不被单条规则吞掉；飞书长任务不提前 DONE。单元测试与提示加载校验不等于这些场景的模型或客户端端到端通过，应分别记载。
