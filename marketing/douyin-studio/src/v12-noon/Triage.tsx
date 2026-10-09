import React from "react";
import {AbsoluteFill, Interactive, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

// An editorial sorting metaphor, never a claimed automatic detection screen.
export const NoonTriage: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#ebe5d9", color: "#273725", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden"}}>
    <div style={{position: "absolute", inset: 0, background: "radial-gradient(ellipse at 15% 20%,#fff9ef,transparent 60%)"}} />
    <Interactive.Div name="先理清资料" style={{position: "absolute", left: 80, top: 230, fontSize: 82, lineHeight: 1.3, letterSpacing: -2, fontWeight: 720}}>先理清，<br/>再开始写。</Interactive.Div>
    <Interactive.Div name="有依据目的位置" style={{position: "absolute", left: 85, top: 640, width: 395, height: 575, borderTop: "4px solid #50704f", backgroundColor: "#d8dfcf", opacity: interpolate(frame, [3.2 * fps, 3.7 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}><div style={{padding: "30px 30px", fontSize: 43, fontWeight: 700}}>有依据</div></Interactive.Div>
    <Interactive.Div name="待确认目的位置" style={{position: "absolute", left: 505, top: 640, width: 395, height: 575, borderTop: "4px solid #a98c5b", backgroundColor: "#e7d8bd", opacity: interpolate(frame, [4.8 * fps, 5.3 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}><div style={{padding: "30px 30px", fontSize: 43, fontWeight: 700}}>待确认</div></Interactive.Div>
    <Interactive.Div name="确认信息分到左侧" style={{position: "absolute", left: 240, top: 805, width: 325, padding: "40px 28px", backgroundColor: "#fffaf0", boxShadow: "0 16px 40px #403d2d24", fontSize: 43, lineHeight: 1.45, rotate: interpolate(frame, [0, 3.15 * fps, 4.1 * fps], ["-7deg", "-7deg", "0deg"], {extrapolateRight: "clamp"}), translate: interpolate(frame, [3.15 * fps, 4.1 * fps], ["0px 0px", "-130px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>已确认<br/>的信息</Interactive.Div>
    <Interactive.Div name="缺项分到右侧" style={{position: "absolute", left: 435, top: 1000, width: 325, padding: "40px 28px", backgroundColor: "#f5ecd9", boxShadow: "0 16px 40px #403d2d24", fontSize: 43, lineHeight: 1.45, rotate: interpolate(frame, [0, 4.6 * fps, 5.5 * fps], ["6deg", "6deg", "0deg"], {extrapolateRight: "clamp"}), translate: interpolate(frame, [4.6 * fps, 5.5 * fps], ["0px 0px", "95px -195px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>还缺<br/>哪些资料？</Interactive.Div>
    <SpokenLine from={0} frames={83} file="line-05.wav">别急着把它们全塞进标题。</SpokenLine>
    <SpokenLine from={87} frames={143} file="line-06.wav">先分清，哪些有依据，哪些还要确认。</SpokenLine>
  </AbsoluteFill>;
};
