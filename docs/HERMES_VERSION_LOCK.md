# Hermes 版本锁定与商用边界记录

生成日期：2026-05-14

本文档用于锁定当前捷境内测使用的 Hermes 基线版本，并规定后续云端部署、fork、升级和替换的边界。

这不是对 Hermes 的法律意见书，而是捷境项目内部的工程与合规记录。

---

## 1. 当前锁定版本

当前本地运行环境：

| 项目 | 当前值 |
| --- | --- |
| 运行用户 | `hermes` |
| 本地运行目录 | `/home/hermes/.hermes/hermes-agent` |
| 命令入口 | `/home/hermes/.local/bin/hermes` -> `/home/hermes/.hermes/hermes-agent/venv/bin/hermes` |
| Git remote | `https://github.com/NousResearch/hermes-agent.git` |
| Branch | `main` |
| Commit | `64145a1996554e4e81b694e9737421f34f44e212` |
| Last commit | `64145a199 2026-05-11 Siddharth Balyan fix(nix): replace chown -R with targeted find in container entrypoint (#23633)` |
| Python package | `hermes-agent` |
| Version | `0.13.0` |
| License | `MIT` |
| Copyright | `Copyright (c) 2025 Nous Research` |

当前结论：

- 该版本可以继续作为捷境内测和早期云端试运行底座。
- 该版本不能被宣传为捷境原创底层框架。
- 后续生产环境不得自动跟随上游 `main` 更新。
- 上云前必须 fork、镜像或打包固定版本。

---

## 2. MIT License 使用要求

当前 Hermes 本体许可证为 MIT License。

MIT License 通常允许：

- 使用。
- 复制。
- 修改。
- 合并。
- 发布。
- 分发。
- 再授权。
- 销售软件副本。

必须遵守：

- 保留原始版权声明。
- 保留 MIT License 文本。
- 不删除 Nous Research 版权信息。
- 不把 Hermes 本体宣传为捷境原创代码。

捷境内部使用口径：

- Hermes 是当前内测执行底座。
- Hermes 是捷境后端未来可选的 Agent Worker。
- 对外不宣传 Hermes。
- 客户购买的是捷境，不是 Hermes。

---

## 3. 禁止事项

在没有再次审查前，禁止：

- 生产环境直接执行 `hermes update`。
- 生产环境直接从上游 `main` 自动拉取最新代码。
- 删除 LICENSE 文件或版权声明。
- 把 Hermes 作为公开卖点写进官网、合同或销售材料。
- 让客户直接访问 Hermes。
- 让前端直接调用 Hermes。
- 让 Hermes 直接掌握全部客户 token。
- 让 Hermes 直接执行真实发布、退款、付款、广告预算、采购付款、政策修改等高风险动作。

---

## 4. 允许事项

当前阶段允许：

- 继续用 Hermes 跑真实 eBay 内测。
- 继续用飞书 CEO 调度 Hermes 岗位。
- 继续让 Hermes 输出市场报告、刊登报告、素材任务包、客服学习包、财务复核和 CEO 汇总。
- 继续把 Hermes 测试结果沉淀为捷境标准样本。
- 在内部文档中讨论 Hermes。
- 将当前版本打包到私有仓库或内部镜像中保存。

---

## 5. 后续 fork / 镜像规则

上云前必须完成：

1. 建立捷境控制的私有仓库或镜像。
2. 导入当前锁定 commit。
3. 保留原始 LICENSE、README 和版权说明。
4. 标记内部版本号，例如 `jiejing-hermes-base-20260514`.
5. 记录所有本地修改。
6. 禁止生产环境自动从 NousResearch 上游更新。
7. 设置升级评审流程。

升级评审必须检查：

- 上游许可证是否仍为 MIT。
- 新版本是否改变配置结构。
- 新版本是否改变 skill / memory / gateway / profile 行为。
- 新版本是否改变安全边界。
- 新版本是否影响飞书 CEO 和岗位调度。
- 新版本是否影响捷境任务协议和报告输出。

---

## 6. 依赖风险初查

当前快速抽查到的关键依赖许可证：

| 依赖 | 版本 | 许可证初查 |
| --- | --- | --- |
| `hermes-agent` | `0.13.0` | MIT |
| `openai` | `2.32.0` | Apache-2.0 |
| `anthropic` | `0.96.0` | MIT |
| `requests` | `2.33.1` | Apache-2.0 |
| `httpx` | `0.28.1` | BSD-3-Clause |
| `exa-py` | `2.12.0` | MIT |
| `firecrawl-py` | `4.22.2` | MIT License |
| `parallel-web` | `0.4.2` | MIT |
| `edge-tts` | `7.2.8` | LGPLv3 |
| `@askjo/camofox-browser` | `1.5.2` | MIT |
| `agent-browser` | `0.26.0` | Apache-2.0 |
| `playwright` | `1.59.1` | Apache-2.0 |
| `playwright-extra` | `4.3.6` | MIT |
| `puppeteer-extra-plugin-stealth` | `2.11.2` | MIT |

注意：

- 这只是快速抽查，不是完整 SBOM。
- 正式商用前要生成完整依赖清单。
- `LGPLv3` 依赖需要确认使用方式和分发方式。
- 浏览器自动化、抓取、stealth 类依赖还要结合目标平台服务条款审查。

---

## 7. 捷境对 Hermes 的正确定位

短期：

Hermes 是真实闭环验证工具。

中期：

Hermes 是捷境后端 `AgentExecutionAdapter` 下的一个执行器。

长期：

Hermes 是可替换 worker。捷境自己的 `Jiejing Agent Runtime` 承担电商任务协议、报告模板、确认中心和平台适配。

---

## 8. 下一步

P0：

- 新增 `JIEJING_TASK_PROTOCOL.md`。
- 把 Hermes 输出报告逐步整理成捷境标准任务样本。
- 禁止生产环境自动升级 Hermes。

P1：

- 建立内部 fork / 镜像仓库。
- 生成完整 SBOM 和依赖许可证报告。
- 建立 `HermesAdapter` 与 `MockAgentAdapter` 的接口设计。

P2：

- 开发 `Jiejing Agent Runtime MVP`。
- 对同一任务进行 Hermes 与 Jiejing Runtime 影子对比。
- 逐步替换低风险任务，例如报告生成、字段校验、确认中心草稿。
