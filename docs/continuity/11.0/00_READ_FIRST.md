# 捷境 11.0 云端工作检查点

本文件提供可恢复的视频工作入口。唯一项目进度索引仍为 `docs/JIEJING_CURRENT_EXECUTION_STATE.md` 的“当前接续摘要”；历史文件不是新的执行授权。

## 先确认版本和资料

- 当前视频工作分支：`video/jiejing-11-continuity-20261006`。以远端该分支的实际提交和保存回执为准；不得仅凭此分支名假定工作已推送。
- 固定迁移基线：`migration/jiejing-10-cloud-20261006` / `0b4e29970c3446f2785084a7439970396cba39ef`。它用于追溯原10.0，不是强制回退点。后续版本必须保留既有成果，不无条件 reset/clean/checkout。
- 私人资料入口：`/workspace/jiejing-continuity/10.0/START_HERE.md`，继续读 OWNER_DECISION、IMPORT_RECEIPT、PRIVATE_HISTORY_ACCESS，以及原六份10.0交接。缺文件先查映射或报告精确缺项，不重建仓库、不以摘要替代原文件。
- 启动校验：`python3 docs/continuity/11.0/verify_checkpoint.py`。它校验资料验证入口、完整已导入资料、固定视频源文件和既有样片保存回执。缺失、哈希变化或验证失败均非零退出；有新工作时先保留，再更新检查点，不能用回退源码消除报错。
- 远端保存核对：`python3 docs/continuity/11.0/verify_checkpoint.py --remote`。只有工作树无未提交更改且远端工作分支与当前 HEAD 相同，才能把当前版本称为已在该分支保存。

## 本地与云端的关系

云端为主要开发/视频工作地，本地10.0原件和本地部署能力保留。额外COS归档已取消，既有生产资源保持原状。当前任务无法观察本地电脑上的后续改动，因此“对齐”指已交付清单及截止点，不是两个设备实时同步。原始日志、保护材料、部分旧图片等只保留本地，索引不代表原文件已上云。

新任务不会自动拥有全部聊天记忆。读最新决定、当前索引及保存回执，再按需检索真实会话和 Windows→云端路径映射。重要新决定写入 OWNER_DECISION/当前索引；每次阶段成果保存到明确分支或云端成果位置，读回核对 SHA 后再报告已保存。不要等待下一次聊天来补记录。

## 视频接续点

继续既有 `marketing/douyin-studio`，不重建SaaS或另做AI短剧。当前已有A资料编辑室、B经营路线图、C先别猜三方向，以及六帧分镜、A方向12秒无声样片；方向、完整成片和发布均未批准。

可编辑源：`marketing/douyin-studio/src/Douyin11VisualStudy.tsx`；注册项 `Douyin11StyleA`、`Douyin11ConceptBoard`、`Douyin11Storyboard`。说明见 `marketing/douyin-studio/docs/11.0-visual-study-v1.md`。已有输出在 `/workspace/jiejing-deliverables/11.0/20261006-visual-v1`，逐文件校验见原 SAVE_RECEIPT，原ZIP不重复打包。

当前先面向已有eBay店铺的中国卖家；跨境电商AI CEO是定位，eBay是第一支持平台。旧37.5秒网页裁切片已否决；保留硅胶/PVC事实冲突，不虚构认证、客户、订单、销量或收益。历史商品原图不是新宣传批准。下一步从现有方向和样片评审续接，确认方向后再做完整视频，发布另行确认。

Python 3.12、Node20和Remotion4.0.518为现有工具链，不自动升级/安装新服务。实际渲染用 `/usr/bin/chromium`；工作台断线后需要重新启动进程，不能把旧PID当作当前进程。保持本地mock及真实平台写入关闭。

## 各项验收分开

资料完整、视频可渲染、Git远端保存、环境快照发布、新任务恢复、生产部署是不同验收。原265/274与三个云端失败保留，不能由视频验证关闭；它们及生产部署通道不是视频制作的前置条件。此检查点不授权main合并、生产SSH/部署、OAuth、真实平台/支付/广告或共享拼嘚变更。

启动说明保存在私人环境配置草稿；草稿保存不等于发布。仓库外资料/输出要依赖已发布的相应快照或另有可验证的私人保存回执，不能只凭当前目录存在承诺未来任务一定取得。新任务必须实际执行上述校验，失败就明确报告。
