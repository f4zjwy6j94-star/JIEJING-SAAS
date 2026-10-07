import type {CSSProperties, ReactNode} from "react";
import {Audio} from "@remotion/media";
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from "remotion";

// A continuous 16-second opening study. This is explanatory animation, not a SaaS execution recording.
const C={blue:"#2857EC",ink:"#151C2B",paper:"#F5F6FA",line:"#DCE1EC",muted:"#727D92"};
const file=(name:string)=>staticFile(`narrative-v3/${name}`);
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

export function Douyin11NarrativeV3() {
 const f=useCurrentFrame();const join=interpolate(f,[319,396],[0,1],ease);
 const captions:[number,number,string][]=[[3,78,"你有货，也有 eBay 店。"],[82,119,"可上一个新品，"],[122,150,"要查市场，"],[155,185,"写英文，"],[188,226,"还要准备图片。"],[232,310,"事情，全压在自己身上。"],[316,351,"捷境做的，"],[352,395,"就是把这些准备工作，"],[398,460,"放进同一个工作台。"]];
 const caption=captions.find(([start,end])=>f>=start&&f<=end)?.[2]??"";
 return <AbsoluteFill style={{background:C.paper,color:C.ink,fontFamily:'"NarrativeSans", "Noto Sans CJK SC", sans-serif',overflow:"hidden"}}>
  <style>{`@font-face{font-family:NarrativeSans;src:url('${file("narrative-sans.otf")}');font-weight:100 600;}@font-face{font-family:NarrativeSans;src:url('${file("narrative-bold.otf")}');font-weight:700 900;}`}</style>
  <Audio src={file("voice-A-yunxi.mp3")}/>
  <div style={{position:"absolute",left:-140,top:680,width:1320,height:1320,borderRadius:"50%",background:"radial-gradient(ellipse,#DCE6FC90 0%,#EDF1F980 43%,transparent 70%)",scale:interpolate(f,[0,270,360,480],[1,1.13,.93,1.04],ease)}}/>
  <div style={{position:"absolute",left:74,right:74,top:91,display:"flex",alignItems:"center",gap:15}}><Img src={file("brand.svg")} style={{width:53,height:53,borderRadius:13,boxShadow:"0 6px 20px #131B2D12"}}/><span style={{fontSize:37,fontWeight:800,letterSpacing:1}}>捷境</span><span style={{marginLeft:"auto",fontSize:22,color:C.muted}}>开篇方向样片 · 16秒</span></div>
  <div style={{position:"absolute",left:78,top:245,opacity:interpolate(f,[0,9,73,83],[0,1,1,0],ease),translate:`0 ${interpolate(f,[0,24,76,100],[22,0,0,-38],ease)}px`}}><div style={{fontSize:27,color:C.blue,letterSpacing:2,marginBottom:24}}>给正在做跨境的你</div><div style={{fontSize:105,fontWeight:800,lineHeight:1.24,letterSpacing:-4}}>货有了。<br/>店也有了。</div></div>
  <div style={{position:"absolute",left:78,top:259,opacity:interpolate(f,[83,103,299,321],[0,1,1,0],ease),translate:`0 ${interpolate(f,[83,110,299,325],[28,0,0,-26],ease)}px`}}><div style={{fontSize:28,color:C.blue,letterSpacing:2,marginBottom:23}}>上一个新品</div><div style={{fontSize:96,fontWeight:850,lineHeight:1.24,letterSpacing:-3}}>怎么还有<br/><span style={{color:C.blue}}>这么多事？</span></div></div>
  <div style={{position:"absolute",left:78,top:252,opacity:interpolate(f,[322,347],[0,1],ease),translate:`0 ${interpolate(f,[322,356],[30,0],ease)}px`}}><div style={{fontSize:27,color:C.blue,letterSpacing:2,marginBottom:22}}>捷境，把工作接起来</div><div style={{fontSize:96,fontWeight:850,lineHeight:1.24,letterSpacing:-4}}>一个工作台，<br/><span style={{color:C.blue}}>接着做。</span></div></div>
  <div style={{position:"absolute",left:206,top:1225,width:670,height:110,borderRadius:"50%",background:"#3C538133",filter:"blur(30px)",opacity:1-join,scale:interpolate(f,[0,95],[.9,1],ease)}}/>
  <div style={{position:"absolute",left:interpolate(f,[0,91,319,396],[382,448,448,147],ease),top:interpolate(f,[0,91,319,396],[925,1010,1010,1203],ease),scale:interpolate(f,[0,91,319,396],[1.52,.88,.88,.27],ease),transformOrigin:"top left",opacity:1,zIndex:f<319?0:15}}><Cube/></div>
  <div style={{position:"absolute",left:150,top:1345,fontSize:27,color:C.muted,letterSpacing:2,opacity:interpolate(f,[5,24,81,100],[0,1,1,0],ease)}}>自己的商品</div>
  <div style={{position:"absolute",right:110,top:758,width:258,height:151,borderRadius:16,background:"#FFFFFF",boxShadow:"0 15px 50px #21355715",opacity:interpolate(f,[12,34,75,100],[0,1,1,0],ease),translate:`0 ${interpolate(f,[12,34],[35,0],ease)}px`,rotate:"7deg",padding:26}}><div style={{color:C.blue,fontSize:29,fontWeight:700}}>eBay 店铺</div><div style={{height:7,background:"#DBE3F2",width:165,marginTop:20}}/><div style={{height:7,background:"#E8EDF6",width:113,marginTop:12}}/></div>
  <div style={{position:"absolute",left:76,top:689,width:928,height:715,borderRadius:25,border:"2px solid #9CB5FE",background:"#FFFFFFDC",boxShadow:"0 28px 90px #2857EC1C",opacity:join,scale:interpolate(f,[319,396],[1.06,1],ease),transformOrigin:"center center"}}><div style={{height:89,borderBottom:`1px solid ${C.line}`,display:"flex",alignItems:"center",padding:"0 29px",gap:16}}><Img src={file("brand.svg")} style={{width:39,height:39}}/><span style={{fontSize:29,fontWeight:750}}>捷境工作台</span><span style={{fontSize:22,marginLeft:"auto",color:C.muted}}>当前支持 eBay</span></div><div style={{position:"absolute",left:35,top:389,fontSize:33,fontWeight:700}}>围绕同一件商品，继续推进。</div><div style={{position:"absolute",left:35,top:471,height:145,width:847,border:"2px solid #BECFFB",borderRadius:18,padding:"29px 115px",fontSize:32,background:"#F8FAFF"}}>{"帮我准备这款新品的商品页".slice(0,Math.floor(interpolate(f,[399,453],[0,14],ease)))}<span style={{color:C.blue,opacity:f%24<12?1:0}}>│</span><span style={{position:"absolute",bottom:18,left:115,fontSize:20,color:C.muted,opacity:interpolate(f,[366,403],[0,1],ease)}}>从你的目标和真实资料开始</span></div></div>
  <Market style={{left:interpolate(f,[95,119,319,396],[25,87,87,111],ease),top:interpolate(f,[95,119,319,396],[670,673,673,815],ease),scale:interpolate(f,[95,119,319,396],[.91,1,1,.49],ease),rotate:`${interpolate(f,[95,119,319,396],[-12,-6,-6,0],ease)}deg`,opacity:interpolate(f,[95,115],[0,1],ease)}}/>
  <English style={{left:interpolate(f,[143,166,319,396],[684,505,505,408],ease),top:interpolate(f,[143,166,319,396],[863,1012,1012,815],ease),scale:interpolate(f,[143,166,319,396],[.93,.96,.96,.49],ease),rotate:`${interpolate(f,[143,166,319,396],[13,7,7,0],ease)}deg`,opacity:interpolate(f,[143,160],[0,1],ease)}}/>
  <Pictures style={{left:interpolate(f,[183,211,319,396],[-205,71,71,705],ease),top:interpolate(f,[183,211,319,396],[1352,1250,1250,815],ease),scale:interpolate(f,[183,211,319,396],[.72,.81,.81,.49],ease),rotate:`${interpolate(f,[183,211,319,396],[-15,-8,-8,0],ease)}deg`,opacity:interpolate(f,[183,203],[0,1],ease)}}/>
  <svg width="44" height="52" viewBox="0 0 44 52" style={{position:"absolute",left:interpolate(f,[108,130,153,178,195,224,267],[383,383,828,828,394,394,590],ease),top:interpolate(f,[108,130,153,178,195,224,267],[797,797,1151,1151,1365,1365,999],ease),zIndex:20,filter:"drop-shadow(0 3px 5px #1C317840)",opacity:interpolate(f,[106,117,286,315],[0,1,1,0],ease)}}><path d="M5 3L7 42L17 32L25 48L33 44L25 29L40 28Z" fill={C.blue} stroke="white" strokeWidth="3"/></svg>
  <svg width="910" height="130" viewBox="0 0 910 130" style={{position:"absolute",left:95,top:980,opacity:join}}><path d="M137 23V64Q137 88 164 88H730Q760 88 760 64V23M455 23V125" stroke="#7C9DF7" strokeWidth="3" fill="none" strokeDasharray="1040" strokeDashoffset={1040*(1-join)}/><circle cx="455" cy="88" r="8" fill={C.blue}/></svg>
  <div style={{position:"absolute",left:82,right:82,top:1513,fontSize:23,color:C.muted,display:"flex",justifyContent:"space-between"}}><span>工作方式示意</span></div>
  <div style={{position:"absolute",left:80,right:80,top:1610,height:103,display:"flex",alignItems:"center",justifyContent:"center",textAlign:"center",fontSize:39,fontWeight:550,lineHeight:1.5,color:C.ink}}>{caption}</div>
  <div style={{position:"absolute",left:80,right:80,bottom:111,height:2,background:C.line}}><div style={{height:2,background:C.blue,width:`${f/479*100}%`}}/></div><div style={{position:"absolute",right:81,bottom:68,fontSize:19,color:C.muted}}>合成配音试听 · 私人方向评审</div>
 </AbsoluteFill>;
}
