import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonWorkspace: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#24301f", color: "#fff8e9", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden"}}>
    <Img name="人整理草稿的情境" src={staticFile("noon-working.png")} style={{width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 3.9 * fps], [1.035, 1.095])}} />
    <AbsoluteFill style={{background: "linear-gradient(180deg,#182317b8,transparent 65%,#18231755)"}} />
    <Interactive.Div name="连接上架准备" style={{position: "absolute", left: 80, right: 130, top: 315, fontSize: 85, lineHeight: 1.28, letterSpacing: -2, fontWeight: 700, opacity: interpolate(frame, [.35 * fps, .7 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>把上架准备，<br/>接起来。</Interactive.Div>
    <SpokenLine from={0} frames={113} file="line-09.wav">捷境，把这段上架准备接起来。</SpokenLine>
  </AbsoluteFill>;
};
