import React from "react";
import {useCurrentFrame} from "remotion";
import {Caption, Carton, coral, ink, Mat, move, Set} from "./Art";

export const V14Ask: React.FC = () => {
  const f = useCurrentFrame();
  const evidence = move(f, 108, 127, 0, 1);
  return <Set>
    <div style={{position: "absolute", top: 200, left: 89, fontSize: 94, fontWeight: 800, letterSpacing: -5, lineHeight: 1.23}}>问供应商，<br/>问到这一步。</div>
    <div style={{position: "absolute", top: 553 - move(f, 0, 110, 0, 30), left: 338, transform: `scale(.91) rotate(${move(f, 0, 145, -3, 4)}deg)`, opacity: 1-evidence*.5}}><Mat width={680} tilt={32} angle={-20}/></div>
    <div style={{position: "absolute", top: 857 + move(f, 0, 90, 60, 0), left: 83, opacity: 1-evidence*.6}}><Carton width={680} opening={move(f, 0, 60, 0.25, 1)}/></div>
    <div style={{position: "absolute", top: 620, left: 92, transform: `translateX(${move(f, 0, 19, -55, 0)}px)`, opacity: move(f, 0, 10, 0, 1)}}><div style={{fontSize: 51, fontWeight: 750}}>实物多大？</div><div style={{marginTop: 19, width: 144, height: 4, background: ink}}/></div>
    <div style={{position: "absolute", top: 1196, left: 581, opacity: move(f, 48, 65, 0, 1), transform: `translateY(${move(f, 48, 72, 35, 0)}px)`}}><div style={{width: 152, height: 4, background: ink, marginBottom: 18}}/><div style={{fontSize: 49, fontWeight: 750}}>包装多大？</div></div>
    <div style={{position: "absolute", top: 796, left: 90, right: 119, background: ink, color: "#fffef0", padding: "41px 39px", transform: `translateY(${(1-evidence)*110}px) rotate(-3deg)`, opacity: evidence, boxShadow: "0 30px 70px #0a2b3440"}}>
      <div style={{fontSize: 36, color: "#c6d0b9", marginBottom: 12}}>再要一份依据</div><div style={{fontSize: 72, fontWeight: 750}}>请给<span style={{color: coral}}>实测图。</span></div>
    </div>
    <Caption>{f < 108 ? "实物和包装，分开问清。" : "不靠猜，拿实测图核对。"}</Caption>
  </Set>;
};
