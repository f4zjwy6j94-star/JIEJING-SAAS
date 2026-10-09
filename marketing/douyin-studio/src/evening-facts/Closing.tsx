import React from "react";
import {interpolate,useCurrentFrame} from "remotion";
import {Stage,lime,ease} from "./Shared";

export const EveningClosing: React.FC = () => {
  const f=useCurrentFrame();
  return <Stage dark>
    <div style={{position:"absolute",left:85,top:290,fontSize:92,fontWeight:800,lineHeight:1.32,letterSpacing:-2}}>让 AI 整理内容。<br/><span style={{color:lime}}>让证据决定参数。</span></div>
    <div style={{position:"absolute",left:85,top:810,width:795,fontSize:50,display:"flex",justifyContent:"space-between",borderTop:`3px solid ${lime}`,paddingTop:42,opacity:interpolate(f,[0,30],[0,1],ease)}}><span>资料</span><span style={{color:lime}}>→</span><span>核对</span><span style={{color:lime}}>→</span><span>草稿</span></div>
    <div style={{position:"absolute",left:85,top:1190,fontSize:115,fontWeight:750,letterSpacing:7}}>捷境</div>
    <div style={{position:"absolute",left:85,top:1350,fontSize:40,color:"#c8d6c7"}}>跨境电商的 AI 工作方法</div>
    <div style={{position:"absolute",left:85,top:1470,fontSize:48,color:lime,letterSpacing:2}}>jiejing.shop</div>
  </Stage>;
};
