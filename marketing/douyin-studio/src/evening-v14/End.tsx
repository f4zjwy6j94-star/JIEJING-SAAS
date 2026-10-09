import React from "react";
import {useCurrentFrame} from "remotion";
import {Caption, lime, Mat, move, Set} from "./Art";

export const V14End: React.FC = () => {
  const f = useCurrentFrame();
  return <Set dark>
    <div style={{position: "absolute", top: 213, left: 92, fontSize: 54, fontWeight: 800}}>捷境<span style={{display: "inline-block", width: 42, height: 4, background: lime, verticalAlign: "middle", marginLeft: 24}}/></div>
    <div style={{position: "absolute", top: 392, left: 85, fontSize: 99, fontWeight: 800, letterSpacing: -5, lineHeight: 1.32}}>让 AI 整理。<br/><span style={{color: lime}}>让证据决定。</span></div>
    <div style={{position: "absolute", top: 757, left: 143, transform: `translateY(${move(f, 0, 119, 0, -32)}px)`}}><Mat width={690} tilt={48} angle={move(f, 0, 119, -9, 9)}/></div>
    <div style={{position: "absolute", top: 1420, left: 90, fontFamily: "Arial,sans-serif", fontSize: 67, letterSpacing: -1}}>jiejing.shop</div>
    <Caption dark>分享跨境电商里的 AI 工作方法</Caption>
  </Set>;
};
