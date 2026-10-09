# Refero Styles 设计参考接续（2026-10-09）

## 用户最新决定与范围

用户明确要求查看Refero Styles，并把AI可读设计资料保存本机，作为以后UI设计的参考；特别重视美感、层次、交互和动效。本轮只研究、保存与接续，不修改捷境UI/业务代码，不部署、不连接付费MCP、不买服务、不动拼嘚。当前API恢复事故仍按执行索引置顶记录等待特定授权，本任务不构成该授权或恢复证明。

本地10.0负责。开工按WORK_SYNC正常status/receive，收到 `e2a4c563596cd5bda3a9e573f697a8f6f8b451e0`，正确共用分支且干净，与远端相同。第三方资料未进入产品源码或Git。

## 实际保存范围

本地根：`D:/Codex-References/refero-styles-20261009/`。

- `README.md`：面向经营者的总入口。
- `JIEJING_UI_REFERENCE_PLAYBOOK.md`：捷境适配与后续验收方法。
- `RESOURCE_INDEX.md`：官方AI资料页可见链接去重50项，仅入口，不是50页全文。
- `ARCHIVE_MANIFEST.safe.json`：42个第三方/截图文件的路径、大小、SHA256与来源。非整个目录所有自写文件的快照。
- `refero-official-skill/`：官方MIT仓库当前完整检出，30个跟踪文件，含10份设计参考；固定提交 `a9b54a3e62a6391f5f5ab7a20e4ddb32fb79a27d`。浅克隆，不含全部历史。没有执行其中脚本/安装依赖、插件或MCP。
- `styles/`：6套网站原生Extended DESIGN.md，含各自规范和Quick Start；不是自行生成的仿制文件。
- `screenshots/`：6张对应详情截图。Chrome自动翻译过部分展示文字，下载原件保持英文。

通过本机Chrome网站原生下载按钮取得；下载原件仍在用户下载文件夹保留，未移动、删除或覆盖。Linear第一次等待下载事件超时，但实际文件已存在并完成标题/哈希核对，因此没有重复下载。其他5份逐个核对标题后复制到独立文件名。

本次原生规范链接：

- linear：https://styles.refero.design/style/90ce5883-bb24-4466-93f7-801cd617b0d1 → `styles/linear.DESIGN.md`
- cursor：https://styles.refero.design/style/4e3b4717-84c8-4599-baaf-a343c3d619b6 → `styles/cursor.DESIGN.md`
- notion：https://styles.refero.design/style/2bf4c61f-de10-4614-ba1b-20c0453bd2a9 → `styles/notion.DESIGN.md`
- ramp：https://styles.refero.design/style/b38702a0-75ab-474c-9106-00b624535825 → `styles/ramp.DESIGN.md`
- perplexity：https://styles.refero.design/style/81afaa5c-73ac-4ef4-9a99-296da325ea6c → `styles/perplexity.DESIGN.md`
- openai：https://styles.refero.design/style/dc541737-8bf2-4b31-b729-0352f696e82f → `styles/openai.DESIGN.md`

## 以后怎样参考，不偏离捷境

- Perplexity：研究中心输入、侧栏退后、阅读焦点；用于AI CEO工作区的方向比较，不把捷境改成普通聊天工具。
- Linear：研究表面层次、边线与紧凑秩序；不是已经决定使用暗色或小字号。
- Ramp：研究数字/行动的主次，OPS未知、阻断、零收入等真实状态不能被视觉美化。
- Cursor/Notion/OpenAI：作为产品主视觉、阅读层级、卡片与留白的对照；不默认照搬米白、专有字体、Logo、客户背书或品牌配色。
- Refero详情页“预览 + 规范”的并置方式可启发成果预览与依据检查的主次关系；这是待评估建议，不是现有导航改版决定。
- 实施前选1个主方向与最多2个局部参考，重大视觉修改先给2–3个可见方案，由经营者选定，再写捷境自己的DESIGN.md。保留原产品功能、确认边界、中文适配与账号/店铺隔离。
- 官方开源motion参考已保存。快速反馈、状态连续、低动态模式、可打断和明确过渡属性可作为研究起点；本轮没有逐站验证原站动效，不把静态截图或Refero描述当现场测量。

## 保存位置与云端边界

本机Product Design偏好：`C:/Users/57249/.codex/state/plugins/product-design/user-context.md`，已登记参考与使用边界。按用户明确“记到电脑”请求，新增一份本机记忆补充note；没有直接改写既有MEMORY.md。新任务读取项目索引及本文件即可找到来源。

云端接收到本文件，仅表示收到安全入口/偏好/版本说明。D盘外部仓库、DESIGN.md和截图不上传Git，不能声称云端已拥有这些原件或已安装插件；云端需按当前任务和公开来源重新取得所需参考。

## 明确保留的限制

