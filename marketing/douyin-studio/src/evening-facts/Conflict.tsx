import React from "react";
import {interpolate,useCurrentFrame} from "remotion";
import {Stage,Heading,DrainDiagram,Ruler,ink,lime,ease} from "./Shared";

export const EveningConflict: React.FC = () => {
  const f=useCurrentFrame();
  return <Stage>
    <Heading>同一个商品，<br/>两个尺寸？</Heading>
    <div style={{position:"absolute",left:152,top:540,rotate:`${interpolate(f,[0,90],[-6,0],ease)}deg`,scale:interpolate(f,[0,80],[1.05,1],ease)}}><DrainDiagram scale={1.15}/></div>
    <div style={{position:"absolute",left:85,top:1030,fontSize:158,fontWeight:850,letterSpacing:-8,translate:`${interpolate(f,[0,20],[-75,0],ease)}px 0px`}}>11.5<span style={{fontSize:46,letterSpacing:0}}> cm</span></div>
    <div style={{position:"absolute",left:85,top:985,fontSize:36,color:"#60786d"}}>详情图</div>
    <div style={{position:"absolute",left:590,top:1000,rotate:"7deg",background:ink,color:lime,padding:"26px 42px 38px",boxShadow:"0 30px 50px #16382f24",translate:`0px ${interpolate(f,[8,28],[110,0],ease)}px`}}><div style={{fontSize:36,letterSpacing:0}}>参数栏</div><div style={{fontSize:160,lineHeight:1.2,fontWeight:850}}>20<span style={{fontSize:38}}> cm</span></div></div>
    <div style={{position:"absolute",left:85,top:1405,rotate:"-2deg"}}><Ruler/></div>
  </Stage>;
};
