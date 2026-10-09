import React from "react";
import {Interactive, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {Product, accent, ease, font, ink, paper} from "./Shared";

type WebsiteCloseProps = {durationFrames?: number};

// Original product illustration and workflow summary, not a real listing result.
// Keep the website readable through the last frame; no end fade or black hold.
export const WebsiteClose: React.FC<WebsiteCloseProps> = ({durationFrames = 270}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const settleBy = Math.max(3.7 * fps, Math.min(5 * fps, durationFrames - 2 * fps));

  return <Interactive.Div name="结果收束与捷境官网" style={{position: "absolute", inset: 0, background: ink, color: paper, fontFamily: font, overflow: "hidden"}}>
    <div style={{position: "absolute", left: 336, top: 345, width: 1250, height: 1250, borderRadius: "50%", border: "1px solid #88a56b30", scale: interpolate(frame, [0, 3.6 * fps], [0.86, 1], ease)}} />
    <div style={{position: "absolute", left: 440, top: 450, width: 1040, height: 1040, borderRadius: "50%", border: "1px solid #88a56b20", scale: interpolate(frame, [0, 3.6 * fps], [0.9, 1], ease)}} />

    <Interactive.Div name="捷境品牌" style={{position: "absolute", left: 84, top: 176, fontSize: 78, fontWeight: 750, letterSpacing: -3, opacity: interpolate(frame, [0, 0.24 * fps], [0, 1], ease)}}>捷境</Interactive.Div>

    <Interactive.Div name="草稿结果收束" style={{position: "absolute", left: 84, top: 361, right: 112, fontSize: 98, fontWeight: 750, letterSpacing: -4, lineHeight: 1.2, opacity: interpolate(frame, [0, 0.24 * fps, 2.3 * fps, 2.7 * fps], [0, 1, 1, 0], ease), translate: `0px ${interpolate(frame, [2.3 * fps, 2.7 * fps], [0, -32], ease)}px`}}>资料有了，<br /><span style={{color: accent}}>草稿接上。</span></Interactive.Div>

    <div style={{position: "absolute", left: 84, top: 724, width: 482, height: 406, borderRadius: "50%", background: "radial-gradient(ellipse,#e1ebd810 0%,#e1ebd808 47%,transparent 70%)", opacity: interpolate(frame, [2.3 * fps, 2.9 * fps], [1, 0], ease)}} />
    <Interactive.Div name="商品缩小归位" style={{position: "absolute", left: interpolate(frame, [2.25 * fps, 3.1 * fps], [80, 756], ease), top: interpolate(frame, [2.25 * fps, 3.1 * fps], [670, 151], ease), width: 486, height: 480, scale: interpolate(frame, [2.25 * fps, 3.1 * fps], [1, 0.33], ease), transformOrigin: "0 0", rotate: interpolate(frame, [0, 2.25 * fps, 3.1 * fps], ["-4deg", "2deg", "0deg"], ease), filter: "drop-shadow(0 22px 28px #061d1740)"}}><div style={{position: "absolute", left: 14, top: 61, width: 455, height: 366, borderRadius: "50%", background: "#e9eedf"}} /><Product style={{position: "relative"}} /></Interactive.Div>

    <Interactive.Div name="结果清单标题" style={{position: "absolute", left: 574, top: 728, right: 112, fontSize: 46, fontWeight: 650, lineHeight: 1.5, opacity: interpolate(frame, [0.12 * fps, 0.35 * fps, 2.25 * fps, 2.6 * fps], [0, 1, 1, 0], ease), translate: `0px ${interpolate(frame, [0.12 * fps, 0.35 * fps], [22, 0], ease)}px`}}><span style={{color: accent, paddingRight: 18}}>—</span>标题草稿</Interactive.Div>
    <Interactive.Div name="结果清单卖点" style={{position: "absolute", left: 574, top: 826, right: 112, fontSize: 46, fontWeight: 650, lineHeight: 1.5, opacity: interpolate(frame, [0.35 * fps, 0.6 * fps, 2.25 * fps, 2.6 * fps], [0, 1, 1, 0], ease), translate: `0px ${interpolate(frame, [0.35 * fps, 0.6 * fps], [22, 0], ease)}px`}}><span style={{color: accent, paddingRight: 18}}>—</span>卖点草稿</Interactive.Div>
    <Interactive.Div name="结果清单描述" style={{position: "absolute", left: 574, top: 924, right: 112, fontSize: 46, fontWeight: 650, lineHeight: 1.5, opacity: interpolate(frame, [0.6 * fps, 0.85 * fps, 2.25 * fps, 2.6 * fps], [0, 1, 1, 0], ease), translate: `0px ${interpolate(frame, [0.6 * fps, 0.85 * fps], [22, 0], ease)}px`}}><span style={{color: accent, paddingRight: 18}}>—</span>描述草稿</Interactive.Div>
    <Interactive.Div name="商家核对" style={{position: "absolute", left: 84, top: 1110, right: 112, fontSize: 44, lineHeight: 1.35, color: "#d2dcc3", opacity: interpolate(frame, [0.65 * fps, 0.95 * fps, 2.25 * fps, 2.6 * fps], [0, 1, 1, 0], ease)}}>草稿先核对，再继续。</Interactive.Div>

    <Interactive.Div name="官网行动主标题" style={{position: "absolute", left: 84, top: 425, right: 112, fontSize: 102, lineHeight: 1.2, letterSpacing: -4, fontWeight: 750, opacity: interpolate(frame, [2.6 * fps, 3.2 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [2.6 * fps, 3.2 * fps], [48, 0], ease)}px`}}>从一个商品，<br /><span style={{color: accent}}>开始用捷境。</span></Interactive.Div>

    <Interactive.Div name="从一个商品开始" style={{position: "absolute", left: 84, top: 870, right: 112, fontSize: 46, fontWeight: 500, color: "#d4dec7", opacity: interpolate(frame, [3.1 * fps, 3.65 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [3.1 * fps, 3.65 * fps], [24, 0], ease)}px`}}>带上商品资料，准备第一份草稿。</Interactive.Div>
    <div style={{position: "absolute", left: 84, top: 990, width: 864, height: 2, background: "#79995e66", transformOrigin: "left", scale: `${interpolate(frame, [3.4 * fps, settleBy], [0, 1], ease)} 1`}} />

    <Interactive.Div name="捷境官网地址保持至末帧" style={{position: "absolute", left: 84, top: 1195, width: 864, height: 132, borderRadius: 26, boxSizing: "border-box", padding: "0 34px", display: "flex", alignItems: "center", justifyContent: "space-between", background: accent, color: ink, opacity: interpolate(frame, [1.7 * fps, 2 * fps], [0, 1], ease), boxShadow: "0 18px 50px #091a132c"}}>
      <span style={{fontFamily: '"Arial", "Microsoft YaHei", sans-serif', fontSize: 77, fontWeight: 650, letterSpacing: -2}}>jiejing.shop</span>
      <span style={{fontSize: 67, fontWeight: 400, paddingRight: 7}}>↗</span>
    </Interactive.Div>
    <Interactive.Div name="当前支持与确认边界" style={{position: "absolute", left: 84, top: 1364, right: 112, fontSize: 42, lineHeight: 1.3, color: "#d9e3cf", opacity: interpolate(frame, [2.9 * fps, 3.35 * fps], [0, 1], ease)}}>当前先支持 eBay<br />发布由你确认</Interactive.Div>
  </Interactive.Div>;
};
