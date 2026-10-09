import React from "react";
import {Interactive, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {Product, ease, font, ink, paper, accent} from "./Shared";

export const ReviewClose: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <Interactive.Div name="捷境收束" style={{position: "absolute", inset: 0, background: ink, color: paper, fontFamily: font, overflow: "hidden"}}>
    <div style={{position: "absolute", left: -105, top: 690, width: 1200, height: 1200, borderRadius: "50%", border: "1px solid #69836355", scale: interpolate(frame, [0, 3 * fps], [0.82, 1.06], ease)}} />
    <Interactive.Div name="产品名" style={{position: "absolute", left: 84, top: 181, fontSize: 78, letterSpacing: -3, fontWeight: 750, opacity: interpolate(frame, [0, 0.3 * fps], [0, 1], ease)}}>捷境</Interactive.Div>
    <Interactive.Div name="价值收束" style={{position: "absolute", left: 84, top: 365, right: 100, fontSize: 105, lineHeight: 1.18, letterSpacing: -5, fontWeight: 750, translate: `0px ${interpolate(frame, [0, 0.45 * fps], [55, 0], ease)}px`, opacity: interpolate(frame, [0, 0.3 * fps, 2.6 * fps, 3.25 * fps], [0, 1, 1, 0], ease)}}>少一点来回。<br /><span style={{color: accent}}>多一点推进。</span></Interactive.Div>
    <div style={{position: "absolute", left: 240, top: 755, width: 570, height: 480, background: "#e9eee2", borderRadius: 36, rotate: interpolate(frame, [0, 2.8 * fps], ["2deg", "-3deg"], ease), scale: interpolate(frame, [0, 0.5 * fps], [0.8, 1], ease), boxShadow: "0 25px 75px #071a1645", opacity: interpolate(frame, [2.6 * fps, 3.25 * fps], [1, 0], ease)}}><Product /></div>
    <Interactive.Div name="当前支持范围" style={{position: "absolute", left: 84, top: 1335, right: 112, fontSize: 44, lineHeight: 1.55, fontWeight: 600, color: "#ecf0df", opacity: interpolate(frame, [2.6 * fps, 3.25 * fps], [1, 0], ease)}}>当前先支持 eBay<br /><span style={{color: accent}}>发布前，由你确认。</span></Interactive.Div>
    <Interactive.Div name="把问题留给商家" style={{position: "absolute", left: 84, top: 395, right: 100, fontSize: 94, lineHeight: 1.25, letterSpacing: -4, fontWeight: 750, opacity: interpolate(frame, [3.05 * fps, 3.55 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [3.05 * fps, 3.55 * fps], [45, 0], ease)}px`}}>你最费时间的，<br /><span style={{color: accent}}>是哪一步？</span></Interactive.Div>
    <Interactive.Div name="选项写文案" style={{position: "absolute", left: 84, top: 935, width: 864, height: 143, boxSizing: "border-box", padding: "0 41px", display: "flex", alignItems: "center", justifyContent: "space-between", borderRadius: 25, background: paper, color: ink, fontSize: 56, fontWeight: 700, opacity: interpolate(frame, [3.35 * fps, 3.75 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [3.35 * fps, 3.75 * fps], [40, 0], ease)}px`}}><span>写文案</span><span style={{fontWeight: 400, color: "#6b8651"}}>↗</span></Interactive.Div>
    <Interactive.Div name="选项做商品图" style={{position: "absolute", left: 84, top: 1117, width: 864, height: 143, boxSizing: "border-box", padding: "0 41px", display: "flex", alignItems: "center", justifyContent: "space-between", borderRadius: 25, background: accent, color: ink, fontSize: 56, fontWeight: 700, opacity: interpolate(frame, [3.75 * fps, 4.15 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [3.75 * fps, 4.15 * fps], [40, 0], ease)}px`}}><span>做商品图</span><span style={{fontWeight: 400, color: "#506634"}}>↗</span></Interactive.Div>
  </Interactive.Div>;
};