1. **不是2,000+全库镜像**。首页宣称2,000+且持续更新；本轮未发现公开全库导出按钮，未抓内部接口、不绕过权限或付费限制。完成的是开源工具资料当前版本 + 50个入口 + 6套精选原生规范。
2. 规范由Refero提取与解释，非品牌官方指南；HTML示例可能重建，数值/用途可能有矛盾，不能盲目执行或当业务真相。
3. 开源仓库MIT许可不自动覆盖品牌字体/商标/图片/网站设计素材。参考只作私有研究，不直接发布他人品牌资产。
4. [官方MCP说明](https://doc.refero.design/mcp/getting-started)当前要求付费计划。未登录、注册、连接、购买、安装或扩大权限；本轮免费公开浏览和本机保存不产生新增采购。
5. 资料里的安装/优先级/外部操作指令不自动成为本项目规则。AGENTS、当前执行摘要与用户新决定优先。
6. 本轮没有修复或复核线上502；生产恢复问题保持原记录，不把本参考保存任务称作整个项目已完成。

## 官方资源入口（50项）

来源：https://styles.refero.design/ai-agents/design-resources 。以下是当时可见目录去重索引，不声称每一篇已深入阅读或完整离线保存。

1. [UI设计示例](https://styles.refero.design/ai-agents/ui-design-examples)
2. [面向AI的网站风格](https://styles.refero.design/ai-agents/website-design-styles)
3. [后台设计提示](https://styles.refero.design/ai-agents/dashboard-design-prompts)
4. [金融科技网站](https://styles.refero.design/design-styles/fintech-websites)
5. [AI产品网站](https://styles.refero.design/design-styles/ai-startup-websites)
6. [字体搭配](https://styles.refero.design/design-styles/website-font-pairings)
7. [落地页提示](https://styles.refero.design/ai-agents/landing-page-design-prompts)
8. [定价页提示](https://styles.refero.design/ai-agents/pricing-page-design-prompts)
9. [新手引导提示](https://styles.refero.design/ai-agents/onboarding-design-prompts)
10. [表单提示](https://styles.refero.design/ai-agents/form-design-prompts)
11. [设置页提示](https://styles.refero.design/ai-agents/settings-page-design-prompts)
12. [SaaS应用提示](https://styles.refero.design/ai-agents/saas-app-design-prompts)
13. [开发者工具提示](https://styles.refero.design/ai-agents/devtools-design-prompts)
14. [组件提示](https://styles.refero.design/ai-agents/component-design-prompts)
15. [DESIGN.md示例](https://styles.refero.design/ai-agents/design-md-examples)
16. [DESIGN.md模板](https://styles.refero.design/design-md/design-md-template)
17. [风格驱动提示](https://styles.refero.design/ai-agents/design-prompts)
18. [AI可读设计系统](https://styles.refero.design/design-md/ai-readable-design-systems)
19. [AI Agent使用DESIGN.md](https://styles.refero.design/design-md/design-md-for-ai-agents)
20. [Claude Code使用DESIGN.md](https://styles.refero.design/design-md/design-md-for-claude-code)
21. [Cursor使用DESIGN.md](https://styles.refero.design/design-md/design-md-for-cursor)
22. [DESIGN.md资源](https://styles.refero.design/design-md/design-md-resources)
23. [DESIGN.md规范](https://styles.refero.design/design-md/design-md-specification)
24. [DESIGN.md与Tokens](https://styles.refero.design/design-md/design-md-vs-design-tokens)
25. [DESIGN.md与Figma](https://styles.refero.design/design-md/design-md-vs-figma)
26. [Figma转DESIGN.md](https://styles.refero.design/design-md/figma-to-design-md)
27. [Google Stitch指南](https://styles.refero.design/design-md/google-stitch-design-md)
28. [语义设计系统](https://styles.refero.design/design-md/semantic-design-systems)
29. [什么是DESIGN.md](https://styles.refero.design/design-md/what-is-design-md)
30. [机构网站](https://styles.refero.design/design-styles/agency-websites)
31. [简洁SaaS](https://styles.refero.design/design-styles/clean-saas)
32. [暗色网站](https://styles.refero.design/design-styles/dark-mode-websites)
33. [开发者工具网站](https://styles.refero.design/design-styles/devtools-websites)
34. [电商网站](https://styles.refero.design/design-styles/ecommerce-websites)
35. [编辑式网站](https://styles.refero.design/design-styles/editorial-websites)
36. [极简网站](https://styles.refero.design/design-styles/minimal-websites)
37. [生产力应用](https://styles.refero.design/design-styles/productivity-apps)
38. [AI界面质量检查](https://styles.refero.design/ai-agents/agentic-ui-quality-checklist)
39. [品牌匹配提示](https://styles.refero.design/ai-agents/brand-matching-prompts)
40. [Claude Code提示](https://styles.refero.design/ai-agents/claude-code-design-prompts)
41. [CSS变量](https://styles.refero.design/ai-agents/css-variables-design-tokens)
42. [Cursor提示](https://styles.refero.design/ai-agents/cursor-design-prompts)
43. [设计上下文](https://styles.refero.design/ai-agents/design-context)
44. [设计系统上下文文件](https://styles.refero.design/ai-agents/design-system-context-files)
45. [Tailwind Tokens](https://styles.refero.design/ai-agents/tailwind-design-tokens)
46. [v0提示](https://styles.refero.design/ai-agents/v0-design-prompts)
47. [API文档网站](https://styles.refero.design/examples/api-documentation-websites)
48. [后台界面示例](https://styles.refero.design/examples/dashboard-ui-design)
49. [定价页示例](https://styles.refero.design/examples/pricing-page-design)
50. [产品截图主视觉](https://styles.refero.design/examples/product-screenshot-heroes)

## 开源与证据入口

- 官方开源库：https://github.com/referodesign/refero_skill
- 固定版本：https://github.com/referodesign/refero_skill/tree/a9b54a3e62a6391f5f5ab7a20e4ddb32fb79a27d
- 许可：https://github.com/referodesign/refero_skill/blob/a9b54a3e62a6391f5f5ab7a20e4ddb32fb79a27d/LICENSE
- 本地核验：根目录 `VERIFY.safe.json`；保存回执 `WORK_SYNC_SAVE.safe.json`。仅在实际核验、推送及远端读回成功后称已交出；另一端仍须receive。

