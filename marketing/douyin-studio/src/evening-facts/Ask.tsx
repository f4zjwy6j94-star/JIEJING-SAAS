import React from "react";
import {interpolate,useCurrentFrame} from "remotion";
import {Stage,Heading,cream,ink,lime,ease} from "./Shared";

export const EveningAsk: React.FC = () => {
  const f=useCurrentFrame();
  return <Stage dark>
    <Heading>这句直接问<br/><span style={{color:lime}}>供应商。</span></Heading>
    <div style={{position:"absolute",left:115,top:560,width:775,minHeight:820,padding:"70px 54px",background:cream,color:ink,borderRadius:44,boxShadow:"0 45px 100px #0005",translate:`0px ${interpolate(f,[0,30],[90,0],ease)}px`}}>
      <div style={{fontSize:34,color:"#6a7d70",borderBottom:"1px solid #b5beae",paddingBottom:25}}>询问文本</div>
      <div style={{fontSize:57,lineHeight:1.65,marginTop:40,fontWeight:600}}>请分别确认<br/><span style={{background:lime,padding:"3px 9px"}}>实物尺寸</span>和<br/><span style={{background:lime,padding:"3px 9px"}}>包装尺寸</span>，<br/>并提供实测图。</div>
      <div style={{fontSize:38,marginTop:52,paddingTop:28,borderTop:"1px solid #b5beae"}}>附上两份原资料，一起核对</div>
    </div>
  </Stage>;
};
