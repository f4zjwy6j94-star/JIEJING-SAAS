import React from "react";
import {useCurrentFrame} from "remotion";
import {Caption, coral, ink, Mat, move, PaperSource, Set} from "./Art";

export const V14Draft: React.FC = () => {
  const f = useCurrentFrame();
  const t = move(f, 0, 47, 0, 1);
  return <Set>
    <div style={{position: "absolute", top: 202, left: 89, fontSize: 101, fontWeight: 800, lineHeight: 1.24, letterSpacing: -5}}>资料先整理，<br/>尺寸等核实。</div>
    <div style={{position: "absolute", top: 706, left: -154, transform: `scale(${1-t*.24}) rotate(-9deg)`, opacity: 1-t*.5}}><Mat width={725} angle={0} tilt={34}/></div>
    <div style={{position: "absolute", left: 198, top: 662 + (1-t)*565, width: 683, background: "#fffcf6", boxShadow: "0 28px 65px #283a2430", border: "1px solid #d9d8c9", padding: "50px 43px", transform: `rotate(${-3*t}deg)`, opacity: move(f, 0, 18, 0, 1)}}>
      <div style={{fontSize: 67, fontWeight: 800, marginBottom: 40}}>过滤盖 / 草稿</div>
      <div style={{borderTop: "1px solid #d5d9cc", padding: "36px 0", display: "flex", justifyContent: "space-between", fontSize: 46}}><span style={{color: "#6c786a"}}>来源</span><span>原图 + 参数表</span></div>
      <div style={{borderTop: "1px solid #d5d9cc", padding: "36px 0", display: "flex", justifyContent: "space-between", fontSize: 49}}><span style={{color: "#6c786a"}}>尺寸</span><span style={{color: "#a74933", background: `${coral}30`, padding: "3px 13px", transform: `scale(${move(f, 76, 99, 1, 1.09)})`}}>待核实</span></div>
      <div style={{borderTop: "1px solid #d5d9cc", padding: "37px 0 7px", fontSize: 45, color: ink, opacity: move(f, 44, 63, 0, 1)}}>确认后，再填真实参数</div>
    </div>
    <div style={{position: "absolute", left: move(f, 0, 47, 94, 381), top: move(f, 0, 47, 645, 828), transformOrigin: "0 0", transform: `scale(${1-t*.75})`, opacity: 1-move(f, 32, 47, 0, 1)}}><PaperSource value="11.5" label="资料图标注"/></div>
    <div style={{position: "absolute", left: move(f, 0, 47, 568, 614), top: move(f, 0, 47, 645, 828), transformOrigin: "0 0", transform: `scale(${1-t*.75})`, opacity: 1-move(f, 32, 47, 0, 1)}}><PaperSource value="20" label="参数表标注" accent="#a84930"/></div>
    <Caption>让 AI 整理，参数凭证据。</Caption>
  </Set>;
};
