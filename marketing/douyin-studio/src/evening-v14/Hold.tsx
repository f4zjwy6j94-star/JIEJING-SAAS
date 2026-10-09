import React from "react";
import {useCurrentFrame} from "remotion";
import {Caption, coral, ink, move, PaperSource, Set} from "./Art";

export const V14Hold: React.FC = () => {
  const f = useCurrentFrame();
  const p = move(f, 0, 24, 0, 1);
  return <Set>
    <div style={{position: "absolute", top: 202, left: 89, fontSize: 116, fontWeight: 800, letterSpacing: -6, lineHeight: 1.2}}>先别填。</div>
    <div style={{position: "absolute", top: 369, left: 92, fontSize: 47, color: "#5a6b5e"}}>标注冲突，先问清再写。</div>
    <div style={{position: "absolute", top: 590, left: move(f, 0, 36, -200, 74), transform: `rotate(${move(f, 0, 36, -12, -6)}deg)`}}><PaperSource value="11.5" label="资料图标注"/></div>
    <div style={{position: "absolute", top: 755, left: move(f, 0, 36, 1060, 502), transform: `rotate(${move(f, 0, 36, 17, 7)}deg)`}}><PaperSource value="20" label="参数表标注" accent="#a84930"/></div>
    <div style={{position: "absolute", top: 1152, left: 92, right: 120, height: 189, borderTop: `2px solid ${ink}`, borderBottom: `2px solid ${ink}`, display: "flex", alignItems: "center", justifyContent: "space-between", transform: `translateY(${(1-p)*70}px)`, opacity: p}}>
      <span style={{fontSize: 45}}>商品尺寸</span><span style={{fontSize: 65, fontWeight: 800, color: "#aa4932", background: `${coral}30`, padding: "12px 22px"}}>待核实</span>
    </div>
    <Caption>先确认，再写进草稿。</Caption>
  </Set>;
};
