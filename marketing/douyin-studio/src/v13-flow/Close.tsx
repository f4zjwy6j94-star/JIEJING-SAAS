import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig, Interactive} from "remotion";
import {Frame, accent, ease} from "./Shared";
export const FlowClose: React.FC = () => {
 const f=useCurrentFrame(); const {fps}=useVideoConfig();
 return <Frame dark>
  <Interactive.Div name="Brand arrives at the end" style={{position:"absolute",left:86,top:340,color:accent,fontSize:60,fontWeight:650,opacity:interpolate(f,[0,.3*fps],[0,1],ease)}}>捷境</Interactive.Div>
  <Interactive.Div name="Single payoff" style={{position:"absolute",left:84,top:486,fontSize:111,fontWeight:800,lineHeight:1.18,letterSpacing:-5,translate:`0px ${interpolate(f,[0,.5*fps],[40,0],ease)}px`}}>少一点来回。<br/>多一点推进。</Interactive.Div>
  <div style={{position:"absolute",left:86,top:920,fontSize:43,lineHeight:1.9,opacity:interpolate(f,[.3*fps,.7*fps],[0,1],ease)}}>当前先支持 eBay<br/><span style={{color:"#becbbc"}}>重要操作，由你确认。</span></div>
  <div style={{position:"absolute",left:86,top:1260,width:780,height:2,background:"#687e63"}}/>
  <div style={{position:"absolute",left:86,top:1320,fontSize:34,color:"#bdcbbb"}}>你卡在写文案，还是做商品图？</div>
 </Frame>;
};
