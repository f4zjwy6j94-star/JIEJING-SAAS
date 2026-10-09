import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig, Interactive} from "remotion";
import {Frame, Product, accent, ink, ease} from "./Shared";

// New voice-synchronised draft scene; the historical FlowDraft stays unchanged.
export const ReviewDraft: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const title = "Tablet Stand";
  const typed = title.slice(0, Math.floor(interpolate(frame, [0.35 * fps, 1.25 * fps], [0, title.length], ease)));
  return <Frame dark>
    <Interactive.Div name="Content unfolds with narration" style={{position: "absolute", left: 84, top: 175, fontSize: 91, fontWeight: 750, lineHeight: 1.19, letterSpacing: -4, translate: `0px ${interpolate(frame, [0, 0.6 * fps], [55, 0], ease)}px`, opacity: interpolate(frame, [0, 0.3 * fps], [0, 1], ease)}}>不是换个工具，<br /><span style={{color: accent}}>是接着往下做。</span></Interactive.Div>
    <div style={{position: "absolute", left: 84, top: 482, width: 864, height: 940, background: "#f7f5ee", borderRadius: 36, color: ink, overflow: "hidden", scale: interpolate(frame, [0, 0.65 * fps], [0.93, 1], ease), boxShadow: "0 35px 85px #071c2550"}}>
      <div style={{position: "absolute", left: 38, top: 29, fontSize: 30, fontWeight: 650}}>内容草稿</div>
      <Interactive.Div name="草稿仍待核对" style={{position: "absolute", right: 32, top: 24, background: "#e9e9da", padding: "10px 20px", fontSize: 26, borderRadius: 12, border: "1px solid #b4c4a5", scale: interpolate(frame, [3.7 * fps, 4.0 * fps, 4.3 * fps], [1, 1.07, 1], ease), boxShadow: `0 0 0 ${interpolate(frame, [3.7 * fps, 4.0 * fps, 4.45 * fps], [0, 8, 0], ease)}px #b6cf7040`}}>待核对</Interactive.Div>
      <div style={{position: "absolute", left: 38, top: 110, width: 285, height: 290, borderRadius: 20, background: "#e7e9df"}}><Product /></div>
      <div style={{position: "absolute", left: 370, top: 126, fontSize: 28, color: "#71806f"}}>PRODUCT TITLE</div>
      <div style={{position: "absolute", left: 370, top: 186, right: 35, fontSize: 51, fontWeight: 700, lineHeight: 1.22, minHeight: 125}}>{typed}<span style={{opacity: frame < 1.4 * fps ? 1 : 0}}>│</span></div>
      <div style={{position: "absolute", left: 38, right: 38, top: 462, height: 1, background: "#d4dacb", scale: `${interpolate(frame, [1.1 * fps, 1.35 * fps], [0, 1], ease)} 1`, transformOrigin: "left"}} />
      <Interactive.Div name="卖点随口播出现" style={{position: "absolute", left: 38, top: 503, opacity: interpolate(frame, [1.25 * fps, 1.75 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [1.25 * fps, 1.75 * fps], [35, 0], ease)}px`}}><div style={{fontSize: 28, color: "#6c7c68"}}>卖点</div><div style={{fontSize: 43, fontWeight: 650, marginTop: 17}}>折叠结构 · 桌面使用</div></Interactive.Div>
      <Interactive.Div name="描述随口播出现" style={{position: "absolute", left: 38, right: 38, top: 666, opacity: interpolate(frame, [1.9 * fps, 2.35 * fps], [0, 1], ease), translate: `0px ${interpolate(frame, [1.9 * fps, 2.35 * fps], [35, 0], ease)}px`}}><div style={{fontSize: 28, color: "#6c7c68"}}>描述</div><div style={{fontSize: 39, lineHeight: 1.5, marginTop: 12}}>围绕你提供的商品资料，<br />准备标题、卖点和描述。</div></Interactive.Div>
    </div>
  </Frame>;
};
