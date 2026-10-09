# 抖音参考实读、技能审查与捷境应用

日期：2026-10-09，北京时间；负责端本地10.0。用户要求实读四个分享链接，并进一步在抖音搜索 Codex 运营、视频复盘方法，由助手主动判断使用。此为研究、轻量技能安装及制作流程接入，不是新视频、公开投稿或 SaaS 修复回执。

## 一、四个分享链接实际讲了什么

四条均通过本机 Chrome 既有登录打开，按真实作者/标题/作品 ID 核对。视频使用页面正文/章节、实际关键帧和现有本地 tiny 模型辅助转录；图文读取完整可见说明。辅助转录有同音词和英文名错误，名称以实际画面/原作者文档纠正，不称真人听审。原片、关键帧和粗转录仅留 D 盘研究目录，不入Git、不当宣传素材。

| 原作者与真实作品 | 核实内容 | 对捷境的取舍 |
|---|---|---|
| [浩辰 Alex(AI版)：做自媒体必装的3个skills](https://www.douyin.com/video/7647846861123375834)，原短链 sJMbFCG_fvA | web-access 对标研究；humanizer 中文文案整理；baoyu-skills 配图与平台适配。web-access 名称由作者评论纠正平台章节误写 | 研究→自己的脚本→视觉包装；不照抄他人文案或自动批量发布。视频未唯一展示前两项repo，本次中文实现是另经审核选定的候选，不能冒称唯一指定仓库 |
| [数字生命泰妞tk：AI做带货视频Github综合Skill](https://www.douyin.com/note/7679987307696360730)，原短链 yIsghlO-sgE | 列出Clipcat、ComfyUI、MoneyPrinterTurbo、Fooocus、FaceFusion、Open-Sora、SadTalker、MoneyPrinter、AnimateDiff、LTX-Video | 清单混合Skill、软件和模型，不全是可直接加载技能；星数/排名是帖文声称，未作当前事实。当前不装大模型、换脸或批量模板产线；Clipcat需单独审查帐号/credits |
| [疯狂小马哥：AI做视频，先选对工具](https://www.douyin.com/video/7690494229131182474)，原短链 eZQFaPvWIOY | HyperFrames/Remotion负责合成；Video Cut处理口播；Video Use剪现有素材；Generative Media补素材；Seedance2写提示词。67/93/115/137秒可见四个真实GitHub仓库 | 最有价值的是按任务选工具，不是全装全跑。已有两个合成引擎无需重装；新增轻量中文分镜方法；付费ASR/生成不默认启动 |
| [陈皓AI实验室：装完codex首先要装这几个skills](https://www.douyin.com/video/7658279489474747898)，原短链 B1TbXx2FSKk | 同样六类工具，最后将选题、分镜、提示词、剪辑、字幕、包装接成流程 | 借鉴有输入输出的流程，不照搬其蓝黑卡片界面，更不把装技能视为审美或爆款保证 |

## 二、追加抖音搜索：实际深入读了两条，不把列表当学完

本机Chrome搜索词：`Codex 抖音运营`、`短视频 开头 完播率 复盘`。仅作小量公开参考，不抓全站或购买数据。列表中的点赞/收藏不等于播放量，更不能据此证明方法有效。

### 珍妮丁丁说：账号策略要随新证据更新

[用codex跑通自媒体运营全流程](https://www.douyin.com/video/7637082949514546466)，页面发布时间2026-05-07 20:00，约6分25秒。

实际内容：读取自己的后台数据，维护受众、账号定位、内容策略与选题资料；下次制作先读取这些资料，生成标题/封面/描述；复盘后修订规则。约4:47后的问答明确拍摄及剪辑仍有人参与，末段也明确工具不能保证每条爆款。不能将该案例宣传成全自动运营已经被证明安全有效。

**采用：** 不另建第二套状态库，继续使用本项目 `PRODUCT_MARKETING_CONTEXT.md`、`DOUYIN_DAILY_REVIEW.md` 和当前执行索引；每次开工读最新日期，给新片记录“哪条证据→哪一个制作修改→怎么验收”。

**不照搬：** 不批量读客户/粉丝个人明细，不因为该视频演示自动化就扩大账号操作；不凭模糊名称安装它的私人自建skill。手动发布/拍摄范围不能被解释成自动发片授权。

### 文刀刘某：先核对作品状态，再看观看和来源

[视频发出去怎么分析数据才能把账号做起来](https://www.douyin.com/video/7623421085962717306)，页面发布时间2026-03-31 22:07，约1分31秒。已核对章节、实际页面画面和全片辅助转录。

**采用：** 将作品状态、2秒跳出、5秒观看、平均观看、来源和目标受众分开观察；把留存问题定位到具体镜头；有足够匿名汇总证据才判断吸引的人是否合适。

**明确不采用：** 片中的固定达标阈值、某粉丝播放占比就“不正常”、有提示就删片/换号，以及“会看数据就能做起来”之类保证。没有对应官方依据和捷境可比样本，不能成为我们的判断规则。这里没有新增删除、换号、投流或发布操作。

## 三、已安装与核验

使用现有skill-installer，固定完整commit下载最小需要目录；主agent已完整读取三份SKILL，保留MIT许可。无第三方脚本执行、后台服务、模型下载、新凭据或付费调用。下面“安装”是本机文件完整性，不代表生成质量、流量或云端安装成功。

| 本机技能 | 固定原作者版本 | 范围与状态 |
|---|---|---|
| humanizer-zh | [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh/tree/f4518a8eab97b8bfebc66a89d34320a89bef6930)，`f4518a8eab97b8bfebc66a89d34320a89bef6930` | 中文表达编辑，不改变事实/否定/不确定性；不是TTS或AI检测器。9文件匹配 |
| baoyu-cover-image | [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills/tree/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-cover-image)，`1567581c26ec29f4216c6e6835415bf30343b0e3` | 封面五维构图，优先现有原生生图，不装发布/生图后端。35上游目录文件+根LICENSE，共36匹配 |
| seedance-prompt-zh | [dexhunter/seedance2-skill](https://github.com/dexhunter/seedance2-skill/tree/516284d5bab58361bfdfed3cc96cee3e837d4c44/zh)，`516284d5bab58361bfdfed3cc96cee3e837d4c44` | 主体/动作/景别/镜头/时间/声音的中文提示词；纯Markdown，无生成程序和额度。SKILL+根LICENSE共2匹配 |

实际位置为 `C:/Users/57249/.codex/skills/<上述名称>/`。47/47文件与固定上游Git blob及SHA256匹配，无额外文件或重解析点，清单 `GROWTH_SKILLS_LINKED_20261009.safe.json`。本轮通过直接读取进行编辑方法应用；没有做自动触发集成测试或生图/视频生成验收，不重启正在工作中的客户端来加载技能。后续新任务读取实际可用技能目录；云端须另行核验安装，不因receive文档即称工具已安装。

已存在的social、analytics、content-strategy、Product Design、Refero资料、HyperFrames、Remotion继续按任务用；不顺手升级现有视频工程依赖。

## 四、审查后暂不启用的模块

| 工具 | 本次实查发现 | 当前决定 |
|---|---|---|
| [web-access候选](https://github.com/eze-is/web-access) | Chrome/Edge远程调试/CDP代理、Node要求，可能涉及历史/书签 | 当前本机Chrome接口已工作；不开放调试端口或扩权限，不另装重复接管层 |
| [Clipcat](https://github.com/Clipcat-ai/clipcat-skill) | API key/帐号；读数据也可能耗credits；生成/发布有额外流程，TikTokShop不等于抖音 | 不注册/充值/运行安装脚本；仅借鉴逐镜拆解问题的方法 |
| [Video Cut](https://github.com/Agentchengfeng/chengfeng-videocut-skills/tree/a33b43e08c34fa8beeb5e78498e852f4e80975a5) | Plugin与Runtime分开；新工作台Skill要求Runtime≥0.5.9，当前公开Runtime0.4.11；剪口播需要获准云ASR | 不把安装文本当完整剪辑能力；借鉴删词/重复/口误复核账，不安装 |
| [Video Use](https://github.com/browser-use/video-use/tree/43cfc566833548093455c9d4a46bd69913b7e552) | ElevenLabs Scribe密钥、音轨上传、credits；缓存只按文件存在，输出可能覆盖 | 不新增ASR连接；用既有工具作本地分析，素材哈希与新输出目录自行核验 |
| [Generative Media](https://github.com/SamurAIGPT/Generative-Media-Skills/tree/66b55e2a27ee554667ec255782922bae72882cc8) | MuAPI；同版SECURITY文案与旧脚本直接curl/上传、写或source .env不一致 | 未完成所有实现安全审计，当前不接入；不执行脚本、不读凭据 |
| baoyu-image-gen、post-to-*、danger-* | 额外API/账号/发布模块；imagegen某子入口会调用danger-full-access参数 | 不整包安装。只装封面指南，保留现有安全生图及发布确认路径 |

免费/开源许可不包含模型额度、音乐、人像、商标或他人声音权利。Seedance提示词中的平台上限是对应作者快照，真正生成前须核对使用入口的最新官方约束；不默认复刻参考作者声音/整段创意。

## 五、本轮已经应用的方法，以及下一条验收

已把自主选择规则写入 `AGENTS.md` 和 `CREATIVE_SKILL_ROUTING.md`，修正旧工具文档强制沿用v10配色/版式的过时条款。本轮没有生成新媒体，V15仍被否决、ready=false。

一个文案编辑练习（不是已发布原文或完成脚本）：

- 待改示例：本产品为您提供全流程智能化内容处理，助力跨境电商高效运营。
- 更具体的候选：资料里的尺寸对不上，先别往商品标题里写。先找依据，再做草稿。
- 必须配套可见来源与操作证据；若软件不会自动发现差异，写成经营者手动核对，不能动画成自动判错功能。删除空话不能删除重要限制，也不能靠新文案证明声音变自然。

用于新片分镜的草案约束（没有渲染/配音）：

1. 开场商品或资料细节已经发生可理解的动作，一个具体问题；不先放品牌片头或栏目编号。
2. 中段追踪同一个商品/资料到草稿的变化，镜头有特写、中景、局部证据切换；不是给同一PNG做缩放。每个镜头标明主体、动作、景别、旁白、证据、出入状态，动作和镜头方向不互相冲突。
3. 完成结果回到开场的问题，官网融入结果镜头，只给一个下一步；网址不是可用性证明。OPS当前事故未恢复，不出现“立即付费/全面可用”承诺。
4. 先做6–8帧主画面及10–15秒正常语速带声样段，确认方向后扩整片；不再拿旧音轨限定新脚本，也不拿ffprobe通过当审美通过。当前声音来源只证明旧片音色获接受，不保证新完整旁白可直接生成。

现有V13数据来自22:00回执，不是本轮重新测量；小样本/分母未知，不能判定限流或是哪一项视觉导致低播放。创意重构会改变多项变量，诚实记为重构而非单变量A/B。之后再保持主体/声音/片长/CTA一致，单独对比开场候选，先离线理解测试，不重复发同片制造实验。

研究证据：`D:/Codex-Verification/jiejing-douyin-linked-skills-20261009/`；含原片分析副本、抽帧、ASR、`UPSTREAM_VIDEO_SKILLS_AUDIT_20261009.md`、`INSTALL_VERIFICATION.safe.json` 和WORK_SYNC回执。这些媒体/转录不入Git。本轮只保存本说明、流程规则及安全锁定；OPS事故/待授权恢复、原作品、原素材、发布排期和其他项目保持原状。
