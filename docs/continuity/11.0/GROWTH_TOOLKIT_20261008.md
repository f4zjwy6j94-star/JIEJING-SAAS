# 捷境抖音增长与视频工具接入

2026-10-09补充：已本机安装同原作者 `content-strategy` 2.1.3，固定提交 `1efedbc5148b54b2f0f6c6c9fe0be62e151c7fff`。4个MD/JSON上游文件逐一Git blob匹配并保留MIT LICENSE，无可执行文件/新外连或权限，未改原social/analytics版本。来源与逐文件SHA见 `GROWTH_TOOLKIT_ADDITION_20261009.safe.json`；云端未安装。用来把一个经营问题、可理解结果和一个下一步组织为新内容，不采用固定流量阈值/必爆承诺。A/B技能仅研究未安装，当前非随机小样本不能称显著实验。Remotion商用主体规模已由经营者在10/9中午确认个人或总人数不超过3，见V13发布回执；下方未核实是10/8历史状态。

日期：2026-10-08晚，负责端本地10.0。范围是经营者授权的推广工作台：GitHub研究、两个轻量技能安装、项目适配、制作/质检与复盘入口。不是SaaS或腾讯云部署，不是无人值守生产/发布已验收。

## 1. 已实际完成的接入

使用Codex已有skill-installer从原作者仓库固定提交安装两个技能；未改已有技能、未整包启用其它工具。安装临时下载/解包位于D盘新证据目录，避免大临时文件占C盘；最终技能文本仅126,326字节，另补MIT许可证。

| 技能 | 版本与实际位置 | 本项目采用范围 |
|---|---|---|
| social | 2.3.3；`C:/Users/57249/.codex/skills/social/` | 选题支柱、开头/内容/行动提示、独立短视频脚本、内容日历和复盘 |
| analytics | 2.0.2；`C:/Users/57249/.codex/skills/analytics/` | 明确漏斗、指标口径、未知值、来源和反推下一次内容实验；不安装埋点 |

原作者：[coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)。锁定提交 `b9ba399dd88b082b926e261e8ccfb843d20aa066`；本轮公开API显示未归档，MIT。准确路径是 `skills/social` 和 `skills/analytics`，不是旧目录名social-content/analytics-tracking。

两个目录共16个上游文件，逐一以Git blob SHA核对通过；只有Markdown和JSON，未安装可执行脚本。已完整阅读两个SKILL及本轮选用的short-form-video、post-templates、event-library参考；没有声称所有未用参考都通过语义安全审计。Markdown仍含命令/外部服务示例，不自动执行。两个目录均补上原作者MIT LICENSE，保留上游原文件不改写。

两个新技能下轮可加载。当前轮已阅读并把其适用方法用于本项目文本简报和汇总数据模板。云端没有本机技能安装成功回执；共享的是来源锁定和项目方法，不冒称插件/登录态自动迁移。

## 2. 视频工具：复用现有，不改变应用运行环境

