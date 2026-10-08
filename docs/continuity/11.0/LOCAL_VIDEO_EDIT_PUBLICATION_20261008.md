# 本地10.0：v10删句版与抖音提交回执

日期：2026-10-08，北京时间。负责端：本地10.0。此为安全工作记录，不含媒体、登录态或原始日志。

## 用户最新决定与状态

用户已下载旁白重音修正版，明确要求审看片、删除“不能保证绝不侵权”那句话、另存桌面，并由助手接管本机在捷境抖音发布。只授权这条视频及其例行标题/简介/封面设置，不是今后全部发片、投流、付费服务、SaaS部署或真实eBay操作的授权。该决定取代本条影片此前“仅下载，由经营者自行发布”的限制。

本地已完成剪辑、另存和一次发布提交。内容管理页面显示新作时间 **2026-10-08 21:18、审核中**。这证明提交已被平台接收，不证明审核通过、已公开可见或商业效果。不要再次发布来测试结果。

## 来源与成果

- 实际源码根：`C:/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo`。
- 开工status/receive退出0，分支 `video/jiejing-11-continuity-20261006`，本地/远端 `befbd09e396a62288440bf4fb816bfb3179be580`，clean/equal。
- 原片：`C:/Users/57249/OneDrive/桌面/jiejing-douyin-v10-audio-fixed.mp4`。
- 原片：86秒、31,862,665字节，SHA256 `005d2a12eec95e50a9b9054ba9b51c2cd8a7daaa4e8278554a3e191af757b458`；与已交付云端修正版一致，剪辑后仍相同，未覆盖。
- 桌面新片：`C:/Users/57249/OneDrive/桌面/捷境抖音推广_v10_删句版_20261008.mp4`。
- 新片：视频77.666667秒、音频77.682秒，1080×1920，30fps，2330帧，H.264/yuv420p、AAC/48kHz/双声道，15,263,691字节。
- 新片SHA256：`0fa4a5f264e0ffe656b6e07b66bacee0821f0972613869569ba9a93976d7b6dc`。
- D盘母版：`D:/Codex-Verification/jiejing-v10-publish-edit-20261008-2058/jiejing-douyin-v10-promo-final.mp4`，与桌面副本SHA一致。

## 实际审看与修改

沿用既有影片视觉风格，不重做品牌、声音或业务流程。检查原片关键帧、对应v10源码/字幕与素材时序：目标话语不仅存在于旁白/烧录字幕，还出现在“不是保证绝不侵权”画面卡片。为避免残留上下文，完整移除侵权初筛这一章，而不是只把“不保证”字样遮掉。

删去原帧区间 `[1596,1840)`（30fps），即原53.2–61.333333秒；留下0–1595与1840–2579帧。0.2秒/6帧向上擦除转场和音频三角交叉淡化，使站内修改接到核对确认发布。原章节编号保持，不擅自重排其余影片。未改为任何“绝不侵权”承诺；保留资料核对、真实货源、重要操作确认、当前eBay与未来平台规划的准确限定。删词不构成法律/IP风险审查通过。

可复现FFmpeg滤镜（现有原片30fps、音轨48kHz）：

```text
[0:v]split=2[va][vb];
[va]trim=end_frame=1596,setpts=PTS-STARTPTS,settb=AVTB[v0];
[vb]trim=start_frame=1840,setpts=PTS-STARTPTS,settb=AVTB[v1];
[v0][v1]xfade=transition=wipeup:duration=0.2:offset=53.0,format=yuv420p[v];
[0:a]asplit=2[aa][ab];
[aa]atrim=end_sample=2553600,asetpts=PTS-STARTPTS[a0];
[ab]atrim=start_sample=2944000,asetpts=PTS-STARTPTS[a1];
[a0][a1]acrossfade=d=0.2:c1=tri:c2=tri[a]
```

编码用既有WSL Ubuntu `/usr/bin/ffmpeg`，libx264/medium/CRF18、30fps、yuv420p/bt709，AAC192k/48kHz，faststart；不安装工具，不调用新模型或付费服务。原始HyperFrames源码/历史ZIP未改；本次为源MP4的无损保留、另行重新编码导出，不宣称新片码流无损。

