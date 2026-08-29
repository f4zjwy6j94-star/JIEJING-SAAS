# 捷境抖音视频工作室

独立于生产 SaaS 的本地 Remotion 工程，用真实捷境页面截图生成统一的 9:16 演示视频、封面和头像。

## 安装

```console
npm install
```

## 准备运行时素材

将经过隐私检查的当前生产页面截图放入：

```text
public/captures/listing-page.png
```

将审定后的旁白放入：

```text
public/audio/launch-01-voice.wav
```

这两个目录默认不提交 Git。

## 预览与渲染

```console
npm run dev
npm run render:launch-01
npm run render:cover-01
npm run render:cover-horizontal-01
npm run render:avatar
```

## 对外口径

- 当前支持 eBay；其他平台只能说是规划方向。
- 客服能力只说“生成回复建议与风险分流”。
- 真实发布、改价、退款、广告和敏感承诺仍由商家确认。
- 使用 AI 生成的图像、文本、配音或视频时，在抖音发布页主动声明。
