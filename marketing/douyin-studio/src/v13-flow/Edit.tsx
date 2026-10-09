import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig, Interactive} from "remotion";
import {Frame, Product, Pointer, ink, accent, ease} from "./Shared";

export const FlowEdit: React.FC = () => {
 const f=useCurrentFrame(); const {fps}=useVideoConfig();
 const edit=f>=4.2*fps;
 const text=edit?"Foldable Tablet Stand":"Tablet Stand";
 return <Frame>
  <Interactive.Div name="Edit follows generation" style={{position:"absolute",left:84,top:170,fontSize:94,fontWeight:800,lineHeight:1.17,letterSpacing:-4}}>{f<3.6*fps?<>图片与展示，<br/><span style={{color:"#588641"}}>也是同一条流程。</span></>:<>生成以后，<br/><span style={{color:"#588641"}}>还能继续改。</span></>}</Interactive.Div>
  <div style={{position:"absolute",left:84,top:477,width:864,height:595,borderRadius:32,background:f<1.45*fps?"#e7eade":"#d4ddd0",overflow:"hidden",border:"1px solid #ccd3c4"}}>
   <div style={{position:"absolute",left:0,right:0,bottom:0,height:220,background:"#b0c1ab",clipPath:"polygon(0 35%, 100% 0, 100% 100%, 0 100%)",opacity:interpolate(f,[1.35*fps,1.7*fps],[0,1],ease)}}/>
   <div style={{position:"absolute",left:120,top:12,width:620,height:550,translate:`${interpolate(f,[1.35*fps,1.75*fps],[0,18],ease)}px 0px`,rotate:interpolate(f,[1.35*fps,1.75*fps],["0deg","-3deg"],ease),filter:"drop-shadow(0 24px 22px #2a402735)"}}><Product/></div>
   <div style={{position:"absolute",left:27,top:27,background:"#ffffffcc",borderRadius:40,padding:"12px 22px",fontSize:28}}>商品图片</div>
   <div style={{position:"absolute",right:27,top:27,borderRadius:40,background:ink,color:"#fff",padding:"12px 22px",fontSize:28,opacity:interpolate(f,[2.15*fps,2.45*fps],[0,1],ease)}}>视频任务</div>
   <div style={{position:"absolute",left:32,bottom:28,fontSize:33,fontWeight:650,color:ink,opacity:interpolate(f,[2.15*fps,2.45*fps],[0,1],ease)}}>{text}</div>
  </div>
  <div style={{position:"absolute",left:84,top:1110,width:864,minHeight:274,padding:32,boxSizing:"border-box",borderRadius:25,border:edit?"3px solid #7ba359":"2px solid #cfd5c5",background:"#fffdf7"}}>
   <div style={{display:"flex",justifyContent:"space-between",fontSize:28,color:"#6c7c68",marginBottom:23}}><span>编辑标题</span><span>{edit?"预览已更新":"可继续修改"}</span></div>
   <div style={{fontSize:48,fontWeight:650,lineHeight:1.2,display:"inline",background:f>3.6*fps&&f<4.2*fps?accent:"transparent"}}>{text}{f>3.6*fps&&f<5.4*fps?<span style={{fontWeight:400}}>│</span>:null}</div>
  </div>
  {f<2.8*fps?<Pointer x={interpolate(f,[.6*fps,1.35*fps],[850,790],ease)} y={interpolate(f,[.6*fps,1.35*fps],[1050,945],ease)} click={f>1.35*fps&&f<1.7*fps}/>:<Pointer x={interpolate(f,[3*fps,3.6*fps],[810,442],ease)} y={interpolate(f,[3*fps,3.6*fps],[960,1230],ease)} click={f>3.6*fps&&f<3.9*fps}/>}
 </Frame>;
};