## 验证与遇到的工具限制

- 最终渲染退出0；完整音视频解码退出0；来源SHA未变；桌面副本SHA相同。
- 新片左右声道差分RMS比 `0.0022377048661399493`，未重新引入旧300ms错位；这属于信号检查，不冒称人耳听过/音色完美。
- 原片关键帧及删段两侧边界、最终接缝帧已视觉检查；封面取自新片10秒，不重新生成有误导性的功能画面。
- Remotion自带Windows FFmpeg可读元信息/截图，但精简构建缺少setpts/xfade；初次渲染失败，未把失败计入完成。改用已经安装的WSL FFmpeg成功。WSL复杂参数经shell解释曾失败，改为 `wsl.exe -d Ubuntu -e` 与滤镜文件；未改代理或网络设置。
- 第一版交叉溶解造成短暂重叠字幕，保留草稿并改为上推擦除；正式发布的是 `promo-final`/桌面删句版，不是 `promo-cut` 草稿。
- 原 `MEDIA_QA_FINAL.safe.json` 的 `publication_status=not_uploaded` 是验证时尚未上传的阶段快照，保留不篡改；后续发布状态以 `PUBLICATION.safe.json` 和截图为准。

## 浏览器与发布内容

使用本机已连接Chrome扩展（本轮ID3、ZONGSHU配置），不是云端浏览器。账号实时显示“捷境AI电商SAAS”，抖音号 `51406410196`。ID/标签号是本轮值，不能硬编码为永久身份。未扫码、退出、重启、清Cookie或修改浏览器权限。

标题：**把电商上架准备交给AI，重要决定留给你**

简介：

```text
捷境，把调研、商品内容、图片视频与确认发布接起来。
有货源，带上真实商品资料；没货源，先研究，再找真实货源。
当前支持 eBay，重要操作由你确认。
#捷境 #跨境电商 #eBay #AI工具
```

设置：公开、立即发布；内容声明“内容由AI生成”；同一真实视频帧分别裁为3:4竖封面和4:3横封面。未定位、投流、加入额外活动或更改旧作品。封面检测通过；作品预检“作品未见异常”是平台预检，不替代最终审核或法律保证。

按明确授权点击发布一次；随后实际跳转内容管理，出现该标题/简介、01:18、2026-10-08 21:18及“审核中”。没有因异步跳转重复点击。管理页：`https://creator.douyin.com/creator-micro/content/manage?enter_from=publish`；未获得可核验的公众作品分享链接，不猜作品ID。

## 本地证据、交接与下一步

证据根：`D:/Codex-Verification/jiejing-v10-publish-edit-20261008-2058/`。

- `EDIT_PLAN.safe.json`、`edit.ffgraph`、`verify_edit.py`：本地剪辑配方/验证入口。
- `MEDIA_QA_FINAL.safe.json`：正式新片核验；前一草稿/QA仍保留。
- `PUBLICATION.safe.json`：本次提交及限定状态的安全回执。
- `douyin-submitted-review.jpg`：只截取新作品及管理页上下文，避免带入无关旧私密作品；SHA256 `522cba3c2bda9f4817e0b0af5e5141cb85cb8d6129d2060c4ca46e15cb93b6c5`。
- `SAVE.safe.json`、`STATUS_AFTER_SAVE.safe.json`：共享分支保存的实际结果，不在提交前虚报成功或写自引用HEAD。

另一端需按WORK_SYNC实际receive后读取最新摘要，不能把共享分支已交出等同云端已经接收。云端收到的是安全文档和剪辑配方，改版媒体/截图仍在本地，没有上传GitHub媒体附件、COS或新增存储点。保留旧10.0/11.0与原7份保全文档，v10 ZIP及全量素材未完成的边界不变。

下一步是根据平台审核结果继续推广，不能重复上传此片或宣称已公开。当前没有新建后台监控/自动发布计划，不承诺自动通知。用户可从保留的内容管理页查看审核。SaaS原三项失败和生产接入未验收事项原状保留，本轮没有部署、改业务代码、生产/拼嘚访问、真实资金或新增费用。
