import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonOpening: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#172016", color: "#fffaf0", overflow: "hidden", fontFamily: '"Microsoft YaHei", sans-serif'}}>
    <Img name="开箱近景" src={staticFile("noon-unboxing.png")} style={{width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 4.53 * fps], [1.13, 1.015])}} />
    <AbsoluteFill style={{background: "linear-gradient(180deg,#121c13cf,transparent 48%,#11180d44)"}} />
    <Interactive.Div name="开场钩子" style={{position: "absolute", left: 80, right: 150, top: 240, fontSize: 84, fontWeight: 750, letterSpacing: -2, lineHeight: 1.23, opacity: interpolate(frame, [0, .18 * fps, 2.3 * fps, 2.5 * fps], [1, 1, 1, 0], {extrapolateRight: "clamp"})}}>货源图<br/>都有了。</Interactive.Div>
    <Interactive.Div name="上架前卡点" style={{position: "absolute", left: 80, right: 150, top: 240, fontSize: 84, fontWeight: 750, letterSpacing: -2, lineHeight: 1.23, opacity: interpolate(frame, [2.4 * fps, 2.7 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), translate: interpolate(frame, [2.4 * fps, 2.9 * fps], ["0px 30px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>怎么还卡在<br/><span style={{color: "#f2cd8c"}}>上架前？</span></Interactive.Div>
    <SpokenLine from={8} frames={124} file="line-01.wav">货源图都有了，怎么还卡在上架前？</SpokenLine>
  </AbsoluteFill>;
};
