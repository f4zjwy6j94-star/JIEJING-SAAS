import type {CSSProperties, ReactNode} from "react";
import {Audio} from "@remotion/media";
import {AbsoluteFill, Easing, Freeze, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";

// One continuous narration track drives five sustained visual chapters. Explanatory visuals are labeled.
import {continuousTiming as timing} from "./ContinuousV4Timing";

const C={blue:"#2857EC",ink:"#151C2B",paper:"#F5F6FA",line:"#DCE1EC",muted:"#727D92"};
const file=(name:string)=>staticFile(`continuous-v4/${name}`);
const ease={extrapolateLeft:"clamp" as const,extrapolateRight:"clamp" as const,easing:Easing.bezier(.22,1,.36,1)};

function Cube({small=false}:{small?:boolean}) {
 const f=useCurrentFrame();const size=small?68:238;
 const face:CSSProperties={position:"absolute",width:size,height:size,backfaceVisibility:"hidden",border:"1px solid #19284918"};
 return <div style={{width:size,height:size,perspective:1100}}><div style={{position:"relative",width:size,height:size,transformStyle:"preserve-3d",transform:`rotateX(-19deg) rotateY(${interpolate(f,[0,100,280,370,480],[-33,-15,12,-27,-22],ease)}deg)`}}>
  <div style={{...face,background:"linear-gradient(130deg,#FFFFFF,#DFE5EF)",transform:`translateZ(${size/2}px)`}}><div style={{position:"absolute",left:"13%",top:0,width:"21%",height:"100%",background:C.blue}}/><div style={{position:"absolute",left:"45%",top:"29%",fontSize:small?15:45,fontWeight:800}}>新品</div><div style={{position:"absolute",left:"45%",top:"57%",height:4,width:"34%",background:"#AAB4C5"}}/><div style={{position:"absolute",left:"45%",top:"64%",height:4,width:"21%",background:"#C0C8D6"}}/></div>
  <div style={{...face,background:"linear-gradient(130deg,#CAD3E4,#A1AEC3)",transform:`rotateY(90deg) translateZ(${size/2}px)`}}/>
  <div style={{...face,background:"linear-gradient(130deg,#EEF1F8,#C8D2E3)",transform:`rotateY(-90deg) translateZ(${size/2}px)`}}/>
  <div style={{...face,background:"#FFFFFF",transform:`rotateX(90deg) translateZ(${size/2}px)`}}><div style={{position:"absolute",left:"13%",width:"21%",height:"100%",background:"#7395FA"}}/></div>
 </div></div>;
}

function Window({name,children,style,active=false}:{name:string;children:ReactNode;style:CSSProperties;active?:boolean}) {
 return <div style={{position:"absolute",width:530,height:325,background:"#FFFFFF",borderRadius:20,border:`2px solid ${active?"#6E8FFB":C.line}`,boxShadow:"0 25px 70px #25375623,0 2px 7px #23396312",overflow:"hidden",transformOrigin:"top left",...style}}>
  <div style={{height:65,borderBottom:`1px solid ${C.line}`,background:"#F9FAFD",display:"flex",alignItems:"center",padding:"0 22px",gap:8}}><span style={{width:10,height:10,borderRadius:9,background:"#CDD4E1"}}/><span style={{width:10,height:10,borderRadius:9,background:"#DDE3ED"}}/><span style={{width:10,height:10,borderRadius:9,background:"#E4E9F2"}}/><span style={{marginLeft:16,fontSize:26,fontWeight:600}}>{name}</span></div>
  {children}
 </div>;
}

function Market({style}:{style:CSSProperties}) {
 const f=useCurrentFrame();return <Window name="查市场" style={style} active={f>110&&f<156}>
  <div style={{margin:"20px 24px",height:52,border:`1px solid ${C.line}`,borderRadius:9,display:"flex",alignItems:"center",padding:"0 16px",color:C.muted,fontSize:23}}><svg width="24" height="24" viewBox="0 0 24 24" style={{marginRight:12}}><circle cx="10" cy="10" r="6" fill="none" stroke={C.blue} strokeWidth="2"/><path d="M15 15L22 22" stroke={C.blue} strokeWidth="2"/></svg>{"coffee scoop".slice(0,Math.floor(interpolate(f,[105,150],[0,12],ease)))}</div>
  {[0,1,2].map(i=><div key={i} style={{margin:"13px 25px",display:"flex",gap:15,opacity:interpolate(f,[130+i*6,145+i*6],[.1,1],ease)}}><div style={{width:27,height:27,background:i===0?"#DFE7FE":"#EEF1F6",borderRadius:5}}/><div style={{height:8,width:310-i*39,background:i===0?"#8AA6FB":"#D2DAE8",marginTop:10,borderRadius:5}}/></div>)}
 </Window>;
}
function English({style}:{style:CSSProperties}) {
 const f=useCurrentFrame();return <Window name="写英文" style={style} active={f>157&&f<190}><div style={{padding:28}}><div style={{fontSize:34,fontWeight:700,color:C.blue}}>{"Product title".slice(0,Math.floor(interpolate(f,[150,183],[0,13],ease)))}<span style={{opacity:f%24<12?1:0,color:C.blue}}>│</span></div><div style={{fontSize:18,color:C.muted,marginTop:8,letterSpacing:2}}>DESCRIPTION</div>{[365,410,280].map((w,i)=><div key={w} style={{height:11,width:interpolate(f,[169+i*5,190+i*5],[0,w],ease),background:"#DBE2ED",borderRadius:4,marginTop:19}}/>)}</div></Window>;
}
function Pictures({style}:{style:CSSProperties}) {
 const f=useCurrentFrame();return <Window name="准备图片" style={style} active={f>192&&f<235}><div style={{display:"flex",gap:15,padding:25}}>{[0,1,2].map(i=><div key={i} style={{width:144,height:180,borderRadius:11,background:i===0?"#E9EFFD":"#F0F3F8",display:"flex",alignItems:"center",justifyContent:"center",opacity:interpolate(f,[193+i*9,211+i*9],[0,1],ease),translate:`0 ${interpolate(f,[193+i*9,215+i*9],[36,0],ease)}px`}}><Cube small/></div>)}</div></Window>;
}

const cuts={goal:timing.anchors.goal+12,confirm:timing.anchors.confirm+12,roadmap:timing.anchors.roadmap+10,cta:timing.anchors.cta+8};

function Heading({small,children,dark=false}:{small:string;children:ReactNode;dark?:boolean}) {
 return <div style={{position:"absolute",left:80,right:80,top:252}}><div style={{fontSize:27,color:dark?"#A9BDFB":C.blue,letterSpacing:2,marginBottom:27}}>{small}</div><div style={{fontSize:91,fontWeight:800,lineHeight:1.24,letterSpacing:-4,color:dark?"#FFFFFF":C.ink}}>{children}</div></div>;
}

function Intro() {
 const f=useCurrentFrame();const merge=interpolate(f,[timing.anchors.workspace,cuts.goal-20],[0,1],ease);
 return <AbsoluteFill>
  <div style={{opacity:interpolate(f,[timing.anchors.workspace-12,timing.anchors.workspace],[1,0],ease)}}><Heading small="一件新品，背后是一串准备工作">上个新品，<br/><span style={{color:C.blue}}>事情总做不完？</span></Heading></div>
  <div style={{opacity:interpolate(f,[timing.anchors.workspace+1,timing.anchors.workspace+19],[0,1],ease)}}><Heading small="捷境 · 跨境电商 AI 经营工作台">把分散的工作，<br/><span style={{color:C.blue}}>接在一起。</span></Heading></div>
  <div style={{position:"absolute",left:340,top:1002,scale:1.1-merge*.57,transformOrigin:"top left",translate:`${-175*merge}px ${165*merge}px`,opacity:1-merge}}><Cube/></div>
  <div style={{position:"absolute",left:76,top:696,width:928,height:737,background:"#FFFFFFEA",border:"2px solid #B5C7FA",borderRadius:26,boxShadow:"0 22px 65px #2649821A",opacity:merge}}><div style={{height:83,borderBottom:`1px solid ${C.line}`,display:"flex",alignItems:"center",padding:"0 30px",fontSize:31,fontWeight:750,gap:17}}><Img src={file("brand.svg")} style={{width:39,height:39}}/>捷境工作台</div><div style={{position:"absolute",left:38,right:38,top:434,fontSize:39,fontWeight:750}}>从商品出发，围绕目标继续做。</div><div style={{position:"absolute",left:38,right:38,top:543,fontSize:29,color:C.muted}}>调研、商品页与素材，在同一处衔接。</div></div>
  <Freeze frame={Math.min(f*2,300)}><Market style={{left:87+24*merge,top:690+142*merge,scale:1-.51*merge,rotate:`${-6+6*merge}deg`,opacity:interpolate(f,[20,40],[0,1],ease)}}/></Freeze>
  <Freeze frame={Math.min(f*2,300)}><English style={{left:508-100*merge,top:1030-198*merge,scale:.95-.46*merge,rotate:`${7-7*merge}deg`,opacity:interpolate(f,[57,79],[0,1],ease)}}/></Freeze>
  <Freeze frame={Math.min(f*2,300)}><Pictures style={{left:76+629*merge,top:1255-423*merge,scale:.79-.30*merge,rotate:`${-7+7*merge}deg`,opacity:interpolate(f,[86,111],[0,1],ease)}}/></Freeze>
  <svg width="900" height="120" viewBox="0 0 900 120" style={{position:"absolute",left:100,top:1010,opacity:merge}}><path d="M138 0V40Q138 69 166 69H734Q760 69 760 40V0M455 0V111" stroke="#7295F5" strokeWidth="4" fill="none" strokeDasharray="1000" strokeDashoffset={1000*(1-merge)}/><circle cx="455" cy="69" r="8" fill={C.blue}/></svg>
  <div style={{position:"absolute",left:83,top:1538,fontSize:24,color:C.muted}}>工作方式示意</div>
 </AbsoluteFill>;
}

function GoalAndPreparation() {
 const f=useCurrentFrame();const prepare=timing.anchors.prepare-cuts.goal;const revise=timing.anchors.revise-cuts.goal;
 return <AbsoluteFill>
  <Heading small="你给目标与真实资料">用中文说明白，<br/><span style={{color:C.blue}}>事情接着做。</span></Heading>
  <div style={{position:"absolute",left:80,top:660,width:920,height:282,background:"#FFFFFF",borderRadius:24,border:`1px solid ${C.line}`,boxShadow:"0 20px 60px #253D7020",overflow:"hidden"}}><div style={{position:"absolute",left:27,top:22,fontSize:25,fontWeight:650}}>例如：准备咖啡量勺的商品页</div><div style={{position:"absolute",left:21,top:77,width:876,height:169,overflow:"hidden",borderRadius:12,border:"1px solid #D3DEF7"}}>{f<114?<OffthreadVideo src={file("goal.mp4")} muted style={{position:"absolute",width:1225,left:-297,top:-874}}/>:<Img src={file("workspace-goal.png")} style={{position:"absolute",width:1225,left:-297,top:-874}}/>}</div></div>
  <div style={{position:"absolute",left:88,top:959,fontSize:21,color:C.muted}}>本地输入演示 · 未发送任务</div>
  <div style={{position:"absolute",left:114,top:1120,scale:.58,transformOrigin:"top left"}}><Cube/></div>
  <div style={{position:"absolute",left:85,top:1327,fontSize:28,fontWeight:700}}>同一件商品</div>
  <div style={{position:"absolute",left:81,top:1380,fontSize:24,color:C.muted,lineHeight:1.55}}>真实图片<br/>商品参数</div>
  <svg width="330" height="460" viewBox="0 0 330 460" style={{position:"absolute",left:250,top:1015}}><path d="M10 226H82Q120 226 120 190V61Q120 32 158 32H314M120 190V226H314M120 226V390Q120 419 158 419H314" stroke="#A7BDF8" strokeWidth="3" fill="none" strokeDasharray="1100" strokeDashoffset={1100*(1-interpolate(f,[prepare-30,prepare+70],[0,1],ease))}/></svg>
  <div style={{position:"absolute",left:556,top:1004,width:425}}>
   <div style={{height:146,padding:"29px 25px",borderBottom:`1px solid ${C.line}`,opacity:interpolate(f,[prepare-12,prepare+18],[.18,1],ease),translate:`${interpolate(f,[prepare-12,prepare+18],[24,0],ease)}px 0`}}><div style={{fontSize:38,fontWeight:750}}>市场调研</div><div style={{fontSize:22,color:C.muted,marginTop:8}}>先了解经营方向</div></div>
   <div style={{height:146,padding:"29px 25px",borderBottom:`1px solid ${C.line}`,opacity:interpolate(f,[prepare+14,prepare+44],[.18,1],ease),translate:`${interpolate(f,[prepare+14,prepare+44],[24,0],ease)}px 0`}}><div style={{fontSize:38,fontWeight:750}}>商品页草稿</div><div style={{fontSize:22,color:C.muted,marginTop:8}}>标题、规格与描述</div></div>
   <div style={{height:146,padding:"29px 25px",opacity:interpolate(f,[prepare+38,prepare+68],[.18,1],ease),translate:`${interpolate(f,[prepare+38,prepare+68],[24,0],ease)}px 0`}}><div style={{fontSize:38,fontWeight:750}}>素材准备</div><div style={{fontSize:22,color:C.muted,marginTop:8}}>围绕真实商品资料</div></div>
  </div>
  <div style={{position:"absolute",left:360,top:1455,display:"flex",gap:18,opacity:interpolate(f,[revise-5,revise+14],[0,1],ease),translate:`0 ${interpolate(f,[revise-5,revise+20],[25,0],ease)}px`}}><span style={{fontSize:26,color:C.blue,padding:"13px 20px",border:"1px solid #AAC0FB",borderRadius:9,background:"#FFFFFF"}}>补资料</span><span style={{fontSize:26,color:C.blue,padding:"13px 20px",border:"1px solid #AAC0FB",borderRadius:9,background:"#FFFFFF"}}>改内容</span><span style={{fontSize:20,color:C.muted,alignSelf:"center"}}>准备流程示意</span></div>
 </AbsoluteFill>;
}

function ConfirmAndContinue() {
 const f=useCurrentFrame();const assist=timing.anchors.assist-cuts.confirm;const route=interpolate(f,[0,108],[0,1],ease);
 return <AbsoluteFill>
  <Heading small="从准备，到受控执行">关键决定，<br/><span style={{color:C.blue}}>由你来定。</span></Heading>
  <div style={{position:"absolute",left:81,top:694,width:918,height:521,border:"2px solid #C3D1F4",borderRadius:27,background:"#FFFFFF",boxShadow:"0 25px 60px #233E7016"}}>
   <div style={{position:"absolute",left:35,top:31,fontSize:27,fontWeight:700}}>发布前的下一步</div>
   <svg width="830" height="165" viewBox="0 0 830 165" style={{position:"absolute",left:39,top:132}}><path d="M82 74H740" stroke="#DAE2F1" strokeWidth="4"/><path d="M82 74H410" stroke={C.blue} strokeWidth="5" strokeDasharray="328" strokeDashoffset={328*(1-route)}/><circle cx="82" cy="74" r="35" fill="#EDF2FF" stroke="#92ACF6" strokeWidth="2"/><circle cx="410" cy="74" r="35" fill={C.blue}/><circle cx="740" cy="74" r="35" fill="white" stroke="#A4B9EB" strokeWidth="2"/><text x="82" y="85" textAnchor="middle" fontSize="26" fill={C.blue}>1</text><text x="410" y="85" textAnchor="middle" fontSize="26" fill="white">2</text><text x="740" y="85" textAnchor="middle" fontSize="26" fill={C.blue}>3</text></svg>
   <div style={{position:"absolute",left:36,right:36,top:314,display:"flex",justifyContent:"space-between",fontSize:32,fontWeight:700}}><span>检查条件</span><span style={{color:C.blue}}>商家确认</span><span>eBay 店铺</span></div>
   <div style={{position:"absolute",left:36,bottom:32,fontSize:22,color:C.muted}}>流程示意 · 经确认后调用平台接口，不代表本片实际刊登</div>
  </div>
  <div style={{position:"absolute",left:85,top:1290,fontSize:30,fontWeight:700,opacity:interpolate(f,[assist-15,assist+10],[0,1],ease)}}>经营工作，还可以继续衔接。</div>
  <div style={{position:"absolute",left:85,top:1370,display:"flex",gap:24,opacity:interpolate(f,[assist,assist+25],[0,1],ease),translate:`0 ${interpolate(f,[assist,assist+25],[25,0],ease)}px`}}>{["客服","订单","经营复盘"].map(label=><div key={label} style={{width:278,borderTop:`3px solid ${C.blue}`,paddingTop:24,fontSize:38,fontWeight:750}}>{label}</div>)}</div>
 </AbsoluteFill>;
}

function PlatformRoadmap() {
 const f=useCurrentFrame();const reveal=timing.anchors.planned-cuts.roadmap;
 return <AbsoluteFill style={{background:C.ink,color:"#FFFFFF"}}>
  <Heading small="平台方向，说清现在与下一步" dark>从 eBay 起步，<br/><span style={{color:"#96B2FF"}}>逐步拓展。</span></Heading>
  <div style={{position:"absolute",left:85,top:696,width:910,height:235,border:"1px solid #5C83EB",borderRadius:23,background:"#213157",padding:"33px 39px"}}><div style={{fontSize:25,color:"#B9C9F8"}}>目前支持</div><div style={{fontSize:75,fontWeight:800,letterSpacing:-3,marginTop:6}}>eBay</div></div>
  <div style={{position:"absolute",left:130,top:932,height:82,width:2,background:"#778AAA"}}/>
  <div style={{position:"absolute",left:85,top:1038,width:910,opacity:interpolate(f,[reveal-7,reveal+13],[0,1],ease)}}><div style={{fontSize:28,color:"#AABDF0",marginBottom:27}}>后续接入计划</div><div style={{display:"flex",gap:19}}>{["亚马逊","TikTok Shop","抖音"].map((label,i)=><div key={label} style={{height:149,width:289,border:"1px dashed #6C7D9D",borderRadius:16,padding:"45px 10px",textAlign:"center",fontSize:label==='TikTok Shop'?34:42,fontWeight:750,translate:`0 ${interpolate(f,[reveal+i*8,reveal+i*8+19],[25,0],ease)}px`}}>{label}</div>)}</div><div style={{marginTop:28,fontSize:24,color:"#B3BDD1"}}>拓展规划 · 尚未接入</div></div>
  <div style={{position:"absolute",left:86,top:1435,fontSize:31,color:"#D1DAEF"}}>朝着覆盖更多电商平台的方向发展。</div>
 </AbsoluteFill>;
}

function Ending() {
 const f=useCurrentFrame();return <AbsoluteFill>
  <Heading small="捷境 · 跨境电商 AI 经营工作台">从一件商品，<br/><span style={{color:C.blue}}>一个任务开始。</span></Heading>
  <div style={{position:"absolute",left:151,top:846,scale:.95,transformOrigin:"top left",translate:`0 ${interpolate(f,[0,90],[8,0],ease)}px`}}><Cube/></div>
  <div style={{position:"absolute",left:496,top:867,fontSize:89,fontWeight:800,letterSpacing:-4}}>捷境</div>
  <div style={{position:"absolute",left:495,top:1005,fontSize:31,color:C.muted}}>目标清楚，工作接着做。</div>
  <div style={{position:"absolute",left:84,top:1259,width:912,borderTop:`2px solid ${C.ink}`,paddingTop:36,display:"flex",alignItems:"center",justifyContent:"space-between"}}><span style={{fontSize:66,fontWeight:750,letterSpacing:-2}}>jiejing.shop</span><svg width="75" height="55" viewBox="0 0 75 55" style={{translate:`${interpolate(f,[0,90],[0,8],ease)}px 0`}}><path d="M2 27H69M46 5L70 27L46 49" stroke={C.blue} strokeWidth="5" fill="none"/></svg></div>
  <div style={{position:"absolute",left:87,top:1414,fontSize:27,color:C.muted}}>目前先支持 eBay</div>
 </AbsoluteFill>;
}

export function Douyin11ContinuousV4() {
 const f=useCurrentFrame();const dark=f>=cuts.roadmap&&f<cuts.cta;const caption=(timing.captions.find(x=>f>=x.from&&f<x.to)?.text??"").replace("后续计划逐步接入亚马逊、TikTok Shop、抖音等平台，","后续计划逐步接入亚马逊、\nTikTok Shop、抖音等平台，");
 return <AbsoluteFill style={{background:C.paper,color:C.ink,fontFamily:'"ContinuousSans", "Noto Sans CJK SC", sans-serif',overflow:"hidden"}}>
  <style>{`@font-face{font-family:ContinuousSans;src:url('${file("sans.otf")}');font-weight:100 600;}@font-face{font-family:ContinuousSans;src:url('${file("bold.otf")}');font-weight:700 900;}`}</style>
  <Audio src={file("voice-continuous.wav")}/>
  <Sequence name="商家处境与捷境作用" durationInFrames={cuts.goal}><Intro/></Sequence>
  <Sequence name="给目标和资料，继续准备与修改" from={cuts.goal} durationInFrames={cuts.confirm-cuts.goal}><GoalAndPreparation/></Sequence>
  <Sequence name="商家确认与后续经营" from={cuts.confirm} durationInFrames={cuts.roadmap-cuts.confirm}><ConfirmAndContinue/></Sequence>
  <Sequence name="当前能力与未来平台计划" from={cuts.roadmap} durationInFrames={cuts.cta-cuts.roadmap}><PlatformRoadmap/></Sequence>
  <Sequence name="从具体任务开始" from={cuts.cta} durationInFrames={timing.duration_frames-cuts.cta}><Ending/></Sequence>
  <div style={{position:"absolute",left:78,right:83,top:91,display:"flex",alignItems:"center",gap:15,color:dark?"#FFFFFF":C.ink}}><Img src={file("brand.svg")} style={{width:52,height:52,borderRadius:13}}/><span style={{fontSize:36,fontWeight:800}}>捷境</span><span style={{marginLeft:"auto",fontSize:22,color:dark?"#AAB8D0":C.muted}}>项目讲解 · 私人审看版</span></div>
  <div style={{position:"absolute",left:86,right:86,top:1610,minHeight:127,display:"flex",justifyContent:"center",alignItems:"center",fontSize:37,fontWeight:500,lineHeight:1.58,textAlign:"center",whiteSpace:"pre-line",color:dark?"#FFFFFF":C.ink}}>{caption}</div>
  <div style={{position:"absolute",left:82,right:82,bottom:110,height:2,background:dark?"#34415D":C.line}}><div style={{height:2,background:dark?"#99B5FF":C.blue,width:`${f/(timing.duration_frames-1)*100}%`}}/></div>
  <div style={{position:"absolute",right:84,bottom:68,fontSize:19,color:dark?"#93A3C2":C.muted}}>合成配音 · 尚未公开发布</div>
 </AbsoluteFill>;
}
