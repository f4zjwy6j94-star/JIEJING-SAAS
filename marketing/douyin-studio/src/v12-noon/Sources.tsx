import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonSources: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#272d21", color: "#fff8e9", overflow: "hidden", fontFamily: '"Microsoft YaHei", sans-serif'}}>
    <Img name="俯拍散落资料" src={staticFile("noon-sorting.png")} style={{width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 6.67 * fps], [1.13, 1])}} />
    <AbsoluteFill style={{background: "linear-gradient(180deg,#132017a3,transparent 50%,#151d1180)"}} />
    <Interactive.Div name="散落资料标题" style={{position: "absolute", left: 80, top: 180, fontSize: 78, lineHeight: 1.28, fontWeight: 700}}>真正卡住的，<br/>是散落的资料。</Interactive.Div>
    <Interactive.Div name="图片归位" style={{position: "absolute", left: 85, top: 580, padding: "24px 32px", backgroundColor: "#f4eddf", color: "#233425", boxShadow: "0 18px 50px #0004", fontSize: 47, rotate: interpolate(frame, [2.57 * fps, 3.1 * fps], ["-9deg", "-3deg"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), opacity: interpolate(frame, [2.57 * fps, 2.8 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), translate: interpolate(frame, [2.57 * fps, 3.1 * fps], ["-110px 70px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>照片</Interactive.Div>
    <Interactive.Div name="规格表归位" style={{position: "absolute", right: 175, top: 880, padding: "24px 32px", backgroundColor: "#ecdabb", color: "#233425", boxShadow: "0 18px 50px #0004", fontSize: 47, rotate: interpolate(frame, [3.25 * fps, 3.8 * fps], ["9deg", "3deg"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), opacity: interpolate(frame, [3.25 * fps, 3.5 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), translate: interpolate(frame, [3.25 * fps, 3.8 * fps], ["100px 40px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>规格表</Interactive.Div>
    <Interactive.Div name="聊天补充归位" style={{position: "absolute", left: 150, top: 1150, padding: "24px 32px", backgroundColor: "#dae1cb", color: "#233425", boxShadow: "0 18px 50px #0004", fontSize: 47, rotate: "-2deg", opacity: interpolate(frame, [4.15 * fps, 4.45 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), translate: interpolate(frame, [4.15 * fps, 4.65 * fps], ["-30px 100px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>聊天补充</Interactive.Div>
    <SpokenLine from={0} frames={73} file="line-03.wav">而在这些散落的资料里。</SpokenLine>
    <SpokenLine from={77} frames={119} file="line-04.wav">照片，规格表，聊天里的补充说明。</SpokenLine>
  </AbsoluteFill>;
};