| 资源 | 本轮结果 | 使用决定 |
|---|---|---|
| [Remotion官方skills](https://github.com/remotion-dev/skills) | 本机官方技能4.0.530；现有工程及依赖4.0.518，Node v24.15.0 | 继续原工程作后续本机样片候选，不升级依赖，不重新安装浏览器 |
| [HeyGen HyperFrames](https://github.com/heygen-com/hyperframes) | 本机已有0.1.2技能，v10 HTML及DESIGN存在；云端特定运行路径本机缺失 | 学习静态主画面、编排、字幕和逐帧检查；保留现有v10工程，不能直接跑硬编码云端脚本 |
| [FFmpeg / FFprobe](https://github.com/FFmpeg/FFmpeg) | 工程自带Windows n7.1；WSL Ubuntu 6.1.1可调用 | 元数据读取、剪辑、混音和技术检查复用现有程序 |
| [Auto-Editor](https://github.com/WyattBlue/auto-editor) | 适合大量长口播粗剪；当前未需要 | 本轮不安装。CLI与付费GUI不同，当前官方不再通过pip发布 |

本机路径：

- Node：`C:/Program Files/nodejs/node.exe`。
- Remotion CLI：`marketing/douyin-studio/node_modules/.bin/remotion.cmd`。
- Windows FFmpeg/FFprobe：`marketing/douyin-studio/node_modules/@remotion/compositor-win32-x64-msvc/`。
- 缓存渲染浏览器：`marketing/douyin-studio/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe`，仅确认文件存在，未启动渲染。
- v10：`marketing/douyin-studio/hyperframes/commerce-v10/index.template.html`、`DESIGN.md`、`tools/commerce-v10/`。

许可注意：引擎开源/技能可读不等于所有规模免费商用。Remotion的[厂商许可](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md)有个人/企业规模条件，不能宣称MIT无限免费；未核验经营主体规模，不购买或升级。HyperFrames仓库Apache-2.0不涵盖外部语音/模型费用。FFmpeg构建组件有不同许可，见[官方说明](https://ffmpeg.org/legal.html)。音乐、字体、声音、照片仍逐项记录商业使用来源。本轮未分发引擎二进制或引入付费服务。

插件目录另检索到Descript、Runway等可选连接器，以及已安装Adobe；本轮没有连接新账号、建议购买、上传素材或增加权限。现有工具已覆盖当前策划与质检所需能力，不把“目录可发现”称为“已接入”。未验证这些连接器支持抖音直接发布。

## 3. 本轮真实验证及仍有限制

1. 新安装16个文件全部与固定版本匹配，约123.4KiB；两份本地LICENSE另计。
2. Windows FFprobe对桌面已交付77.682秒文件读取成功：H.264/AAC、1080×1920、30fps、双声道。
3. Windows捆绑FFmpeg的默认 `-f null` 解码检查失败：默认wrapped_avframe编码器未启用。准确退出码 `-1129203192`。这不是判定视频损坏的证据，不能把该捆绑程序当全功能FFmpeg。
4. 改用现有WSL FFmpeg，完整解码且启用 `-xerror` 退出0。WSL启动有localhost代理提示，与本地文件解码错误区分记录，不修改网络设置。
5. 读取前后现有桌面片SHA均为 `0fa4a5f264e0ffe656b6e07b66bacee0821f0972613869569ba9a93976d7b6dc`，原文件未改。此为旧片的工具检查，不是本轮新片、美术或人工听音验收。

本机WSL缺失原v10硬编码的HyperFrames CLI、Qwen语音模型、`/usr/bin/chromium`、指定NotoSerif字体路径。原 `prepare-film.py` 带有 `adelay=300` 的声道处理，不能直接重复生产并假定旁白重音不会回来。原 `verify-film.py` 会写抽帧/报告，不是只读探针。Remotion配置含 `setOverwriteOutput(true)`；后续必须新建D盘版本目录并显式拒绝已有输出目标。**本轮没有更改或执行这些历史制作脚本。**

## 4. 每次制作实际遵循的入口

1. `WORK_SYNC status/receive`，读执行摘要、`docs/continuity/11.0/PRODUCT_MARKETING_CONTEXT.md`，选定期号和一个商业问题。
2. 内容策划用social；只读本轮相关参考，不自动连接调度器/批量采集。产出开头、脚本、字幕、画面证据、结尾动作、文案和话题。
3. 选择原工程中的一个实际渲染器；检查当前版本API，不能把4.0.530技能示例无验证套到4.0.518项目。高保真分镜和有声样片尚未完成时，先做这两步。
4. 建素材账：素材标识、来源文件/URL、权利依据、使用范围、是否含私人数据、最终批准；未知权利的音乐/声音不用。台账只保存非敏感摘要，不上传原件。
5. 静态主画面 → 动作编排 → 有声样片 → 审看返工 → 完整片。每次导出到D/E/F全新版本；可编辑工程和原件保留。
6. 经过下方两层检查，再进入待发布包；确认授权/账号/声明与平台预检，单次提交并留实际状态。已提交或审核中不重复上传。
7. 用analytics口径记录24/72小时表现。收工保存明确源码与安全记录；媒体不进入GitHub，不部署共享服务器。

## 5. 高级感的可检查标准

沿用v10已部分认可的纸白、森林绿、淡青柠与中文宋体大标题；不再做通用黑金/霓虹科技模板。现有设计文件中的字体要求优先于通用技能的“禁用字体”审美建议，不能偷偷换掉品牌字体。

- **层次**：每镜一个主信息，主体、辅助解释、背景氛围有主次；不要让三层都同时抢注意力。
- **排版**：非对称留白，大字与证据细节形成对比；字幕不超过两行作为起点，按实际中文字宽和手机预览校准。
- **运动**：先放对静态位置，再动画。资料聚拢、文字生成、图文编排等动作要与旁白有因果；保留阅读停顿，不用无意义持续晃动。
- **剪辑**：镜头跟随语义和动作接点；全片控制转场类型，避免每镜一种特效。真实UI是短暂证据，不用浏览器截图撑全片。
- **声音**：旁白清晰优先，音乐在人声时回避，关键动作音效适量。重新合成时禁止照搬左右声道300ms错位；逐段正常速度听审。
- **商业表达**：展示真实准备流程和输出，不捏造用户证言、订单、收益或节省时间。品牌署名自然出现；结尾只给一个可执行下一步。

### 技术检查与审美检查分开

技术：文件/时长/帧数/编码、完整解码、音画同步、黑帧/静音候选、字幕边界和溢出、声道对齐、响度/真峰值、源文件未覆盖。响度可从约−16 LUFS、真峰值≤−1 dBTP试混后听审，这是内部起点而非抖音标准；黑场或静音是否故意必须人工判断，不能见检测命中就自动删。

审美：正常速度全片看/听，并以手机实际尺寸检查。前3秒能否认出问题；中段有没有持续的信息与动作推进；文字能否读完；声音是否单调/抢话；画面是否精致且真实。任一项明显失败先返工；ffprobe/渲染PASS不得替代这些结论。

输出状态必须区分：脚本草案、文字分镜、高保真帧、有声样片、技术通过、审美待审/通过、待发布、已提交、平台审核、公众可见。未知写未知。

## 6. 用营收目标指导复盘，不把热闹当成交

`marketing/douyin-studio/operations/performance.template.json` 仅为空值模板，未植入追踪代码或采集客户记录。每个期号在24/72小时各一条快照，单位和数据来源保持一致。

| 层级 | 看什么 | 决定什么 |
|---|---|---|
| 看到/愿意看 | 播放、观看时长、2秒跳出、相近时长完播 | 开头、节奏是否需要调整 |
| 真有需求 | 收藏、分享、具体经营问题、主页访问/咨询 | 选题是否吸引目标商家 |
| 真正体验 | 可核实来源的注册/关键体验动作 | 内容和产品体验是否匹配 |
| 真实收费 | 可核实归因的实收、退款、净回款 | 评估商业效果，不将净回款等同利润 |

缺来源写null/unknown，不记为0；没有打通抖音到网站的归因就不能归功于某条视频。按去重口径统计咨询/注册/付费，不存邮箱、手机号或订单原文。每次只改一个主要变量，不用小样本宣称标签导致增长。第7天依据真实表现选2–3个题材延展，主时段仍12:00/20:00。

## 7. 接续和下一步

首两条文本制作简报已按本轮方法写入 `marketing/douyin-studio/docs/series-01-02-production-brief.md`；它不是已渲染分镜或新视频。下一步在原工程内做6–8张高保真画面和13秒有声样片，先解决品牌层次、节奏和旁白，再扩成首两条完整片。新增制作授权不意味着必须运行旧云端脚本，也不授权公开发片/付费模型/生产部署。

仍未完成：新旁白/渲染链路验收、高保真帧、有声样片、首两条正式片、周期生成首次执行、电脑关机后的云端调度、未来连续发布方式和真实增长/收入数据。

安全证据目录：`D:/Codex-Verification/jiejing-growth-toolkit-20261008-2206/`；RECEIVE、INSTALL_VERIFIED、MEDIA_TOOLCHAIN_CHECK以及最终SAVE/STATUS_AFTER_SAVE回执。工作分支保持 `video/jiejing-11-continuity-20261006`，只保存本轮安全资料，不推main。源码/文档交出后，云端仍需receive且自行核验技能/运行时，才可称该端接入。
