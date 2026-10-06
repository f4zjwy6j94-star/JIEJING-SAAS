import type {CSSProperties, ReactNode} from "react";
import {Audio} from "@remotion/media";
import {AbsoluteFill, Easing, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";
import {voiceoverDuration, voiceoverSegments as timing} from "./VoiceoverV2Timing";

const C = {paper: "#F3F1EB", white: "#FFFDF8", ink: "#243B34", green: "#376657", sage: "#C6D6C5", gold: "#BC945E", muted: "#76857B", line: "#D9DDD2"};
const sans = '"Noto Sans CJK SC", sans-serif';
const serif = '"Noto Serif CJK SC", serif';
const motion = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const, easing: Easing.bezier(.2,.8,.2,1)};
const file = (name:string) => staticFile(`explainer-v2/${name}`);
const shadow = "0 28px 65px #20392D18, 0 2px 4px #20392D08";
const eyebrow:CSSProperties = {fontSize:27,letterSpacing:3,color:C.green,fontWeight:600};

function Arrow({size=40,color=C.green}:{size?:number;color?:string}) {return <svg width={size} height={size} viewBox="0 0 40 40" fill="none"><path d="M7 20H32M23 11L32 20L23 29" stroke={color} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/></svg>;}
function Icon({kind,size=70,color=C.green}:{kind:string;size?:number;color?:string}) {
 const paths:Record<string,string>={box:"M10 19L32 8L54 19L32 30L10 19ZM10 19V45L32 57L54 45V19M32 30V57M21 14L43 25",chat:"M10 12H54V44H29L15 55V44H10V12ZM20 23H44M20 32H36",sheet:"M16 7H43L53 17V57H16V7ZM42 7V19H53M25 29H43M25 38H43M25 47H36",chart:"M10 10V55H56M22 45V33M34 45V23M46 45V13",check:"M13 32L26 45L53 17",shop:"M10 26H54V56H10V26ZM7 25L13 9H51L57 25M24 56V37H40V56M7 25C7 33 20 33 20 25C20 33 33 33 33 25C33 33 46 33 46 25C46 33 57 33 57 25",search:"M45 43L58 56M49 27A20 20 0 1 1 9 27A20 20 0 1 1 49 27"};
 return <svg width={size} height={size} viewBox="0 0 64 64" fill="none"><path d={paths[kind]??paths.sheet} stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
function Logo({light=false}:{light?:boolean}) {return <div style={{position:"absolute",left:78,top:91,display:"flex",alignItems:"center",gap:17,color:light?C.paper:C.ink}}><Img src={file("brand.svg")} style={{width:55,height:55,borderRadius:14,background:C.white}}/><span style={{fontFamily:serif,fontSize:39,fontWeight:800}}>捷境</span><span style={{fontSize:19,letterSpacing:4,opacity:.5,marginLeft:8}}>JIEJING</span></div>;}
function Stage({children,dark=false,step=""}:{children:ReactNode;dark?:boolean;step?:string}) {
 const f=useCurrentFrame();
 return <AbsoluteFill style={{background:dark?C.ink:C.paper,color:dark?C.paper:C.ink,fontFamily:sans,overflow:"hidden"}}>
  <div style={{position:"absolute",width:1250,height:1250,left:450,top:90,borderRadius:"50%",background:dark?"radial-gradient(circle,#769a7924,transparent 64%)":"radial-gradient(circle,#d8dfce90,transparent 65%)",translate:`${interpolate(f,[0,180],[0,-50],motion)}px 0`}}/>
  <div style={{position:"absolute",left:77,right:100,top:178,height:1,background:dark?"#ffffff20":C.line}}/>
  {children}<Logo light={dark}/>
  <div style={{position:"absolute",right:105,top:112,fontSize:22,color:dark?"#c7d5cc":C.muted,letterSpacing:2}}>{step||"讲清楚 · 从这里开始"}</div>
 </AbsoluteFill>;
}
function Heading({small,children,dark=false}:{small:string;children:ReactNode;dark?:boolean}) {return <div style={{position:"absolute",left:80,right:95,top:261}}><div style={{...eyebrow,color:dark?C.sage:C.green}}>{small}</div><div style={{fontFamily:serif,fontSize:83,lineHeight:1.36,fontWeight:800,letterSpacing:-3,marginTop:24}}>{children}</div></div>;}
function Plate({children,style}:{children:ReactNode;style?:CSSProperties}) {return <div style={{position:"absolute",background:C.white,border:"1px solid #FFFFFF",borderRadius:26,boxShadow:shadow,...style}}>{children}</div>;}
function Photo({style}:{style?:CSSProperties}) {return <div style={{overflow:"hidden",background:"#92918a",...style}}><Img src={file("product-original.jpg")} style={{width:"165%",height:"165%",objectFit:"cover",position:"absolute",left:"-42%",top:"-43%"}}/></div>;}
function Note({children,style}:{children:ReactNode;style?:CSSProperties}) {return <div style={{fontSize:24,color:C.muted,lineHeight:1.65,...style}}>{children}</div>;}

function Opening({fixedFrame}:{fixedFrame?:number}) {
 const frame=useCurrentFrame(),f=fixedFrame??frame;
 return <Stage>
  <Heading small="给正在经营 eBay 店铺的你">每一步，<br/>都要自己盯？</Heading>
  <svg width="930" height="650" style={{position:"absolute",top:733,left:67}} viewBox="0 0 930 650"><path d="M110 515C210 150 775 85 823 400" fill="none" stroke={C.line} strokeWidth="2" strokeDasharray="7 10"/></svg>
  <Plate style={{left:127,top:740,width:474,height:471,padding:42,rotate:`${interpolate(f,[0,70],[-9,-5],motion)}deg`,translate:`0 ${interpolate(f,[0,22],[50,0],motion)}px`}}><div style={eyebrow}>01 / 商品资料</div><Photo style={{position:"absolute",left:36,top:113,width:396,height:254,borderRadius:13}}/><div style={{position:"absolute",bottom:34,fontSize:29,fontWeight:600}}>图片、规格、货源</div></Plate>
  <Plate style={{left:534,top:933,width:383,height:300,padding:35,rotate:"7deg",translate:`0 ${interpolate(f,[9,31],[240,0],motion)}px`}}><Icon kind="sheet"/><div style={{fontSize:38,fontWeight:700,marginTop:15}}>商品页</div><div style={{fontSize:26,color:C.muted,marginTop:13}}>标题 / 描述 / 素材</div></Plate>
  <Plate style={{left:232,top:1274,width:532,height:170,padding:35,display:"flex",alignItems:"center",gap:27,rotate:"-2deg",translate:`0 ${interpolate(f,[24,45],[260,0],motion)}px`}}><Icon kind="chat"/><div><div style={{fontSize:36,fontWeight:700}}>店铺日常</div><div style={{fontSize:25,color:C.muted}}>消息、订单、经营复盘</div></div></Plate>
 </Stage>;
}
function WhatIsIt() {
 const f=useCurrentFrame();
 return <Stage dark>
  <Heading small="一个目标，连接经营中的每一步。" dark>把经营目标，<br/>交给捷境协助。</Heading>
  <div style={{position:"absolute",left:170,top:737,width:637,height:637,borderRadius:"50%",border:"1px solid #c6d6c53a",scale:interpolate(f,[0,45],[.8,1],motion)}}><div style={{position:"absolute",inset:55,borderRadius:"50%",border:"1px solid #c6d6c528"}}/><div style={{position:"absolute",inset:105,borderRadius:"50%",background:"linear-gradient(135deg,#73918170,#233c34)",boxShadow:"inset 0 1px 1px #dbe9dc40, 0 25px 70px #0003",display:"flex",flexDirection:"column",justifyContent:"center",alignItems:"center"}}><Img src={file("brand.svg")} style={{width:106,height:106,borderRadius:26}}/><div style={{fontFamily:serif,fontSize:70,marginTop:25}}>捷境</div><div style={{fontSize:27,marginTop:15,color:C.sage}}>AI 经营工作台</div></div></div>
  <div style={{position:"absolute",left:107,top:783,fontSize:31,background:C.ink,padding:"9px 22px",color:C.sage}}>跨境卖家</div><div style={{position:"absolute",right:137,top:1259,fontSize:31,background:C.ink,padding:"9px 22px",color:C.sage}}>经营协助</div>
  <div style={{position:"absolute",left:80,top:1450,fontSize:26,color:C.sage,display:"flex",gap:35}}><span>市场调研</span><span>商品页与素材</span><span>店铺日常</span></div>
 </Stage>;
}
function Platform() {return <Stage dark><Heading small="当前支持的平台" dark>从 eBay<br/>开始。</Heading><div style={{position:"absolute",left:84,top:809,fontSize:218,letterSpacing:-15,fontWeight:600,color:C.sage}}>eBay<span style={{fontSize:57,letterSpacing:0,marginLeft:30,color:C.paper}}>→</span></div><div style={{position:"absolute",left:90,top:1240,right:140,fontSize:40,lineHeight:1.65,color:C.paper}}>围绕一个经营目标<br/>整理资料，准备下一步。</div></Stage>;}
function Entry() {
 const f=useCurrentFrame();
 return <Stage step="01 / 找到入口"><Heading small="第一次使用">打开官网，<br/>登录或注册。</Heading>
  <Plate style={{left:78,top:641,width:901,height:622,overflow:"hidden",translate:`0 ${interpolate(f,[0,19],[42,0],motion)}px`}}>
   <div style={{height:73,borderBottom:`1px solid ${C.line}`,display:"flex",alignItems:"center",padding:"0 27px",gap:10}}><div style={{width:12,height:12,borderRadius:9,background:C.sage}}/><div style={{width:12,height:12,borderRadius:9,background:C.line}}/><span style={{marginLeft:26,fontSize:28,letterSpacing:1}}>jiejing.shop</span></div>
   <div style={{position:"absolute",top:73,left:0,width:901,height:549,overflow:"hidden"}}><Img src={file(f<69?"home.png":"login.png")} style={f<69?{position:"absolute",width:1200,left:-3,top:-155}:{position:"absolute",width:1660,left:-737,top:-368}}/></div>
  </Plate>
  <div style={{position:"absolute",left:89,top:1346,width:805,display:"flex",alignItems:"center",justifyContent:"space-between",fontSize:31}}><span>官网登录 / 注册</span><Arrow/><span>进入商家向导</span></div>
  <Note style={{position:"absolute",left:89,top:1450}}>官网界面示例 · 登录后按自身情况继续</Note>
 </Stage>;
}
function ChooseEntry() {
 const f=useCurrentFrame();
 const options=[{name:"免费体验",sub:"先了解核心功能",icon:"search"},{name:"有店铺",sub:"从现有经营任务开始",icon:"shop"},{name:"多店铺",sub:"按店铺分别协作",icon:"box"}];
 return <Stage step="01 / 选择入口"><Heading small="按你的经营情况选择">找到自己的<br/>起点。</Heading>
  {options.map((o,i)=>{const focus=(f>=25+i*42&&f<67+i*42);return <Plate key={o.name} style={{left:82,top:660+i*249,width:863,height:203,padding:37,display:"flex",alignItems:"center",gap:31,border:`1px solid ${focus?C.gold:"#fff"}`,translate:`${interpolate(f,[i*8,i*8+20],[50,0],motion)}px 0`}}><Icon kind={o.icon} size={70}/><div><div style={{fontSize:43,fontWeight:700}}>{o.name}</div><div style={{fontSize:28,color:C.muted,marginTop:9}}>{o.sub}</div></div><div style={{marginLeft:"auto"}}><Arrow/></div></Plate>;})}
  <Note style={{position:"absolute",left:91,top:1450}}>选择身份 → 完成向导 → 进入工作台</Note>
 </Stage>;
}
function SetGoal() {
 const f=useCurrentFrame();
 return <Stage step="02 / 说清目标"><Heading small="进入 AI CEO 工作台">从一句<br/>具体的话开始。</Heading>
  <Plate style={{left:78,top:657,width:876,height:208,overflow:"hidden"}}><Img src={file("workspace-start.png")} style={{position:"absolute",width:1210,left:-275,top:-22}}/></Plate>
  <div style={{position:"absolute",left:113,top:1000,color:C.green,fontSize:58,fontFamily:serif,fontWeight:700,translate:`0 ${interpolate(f,[0,25],[30,0],motion)}px`}}>什么商品？<br/><span style={{display:"inline-block",marginTop:35}}>想完成什么任务？</span></div>
  <Note style={{position:"absolute",left:92,top:1450}}>真实界面 · 从经营目标进入对应任务</Note>
 </Stage>;
}
function GoalExample() {
 const f=useCurrentFrame();
 return <Stage step="02 / 说清目标"><Heading small="给目标一个具体对象">“帮我准备<br/>这款商品的商品页。”</Heading>
  <Photo style={{position:"absolute",left:84,top:664,width:399,height:451,borderRadius:26,boxShadow:shadow,rotate:"-3deg"}}/>
  <div style={{position:"absolute",left:544,top:742,fontSize:52,fontFamily:serif,fontWeight:700,lineHeight:1.65}}>咖啡量勺<br/><span style={{fontSize:29,fontFamily:sans,color:C.muted,fontWeight:400}}>明确商品 + 明确任务</span></div>
  <div style={{position:"absolute",left:548,top:965,display:"flex",gap:18,alignItems:"center",fontSize:28,color:C.green}}><span>准备商品页</span><Arrow/></div>
  <Plate style={{left:78,top:1188,width:876,height:169,overflow:"hidden",border:`1px solid ${C.sage}`}}>{f<114?<OffthreadVideo src={file("goal.mp4")} muted style={{position:"absolute",width:1225,left:-297,top:-874}}/>:<Img src={file("workspace-goal.png")} style={{position:"absolute",width:1225,left:-297,top:-874}}/>}</Plate>
  <Note style={{position:"absolute",left:93,top:1427}}>真实输入示范 · 此处未发送任务</Note>
  <div style={{position:"absolute",left:94,top:1522,width:interpolate(f,[0,100],[0,850],motion),height:2,background:C.gold}}/>
 </Stage>;
}
function Facts() {
 const f=useCurrentFrame();
 return <Stage step="03 / 提供资料"><Heading small="让每一步都有依据">真实图片，<br/>真实参数。</Heading>
  <Plate style={{left:81,top:672,width:423,height:615,rotate:"-4deg"}}><Photo style={{position:"absolute",left:22,top:23,width:379,height:430,borderRadius:15}}/><div style={{position:"absolute",left:34,bottom:50,fontSize:35,fontWeight:700}}>原始商品图</div><div style={{position:"absolute",right:28,bottom:57}}><Icon kind="check" size={40}/></div></Plate>
  <Plate style={{left:464,top:809,width:481,height:556,padding:42,rotate:"4deg",translate:`0 ${interpolate(f,[0,30],[100,0],motion)}px`}}><div style={{fontSize:35,fontWeight:700}}>商品资料</div>{["尺寸 / 规格","材质 / 包装","货源 / 实物信息"].map((x,i)=><div key={x} style={{fontSize:31,padding:"25px 0",borderBottom:`1px solid ${C.line}`,color:C.green,opacity:interpolate(f,[i*13,i*13+14],[.2,1],motion)}}>{x}</div>)}<div style={{marginTop:31,color:C.muted,fontSize:25}}>未知项保留待确认</div></Plate>
  <div style={{position:"absolute",left:94,top:1460,fontSize:28,color:C.green}}>调研、文案、素材，都从真实资料出发。</div>
 </Stage>;
}
function ReviewDraft() {
 const f=useCurrentFrame();
 return <Stage step="04 / 核对草稿"><Heading small="对照原资料，逐项看清楚">标题、规格、描述，<br/>由你核对。</Heading>
  <Plate style={{left:80,top:674,width:862,height:555,padding:46}}><div style={{fontSize:25,color:C.muted,letterSpacing:2}}>商品页 / 核对清单</div>{[{label:"标题",desc:"商品是什么，表述是否准确"},{label:"规格",desc:"尺寸、材质与原资料一致"},{label:"描述",desc:"卖点有依据，缺项先补齐"}].map((x,i)=><div key={x.label} style={{display:"flex",gap:32,alignItems:"center",padding:"23px 0",marginTop:15,borderBottom:i<2?`1px solid ${C.line}`:undefined,opacity:interpolate(f,[i*23,i*23+19],[.3,1],motion)}}><span style={{fontFamily:serif,fontSize:51,color:C.gold}}>0{i+1}</span><div><div style={{fontSize:34,fontWeight:700}}>{x.label}</div><div style={{fontSize:27,color:C.muted,marginTop:7}}>{x.desc}</div></div></div>)}</Plate>
  <div style={{position:"absolute",left:92,top:1292,fontSize:37,fontFamily:serif,color:C.green}}>有疑问，先核对；资料缺了，先补齐。</div>
  <Note style={{position:"absolute",left:92,top:1430}}>核对清单示意 · 不代替具体商品预检</Note>
 </Stage>;
}
function Confirm() {
 const f=useCurrentFrame();
 return <Stage dark step="05 / 确认下一步"><Heading small="关键决定，由你掌握。" dark>先完成预检，<br/>再确认是否发布。</Heading>
  <div style={{position:"absolute",left:120,top:725,width:3,height:659,background:"#81998938"}}/>
  {[{name:"核对商品资料",sub:"商品事实与草稿一致"},{name:"完成预检",sub:"按提示处理缺项与条件"},{name:"确认是否发布",sub:"商家作出关键决定"}].map((x,i)=><div key={x.name} style={{position:"absolute",left:84,top:717+i*242,right:140,display:"flex",alignItems:"center",gap:46,translate:`${interpolate(f,[i*14,i*14+23],[40,0],motion)}px 0`}}><div style={{width:76,height:76,borderRadius:"50%",border:`1px solid ${i===2?C.gold:C.sage}`,background:C.ink,display:"flex",alignItems:"center",justifyContent:"center",fontSize:29,color:i===2?C.gold:C.sage}}>0{i+1}</div><div><div style={{fontSize:48,fontWeight:600,color:i===2?"#E6C997":C.paper}}>{x.name}</div><div style={{fontSize:28,color:C.sage,marginTop:17}}>{x.sub}</div></div></div>)}
  <div style={{position:"absolute",left:90,top:1480,fontSize:24,color:C.sage}}>步骤示意 · 发布还需满足店铺授权与套餐条件</div>
 </Stage>;
}
function Ongoing() {
 const f=useCurrentFrame();
 return <Stage step="经营，从这里继续"><Heading small="同一个工作台，继续往下走。">上架准备之后，<br/>还有经营日常。</Heading>
  {[{name:"客服",sub:"准备待审核回复",icon:"chat"},{name:"订单",sub:"协助梳理待办",icon:"box"},{name:"复盘",sub:"整理经营参考",icon:"chart"}].map((x,i)=><Plate key={x.name} style={{left:85+i*30,top:671+i*260,width:809,height:220,padding:35,display:"flex",gap:37,alignItems:"center",rotate:`${i%2?1:-1}deg`,translate:`0 ${interpolate(f,[i*10,i*10+24],[100,0],motion)}px`}}><div style={{width:126,height:126,borderRadius:24,background:"#e8eee3",display:"flex",alignItems:"center",justifyContent:"center"}}><Icon kind={x.icon} size={69}/></div><div><div style={{fontSize:48,fontWeight:700,fontFamily:serif}}>{x.name}</div><div style={{fontSize:29,color:C.muted,marginTop:12}}>{x.sub}</div></div></Plate>)}
 </Stage>;
}
function Closing() {return <Stage dark><div style={{position:"absolute",left:85,top:317,fontSize:29,letterSpacing:4,color:C.sage}}>从一个具体任务开始。</div><div style={{position:"absolute",left:73,top:460,fontFamily:serif,fontSize:205,fontWeight:800,letterSpacing:-9}}>捷境</div><div style={{position:"absolute",left:90,top:776,fontSize:47,lineHeight:1.7}}>跨境电商 AI 经营工作台<br/><span style={{color:C.sage,fontSize:35}}>当前支持 eBay</span></div><div style={{position:"absolute",left:85,right:138,top:1114,height:1,background:"#d0dfce42"}}/><div style={{position:"absolute",left:91,top:1187,fontSize:73,letterSpacing:1,color:"#e6c997"}}>jiejing.shop</div><div style={{position:"absolute",left:94,top:1365,fontSize:32,color:C.sage}}>了解捷境 · 开始你的第一个任务</div><div style={{position:"absolute",left:94,top:1504,fontSize:22,color:"#b2c2b6"}}>AI 合成配音 · 私人审看版</div></Stage>;}

function Captions() {
 const f=useCurrentFrame();
 const seg=timing.find(s=>f>=s.voice_start_frame&&f<=s.voice_end_frame+6);
 if(!seg)return null;
 const parts=seg.text.split(/(?<=[，。？：])/).filter(Boolean);const lines:string[]=[];
 for(const part of parts){if(lines.length&&(lines[lines.length-1]+part).length<=20)lines[lines.length-1]+=part;else lines.push(part);}
 return <div style={{position:"absolute",left:60,right:98,bottom:176,display:"flex",flexDirection:"column",alignItems:"center",gap:5,pointerEvents:"none"}}>{lines.map((line,i)=><div key={i} style={{background:"#172B24F2",color:"#FFFDF7",border:"1px solid #D8E7D02B",padding:"9px 24px 13px",fontFamily:sans,fontSize:37,lineHeight:1.5,fontWeight:500,borderRadius:8,boxShadow:"0 5px 15px #172B2414"}}>{line}</div>)}</div>;
}
export function Douyin11VoiceoverV2() {return <AbsoluteFill>
 <Sequence durationInFrames={117} name="开头 · 卖家的任务"><Opening/></Sequence>
 <Sequence from={117} durationInFrames={162} name="捷境是什么"><WhatIsIt/></Sequence>
 <Sequence from={279} durationInFrames={70} name="当前支持eBay"><Platform/></Sequence>
 <Sequence from={349} durationInFrames={139} name="01 打开官网"><Entry/></Sequence>
 <Sequence from={488} durationInFrames={174} name="01 选择入口"><ChooseEntry/></Sequence>
 <Sequence from={662} durationInFrames={109} name="02 工作台目标"><SetGoal/></Sequence>
 <Sequence from={771} durationInFrames={131} name="02 输入示例"><GoalExample/></Sequence>
 <Sequence from={902} durationInFrames={175} name="03 商品资料"><Facts/></Sequence>
 <Sequence from={1077} durationInFrames={153} name="04 核对草稿"><ReviewDraft/></Sequence>
 <Sequence from={1230} durationInFrames={146} name="05 商家确认"><Confirm/></Sequence>
 <Sequence from={1376} durationInFrames={140} name="经营协助"><Ongoing/></Sequence>
 <Sequence from={1516} durationInFrames={127} name="了解入口"><Closing/></Sequence>
 <Audio src={file("soundtrack.wav")}/><Captions/>
 <div style={{position:"absolute",left:80,bottom:113,width:(850*useCurrentFrame())/voiceoverDuration,height:3,background:C.gold,opacity:.7}}/>
 </AbsoluteFill>;}
export function Douyin11VoiceoverCover() {return <Opening fixedFrame={80}/>;}
