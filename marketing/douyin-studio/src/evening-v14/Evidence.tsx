import React from "react";
import {useCurrentFrame} from "remotion";
import {Caption, lime, move, PaperSource, Set} from "./Art";

export const V14Evidence: React.FC = () => {
  const f = useCurrentFrame();
  const align = move(f, 0, 40, 0, 1);
  return <Set dark>
    <div style={{position: "absolute", top: 208, left: 89, fontSize: 98, fontWeight: 800, letterSpacing: -5, lineHeight: 1.25}}>原资料，<br/><span style={{color: lime}}>两份都留好。</span></div>
    <div style={{position: "absolute", top: 645 + 112 * (1-align), left: 94 - 22*(1-align), transform: `rotate(${-8*(1-align)}deg)`}}><PaperSource value="11.5" label="资料图标注"/></div>
    <div style={{position: "absolute", top: 645 - 140 * (1-align), left: 568 + 70*(1-align), transform: `rotate(${8*(1-align)}deg)`}}><PaperSource value="20" label="参数表标注" accent="#a84930"/></div>
    <svg style={{position: "absolute", top: 1070, left: 88}} width="855" height="290" viewBox="0 0 855 290"><path d="M201 8 V95 Q201 115 225 115 H634 Q654 115 654 95 V8 M429 115 V194" fill="none" stroke={lime} strokeWidth="3" strokeDasharray="1100" strokeDashoffset={1100*(1-move(f, 25, 70, 0, 1))}/></svg>
    <div style={{position: "absolute", top: 1258, left: 195, right: 225, padding: "20px 0", borderTop: "1px solid #658678", borderBottom: "1px solid #658678", textAlign: "center", fontSize: 48, color: lime, opacity: move(f, 55, 77, 0, 1)}}>对照依据 · 不擅自改数</div>
    <Caption dark>核对来源，不替供应商补答案。</Caption>
  </Set>;
};
