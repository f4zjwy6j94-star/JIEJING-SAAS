import React from "react";
import {Interactive, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {Frame, Product, Pointer, ink, accent, ease} from "./Shared";

export const FlowIngest: React.FC = () => {
 const f=useCurrentFrame(); const {fps}=useVideoConfig();
 const dock=interpolate(f,[1.4*fps,2.2*fps],[0,1],ease);
 const entered=f>4.1*fps;
 const goal="为 eBay 准备商品内容";
 return <Frame>
  <Interactive.Div name="Result-first hook" style={{position:"absolute",left:84,top:178,fontSize:94,fontWeight:800,lineHeight:1.18,letterSpacing:-4,opacity:interpolate(f,[0,10],[0,1],ease)}}>一张商品图。<br/><span style={{color:"#588641"}}>接下来呢？</span></Interactive.Div>
  <div style={{position:"absolute",left:84,top:495,width:864,height:880,borderRadius:34,background:"#fffdf7",border:"1px solid #d8d9cd",boxShadow:"0 28px 80px #233b2520",opacity:interpolate(f,[1.25*fps,2*fps],[0,1],ease),translate:`0px ${interpolate(f,[1.25*fps,2*fps],[80,0],ease)}px`}}>
   <div style={{height:105,borderBottom:"1px solid #e1e2d7",padding:"26px 34px",boxSizing:"border-box",display:"flex",justifyContent:"space-between",fontSize:34,fontWeight:700}}><span>捷境</span><span style={{fontSize:28,color:"#809087"}}>商品资料</span></div>
   <div style={{position:"absolute",left:34,top:143,width:365,height:360,borderRadius:22,background:"#eceee5",border:"2px dashed #abb6a5"}}/>
   <div style={{position:"absolute",left:434,top:162,fontSize:32,color:"#69766b"}}>资料随商品归位</div>
   <div style={{position:"absolute",left:434,top:229,width:346,height:88,background:accent,borderRadius:15,display:"flex",alignItems:"center",gap:20,paddingLeft:22,fontSize:34,opacity:interpolate(f,[2.65*fps,3.1*fps],[0,1],ease),translate:`${interpolate(f,[2.65*fps,3.1*fps],[95,0],ease)}px 0px`}}><span>↳</span> 商品原图</div>
   <div style={{position:"absolute",left:434,top:340,width:346,height:88,background:"#e4e8de",borderRadius:15,display:"flex",alignItems:"center",gap:20,paddingLeft:22,fontSize:34,opacity:interpolate(f,[3.05*fps,3.5*fps],[0,1],ease),translate:`${interpolate(f,[3.05*fps,3.5*fps],[95,0],ease)}px 0px`}}><span>≡</span> 规格与参数</div>
   <div style={{position:"absolute",left:34,right:34,top:555,opacity:interpolate(f,[3.8*fps,4.2*fps],[0,1],ease)}}>
    <div style={{fontSize:32,marginBottom:23,color:"#657264"}}>告诉捷境，你要做什么</div>
    <div style={{minHeight:130,border:"2px solid #91a682",borderRadius:20,padding:26,fontSize:36,boxSizing:"border-box"}}>{entered?goal.slice(0,Math.floor(interpolate(f,[4.1*fps,5.7*fps],[0,goal.length],ease))):""}<span style={{color:"#54764c"}}>│</span></div>
    <div style={{marginTop:26,marginLeft:"auto",width:240,textAlign:"center",padding:22,borderRadius:16,background:ink,color:"#fff",fontSize:34,scale:interpolate(f,[6*fps,6.2*fps,6.4*fps],[1,.97,1],ease)}}>准备草稿 →</div>
   </div>
  </div>
  <Interactive.Div name="Same product moves into source" style={{position:"absolute",left:interpolate(f,[1.4*fps,2.2*fps],[150,118],ease),top:interpolate(f,[1.4*fps,2.2*fps],[580,638],ease),width:interpolate(f,[1.4*fps,2.2*fps],[740,365],ease),height:interpolate(f,[1.4*fps,2.2*fps],[660,360],ease),rotate:interpolate(f,[0,1.4*fps,2.2*fps],["-7deg","0deg","0deg"],ease),filter:`drop-shadow(0 ${32-dock*20}px 25px #18352d30)`}}><Product/></Interactive.Div>
  {f>5.8*fps&&<Pointer x={interpolate(f,[5.8*fps,6.2*fps],[920,850],ease)} y={interpolate(f,[5.8*fps,6.2*fps],[1420,1250],ease)} click={f>6.15*fps&&f<6.5*fps}/>}
 </Frame>;
};
