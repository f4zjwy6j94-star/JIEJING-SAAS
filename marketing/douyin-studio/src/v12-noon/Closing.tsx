import React from "react";
import {AbsoluteFill, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {SpokenLine} from "./SpokenLine";

export const NoonClosing: React.FC = () => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: "#1d2b1e", color: "#fbf5e7", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden"}}>
    <Img name="整理后的桌面" src={staticFile("noon-sorting.png")} style={{width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 6.27 * fps], [1.025, 1.09])}} />
    <AbsoluteFill style={{backgroundColor: "#16281ddb"}} />
    <Interactive.Div name="当前平台范围" style={{position: "absolute", left: 80, top: 315, fontSize: 47, lineHeight: 1.5, color: "#dfd9c6"}}>当前先支持 <span style={{color: "#f1ce91", fontSize: 70}}>eBay</span></Interactive.Div>
    <Interactive.Div name="单一互动问题" style={{position: "absolute", left: 80, right: 130, top: 615, fontSize: 87, lineHeight: 1.3, fontWeight: 700, letterSpacing: -2, opacity: interpolate(frame, [2.2 * fps, 2.55 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}), translate: interpolate(frame, [2.2 * fps, 2.85 * fps], ["0px 35px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>你上架前，<br/>最容易卡在<br/><span style={{color: "#f1ce91"}}>哪一步？</span></Interactive.Div>
    <div style={{position: "absolute", left: 80, top: 1250, fontSize: 40, letterSpacing: 5, color: "#e1e3d3"}}>捷境</div>
    <SpokenLine from={0} frames={62} file="line-11.wav">当前先支持eBay。</SpokenLine>
    <SpokenLine from={66} frames={108} file="line-12.wav">你上架前，最容易卡在哪一步？</SpokenLine>
  </AbsoluteFill>;
};
