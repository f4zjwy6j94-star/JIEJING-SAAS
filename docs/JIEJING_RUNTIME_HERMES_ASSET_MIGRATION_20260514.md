# 捷境 Runtime 迁移 Hermes 项目资产进度记录

日期：2026-05-14

## 1. 本次做了什么

本次不是把 Hermes 本体复制进捷境，而是把 Hermes 里与捷境项目有关的方向、记忆、配置边界、岗位 SOP、skills 和闭环样本，迁移成捷境 Runtime 可读取的安全知识包。

已生成：

- `output/jiejing-runtime-knowledge/jiejing-runtime-knowledge-pack.json`
- `output/jiejing-runtime-knowledge/summary.md`
- `output/jiejing-runtime-knowledge/hermes-migration-manifest.json`

## 2. 迁移范围

已迁移进 Runtime 知识层：

- 项目方向与唯一事实记录
- SaaS 当前流程同步
- eBay 运营 SOP
- 任务拆分与市场数据包规则
- 闭环测试经验
- eBay 平台知识
- SpeedPAK / 橙联物流研究
- 产品刊登与素材边界
- 客服学习边界
- 人工确认边界
- Hermes 当前核心 Jiejing skills
- Hermes 各 profile 的相关 skill 清单
- Hermes config 的安全边界说明

明确没有迁移：

- token
- cookie
- OAuth 密钥
- API key
- 原始 Hermes config 内容
- 浏览器会话
- 客户敏感数据

## 3. 当前迁移结果

本次知识包结果：

- 总知识项：57
- 读取文件：47
- 缺失文件：0
- 运行时手工沉淀规则：10
- 当前 Hermes shared note：18
- 当前 Hermes skill：13
- profile skill inventory：1
- safe config inventory：1
- 敏感字段/长值/邮箱/敏感路径处理：188 处

## 4. 百分比进度

这是按真实工程口径估算，不是宣传口径。

| 模块 | 当前进度 | 说明 |
| --- | ---: | --- |
| Hermes 项目方向迁移 | 85% | 核心方向、SaaS 流程、闭环经验、eBay 逻辑已进入 Runtime 知识包。 |
| Hermes 记忆/SOP 迁移 | 80% | 关键 shared 文档和测试经验已迁移；后续还要持续增量同步。 |
| Hermes skills 迁移为 Runtime 知识 | 70% | 13 个当前核心 skill 已迁入知识层；但还没有全部改写成捷境原生可执行工具。 |
| Hermes 配置迁移 | 45% | 已迁移安全配置边界和 profile skill inventory；原始 config 和密钥不能直接复制，后续要做 Runtime 自己的 env/vault 配置。 |
| 捷境自研 Agent 团队合同 | 76% | 7 个电商 Agent 的职责、工具权限、质量门槛和交接合同已接入 Runtime。 |
| 替代 Hermes 的真实执行能力 | 40% | 能按捷境链路模拟运行并读取迁移知识；真实大模型、真实工具、真实 eBay/1688/物流/图片视频执行还未完全接入。 |
| 商业化生产级 | 25% | 本地 Runtime 可跑，但正式多用户后端、队列、权限隔离、密钥保险柜、云端部署还需要继续做。 |

## 5. 当前结论

捷境 Runtime 现在已经开始拥有自己的项目记忆和岗位知识，不再只靠 Hermes 脑子里的内容。

但当前仍然不能说“已经成熟替代 Hermes”。正确状态是：

```text
Hermes 继续作为真实内测执行工具
Jiejing Runtime 已经接收核心项目资产
下一步把 skills 从知识迁移升级为可执行工具/Adapter
最终让 Hermes 退为可替换 worker
```

## 6. 下一步

优先级如下：

1. 把 `jiejing-llm` 配上真实大模型，让 7 个 Agent 真的调用模型生成报告。
2. 把 eBay 只读、公开搜索、1688/货源、橙联/SpeedPAK、图片视频生成做成 Runtime Tool Adapter。
3. 把 Hermes skills 逐个拆成捷境原生工具，不只停留在知识文本。
4. 做 Hermes vs Jiejing Runtime 影子对比：同一个任务两边都跑，比较报告质量。
5. 把 Runtime 部署到云端测试环境。
