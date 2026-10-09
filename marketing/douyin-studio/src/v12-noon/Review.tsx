import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonReview: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#213019", color: "#fff8e9", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden"}}>
    <Img name="检查实物细节" src={staticFile("noon-detail.png")} style={{width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 4.5 * fps], [1.17, 1.025])}} />
    <AbsoluteFill style={{background: "linear-gradient(180deg,#1b281cd9,transparent 55%,#14201655)"}} />
    <Interactive.Div name="人与AI协作" style={{position: "absolute", left: 80, top: 230, fontSize: 70, lineHeight: 1.35, fontWeight: 700}}>你和 AI<br/>一起完善。</Interactive.Div>
    <Interactive.Div name="人工确认强调" style={{position: "absolute", left: 80, top: 510, fontSize: 72, lineHeight: 1.3, color: "#f1ce91", fontWeight: 700, opacity: interpolate(frame, [2.25 * fps, 2.65 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), translate: interpolate(frame, [2.25 * fps, 2.8 * fps], ["0px 35px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>重要操作，<br/>由你确认。</Interactive.Div>
    <SpokenLine from={0} frames={131} file="line-10.wav">你和AI一起完善，重要操作由你确认。</SpokenLine>
  </AbsoluteFill>;
};
