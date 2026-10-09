import React from "react";
import {interpolate,useCurrentFrame} from "remotion";
import {Stage,Heading,ink,lime,ease} from "./Shared";

export const EveningResolve: React.FC = () => {
  const f=useCurrentFrame();
  return <Stage>
    <Heading>核对之后，<br/>再完善草稿。</Heading>
    <div style={{position:"absolute",left:120,top:625,width:755,height:720,padding:56,background:"#fffefa",boxShadow:"0 36px 75px #193a3226",rotate:`${interpolate(f,[0,50],[-5,0],ease)}deg`}}>
      <div style={{fontSize:34,color:"#6a7d70"}}>商品资料核对清单</div>
      <div style={{fontSize:51,fontWeight:750,marginTop:54,paddingBottom:32,borderBottom:`2px solid ${ink}`}}>尺寸：<span style={{color:"#847245"}}>等待依据</span></div>
      <div style={{fontSize:43,marginTop:42,lineHeight:1.9}}>原资料出处<br/>供应商确认<br/>实测图</div>
      <div style={{marginTop:35,background:lime,padding:"18px 20px",fontSize:38}}>信息确认后，再填写参数</div>
    </div>
    <div style={{position:"absolute",left:86,top:1450,fontSize:44,fontWeight:700}}>先核实，再表达。</div>
  </Stage>;
};
