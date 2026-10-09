import React from "react";
import {interpolate,useCurrentFrame} from "remotion";
import {Stage,Heading,DrainDiagram,ink,ease} from "./Shared";

export const EveningSeparate: React.FC = () => {
  const f=useCurrentFrame();
  return <Stage>
    <Heading>测的是实物，<br/>还是包装？</Heading>
    <div style={{position:"absolute",left:95,top:565,scale:.78,transformOrigin:"top left",translate:`${interpolate(f,[0,45],[80,0],ease)}px 0px`}}><DrainDiagram/></div>
    <div style={{position:"absolute",left:595,top:640,fontSize:72,fontWeight:800}}>实物？</div>
    <svg viewBox="0 0 620 500" style={{position:"absolute",left:225,top:920,width:640,height:510,translate:`${interpolate(f,[10,45],[-90,0],ease)}px 0px`}}>
      <ellipse cx="305" cy="408" rx="232" ry="42" fill={ink} opacity=".10"/>
      <path d="M 80 160 L 320 90 L 550 176 L 316 268 Z" fill="#ddc7a2"/>
      <path d="M 80 160 L 316 268 L 316 450 L 80 337 Z" fill="#af936f"/>
      <path d="M 316 268 L 550 176 L 550 354 L 316 450 Z" fill="#cab28d"/>
      <path d="M 80 160 L 17 80 L 245 15 L 320 90 M 320 90 L 408 23 L 620 95 L 550 176" fill="#ead9bc" stroke="#d0b58b" strokeWidth="2"/>
      <path d="M 320 90 L 316 268 L 316 450" fill="none" stroke="#997f5e" strokeWidth="2"/>
      <text x="400" y="331" fill="#69533c" fontSize="96" fontWeight="700" transform="rotate(-19 400 331)">?</text>
    </svg>
    <div style={{position:"absolute",left:86,top:1200,fontSize:72,fontWeight:800}}>包装？</div>
    <div style={{position:"absolute",left:86,top:1450,fontSize:42,color:"#62776c"}}>两个数字的含义，仍需确认</div>
  </Stage>;
};
