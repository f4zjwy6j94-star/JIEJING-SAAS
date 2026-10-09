import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonThreshold: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#232c21", color: "#faf6e9", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden"}}>
    <Img name="手与键盘细节" src={staticFile("noon-working.png")} style={{width: "100%", height: "100%", objectFit: "cover", scale: 1.24, translate: interpolate(frame, [0, 2.94 * fps], ["-55px 20px", "-30px -5px"])}} />
    <AbsoluteFill style={{background: "linear-gradient(180deg,transparent 22%,#182217b3 74%)"}} />
    <Interactive.Div name="操作不是唯一难点" style={{position: "absolute", left: 80, top: 950, fontSize: 69, lineHeight: 1.3, fontWeight: 650, opacity: interpolate(frame, [0, .25 * fps], [0, 1], {extrapolateRight: "clamp"})}}>难的，<br/>不是最后那一下。</Interactive.Div>
    <SpokenLine from={0} frames={84} file="line-02.wav">问题往往不在最后那一下。</SpokenLine>
  </AbsoluteFill>;
};
