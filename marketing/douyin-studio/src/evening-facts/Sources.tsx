import React from "react";
import {interpolate,useCurrentFrame} from "remotion";
import {Stage,Heading,cream,ink,lime,ease} from "./Shared";

export const EveningSources: React.FC = () => {
  const f=useCurrentFrame();
  return <Stage dark>
    <Heading>先别选一个<br/><span style={{color:lime}}>填进去。</span></Heading>
    <div style={{position:"absolute",left:132,top:610,width:665,height:510,background:cream,color:ink,padding:52,rotate:`${interpolate(f,[0,40],[-9,-4],ease)}deg`,boxShadow:"0 30px 65px #0003"}}>
      <div style={{fontSize:38,borderBottom:`2px solid ${ink}`,paddingBottom:20}}>保留来源 A · 详情图</div>
      <div style={{fontSize:155,fontWeight:800,marginTop:45}}>11.5 <span style={{fontSize:40}}>cm</span></div>
    </div>
    <div style={{position:"absolute",left:230,top:1045,width:670,height:325,background:lime,color:ink,padding:42,rotate:"4deg",translate:`${interpolate(f,[15,50],[170,0],ease)}px 0px`,boxShadow:"0 25px 50px #0003"}}>
      <div style={{fontSize:38}}>保留来源 B · 参数栏</div>
      <div style={{display:"flex",alignItems:"baseline",gap:25,marginTop:26}}><strong style={{fontSize:128,lineHeight:1}}>20</strong><span style={{fontSize:40}}>cm</span><span style={{fontSize:36,marginLeft:"auto",border:`2px solid ${ink}`,padding:14}}>待核实</span></div>
    </div>
  </Stage>;
};
