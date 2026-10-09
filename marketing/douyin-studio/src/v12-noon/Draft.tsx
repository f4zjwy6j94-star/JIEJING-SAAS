import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonDraft: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#e9e3d6", color: "#273b2b", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden"}}>
    <Interactive.Div name="资料变成纸面草稿" style={{position: "absolute", left: 55, right: 110, top: 175, height: 1210, backgroundColor: "#fffaf0", boxShadow: "0 25px 100px #45402a33", rotate: interpolate(frame, [0, .7 * fps], ["-3deg", "0deg"], {extrapolateRight: "clamp"}), translate: interpolate(frame, [0, .7 * fps], ["0px 100px", "0px 0px"], {extrapolateRight: "clamp"})}}>
      <div style={{position: "absolute", left: 55, top: 55, fontSize: 33, letterSpacing: 5, color: "#718068"}}>商品资料 → 上架草稿</div>
      <Img name="照片进入草稿" src={staticFile("noon-detail.png")} style={{position: "absolute", top: 145, left: 55, width: 360, height: 460, objectFit: "cover", objectPosition: "50% 63%"}} />
      <Interactive.Div name="标题落位" style={{position: "absolute", left: 460, top: 155, fontSize: 55, fontWeight: 700, opacity: interpolate(frame, [.1 * fps, .55 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>标题</Interactive.Div>
      <Interactive.Div name="参数落位" style={{position: "absolute", left: 460, top: 310, fontSize: 55, fontWeight: 700, opacity: interpolate(frame, [.9 * fps, 1.35 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>参数</Interactive.Div>
      <Interactive.Div name="卖点落位" style={{position: "absolute", left: 460, top: 465, fontSize: 55, fontWeight: 700, opacity: interpolate(frame, [1.6 * fps, 2.05 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>卖点</Interactive.Div>
      <Interactive.Div name="依据连线" style={{position: "absolute", left: 55, top: 670, height: 3, width: interpolate(frame, [2.2 * fps, 3 * fps], [0, 730], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), backgroundColor: "#abb79e"}} />
      <Interactive.Div name="草稿依赖真实资料" style={{position: "absolute", left: 55, right: 70, top: 735, fontSize: 68, lineHeight: 1.3, fontWeight: 700, opacity: interpolate(frame, [3.5 * fps, 4 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>草稿的底气，<br/>来自真实资料。</Interactive.Div>
      <Interactive.Div name="不凭空补参数" style={{position: "absolute", left: 55, top: 980, fontSize: 35, color: "#727e66", opacity: interpolate(frame, [4.7 * fps, 5.2 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>缺项先补齐，不凭空写。</Interactive.Div>
    </Interactive.Div>
    <SpokenLine from={0} frames={103} file="line-07.wav">再整理标题、参数和卖点。</SpokenLine>
    <SpokenLine from={107} frames={111} file="line-08.wav">有了真实资料，才有靠谱的草稿。</SpokenLine>
  </AbsoluteFill>;
};
