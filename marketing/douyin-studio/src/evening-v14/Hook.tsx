import React from "react";
import {useCurrentFrame} from "remotion";
import {Caption, coral, lime, Mat, move, numberFace, Set} from "./Art";

export const V14Hook: React.FC = () => {
  const f = useCurrentFrame();
  return <Set dark>
    <div style={{position: "absolute", top: 205, left: 90, fontSize: 48, letterSpacing: 2}}>上架前，同一个商品</div>
    <div style={{position: "absolute", top: 285, left: 76, fontFamily: numberFace, fontSize: 206, fontWeight: 700, letterSpacing: -13, color: lime, lineHeight: 1.05}}>11.5<span style={{fontSize: 50, letterSpacing: 0}}> cm</span></div>
    <div style={{position: "absolute", top: 520, left: 92, fontSize: 43, color: "#b3c9b9"}}>还是</div>
    <div style={{position: "absolute", top: 578, right: 118, fontFamily: numberFace, fontSize: 232, fontWeight: 700, letterSpacing: -13, lineHeight: 1, color: coral}}>20<span style={{fontSize: 50, letterSpacing: 0}}> cm ?</span></div>
    <div style={{position: "absolute", top: 750 + move(f, 0, 74, 20, -24), left: 134, transform: `scale(${move(f, 0, 74, 1.12, 1.02)})`}}><Mat width={790} angle={move(f, 0, 74, -34, -9)} tilt={move(f, 0, 74, 50, 33)}/></div>
    <div style={{position: "absolute", top: 483, left: 90, width: 276, height: 3, background: lime, transform: `scaleX(${move(f, 3, 24, 0, 1)})`, transformOrigin: "left"}}/>
    <Caption dark>两份资料，对不上。</Caption>
  </Set>;
};
