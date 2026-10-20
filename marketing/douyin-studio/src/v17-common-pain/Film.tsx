import React from 'react';
import {AbsoluteFill, Audio, interpolate, Sequence, spring, staticFile, useCurrentFrame} from 'remotion';

const ink='#182327', paper='#f1f0e8', lime='#deef88', coral='#ef745c';
const ease=(f:number,a:number,b:number,x=0,y=1)=>interpolate(f,[a,b],[x,y],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
const enter=(f:number,d=0)=>spring({frame:f-d,fps:30,config:{damping:22,stiffness:130,mass:0.8}});
const Words:React.FC<{children:React.ReactNode;top:number;size?:number;color?:string;style?:React.CSSProperties}>=({children,top,size=84,color=ink,style={}})=><div style={{position:'absolute',top,left:92,right:90,fontSize:size,fontWeight:780,letterSpacing:-3,lineHeight:1.2,color,...style}}>{children}</div>;
const Base:React.FC<{dark?:boolean;children:React.ReactNode}>=({dark=false,children})=>{
 const f=useCurrentFrame();
 return <AbsoluteFill style={{background:dark?ink:paper,color:dark?paper:ink,overflow:'hidden',fontFamily:'Microsoft YaHei UI, Microsoft YaHei, sans-serif'}}>
  <AbsoluteFill style={{background:`radial-gradient(ellipse at ${60+Math.sin(f/90)*10}% 55%, ${dark?'#50615b':'#ffffff'} 0%, transparent 65%)`,opacity:.55}}/>
  <div style={{position:'absolute',inset:0,opacity:dark?.1:.13,backgroundImage:`linear-gradient(${dark?'#b7c9b4':'#aaa'} 1px,transparent 1px),linear-gradient(90deg,${dark?'#b7c9b4':'#aaa'} 1px,transparent 1px)`,backgroundSize:'108px 108px',transform:`perspective(900px) rotateX(64deg) scale(2) translateY(${260+f*.3}px)`}}/>
  {children}
 </AbsoluteFill>;
};
const Parcel:React.FC<{size?:number;open?:number;id?:string}>=({size=560,open=0,id='box'})=><svg width={size} height={size} viewBox="0 0 600 600" style={{overflow:'visible'}}>
 <defs><linearGradient id={`${id}a`} x2="1" y2="1"><stop stopColor="#e9d9bd"/><stop offset="1" stopColor="#b69770"/></linearGradient><linearGradient id={`${id}b`}><stop stopColor="#aa8963"/><stop offset="1" stopColor="#d5be9a"/></linearGradient><filter id={`${id}s`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="16"/></filter></defs>
 <ellipse cx="307" cy="506" rx="194" ry="44" fill="#080e0b" opacity=".22" filter={`url(#${id}s)`}/>
 <path d="M102 234 298 130 504 230 306 342Z" fill="#ebddc4"/>
 <path d="M102 234 306 342 306 511 103 403Z" fill={`url(#${id}a)`}/>
 <path d="M306 342 504 230 504 399 306 511Z" fill={`url(#${id}b)`}/>
 <path d="M248 157 292 134 497 232 453 258Z M453 258 497 232 497 397 453 422Z" fill="#e3cfac" opacity=".8"/>
 <g transform={`translate(0 ${-open*45}) rotate(${-open*17} 103 234)`}><path d="M102 234 298 130 221 46 28 151Z" fill="#d6bf99" opacity={open}/></g>
 <g transform={`rotate(${open*13} 504 230)`}><path d="M298 130 504 230 565 153 363 60Z" fill="#eee0c8" opacity={open}/></g>
 <rect x="148" y="321" width="93" height="52" rx="2" fill="#f3eee2" transform="skewY(27) translate(0 -95)"/>
 <g stroke="#8b795e" strokeWidth="4" opacity=".6"><path d="m133 398 75 38 m-75-25 54 29"/></g>
</svg>;
const Sheet:React.FC<{label:string;color?:string;style?:React.CSSProperties}>=({label,color=paper,style})=><div style={{width:340,height:400,background:color,borderRadius:8,padding:40,boxShadow:'0 28px 60px #0002',...style}}><div style={{fontSize:31,fontWeight:700,marginBottom:30,color:ink}}>{label}</div>{[1,.8,.95,.6].map((w,i)=><div key={i} style={{height:10,background:'#485653',opacity:i===0?.5:.15,width:`${w*100}%`,marginBottom:23,borderRadius:8}}/>)}<div style={{width:88,height:88,border:`2px solid #7d898166`,borderRadius:'50%',marginTop:30}}/></div>;

const Hook=()=>{
 const f=useCurrentFrame(),p=enter(f,12);
 return <Base dark>
  <Words top={185} size={91} color={paper}>货有了。</Words>
  <Words top={307} size={79} color={lime}>上架前，还在忙？</Words>
  <svg width="1080" height="1240" style={{position:'absolute',top:520}} viewBox="0 0 1080 1240"><circle cx="540" cy="548" r="351" fill="none" stroke="#e4efb7" strokeWidth="2" opacity=".25"/>{Array.from({length:48},(_,i)=><path key={i} d={`M540 174V${i%4===0?206:187}`} stroke="#e5edcc" opacity=".45" strokeWidth="3" transform={`rotate(${i*7.5} 540 548)`}/>)}<path d="M540 548V286" stroke={lime} strokeWidth="9" strokeLinecap="round" transform={`rotate(${f*2.8} 540 548)`}/></svg>
  {[['标题',-29,230],['选品',21,540],['商品图',-4,610]].map(([label,rotation,x],i)=><div key={String(label)} style={{position:'absolute',left:Number(x)-i*80,top:820-p*(190+i*100),transform:`rotate(${Number(rotation)+Math.sin(f/24+i)*5}deg) scale(.73)`,opacity:p}}><Sheet label={String(label)} color={i===1?lime:'#f1eee5'}/></div>)}
  <div style={{position:'absolute',left:220,top:855,transform:`scale(${1.05+ease(f,0,136,0,.1)}) translateY(${Math.sin(f/24)*5}px)`}}><Parcel open={p}/></div>
  <Words top={1440} size={42} color="#f1f0e8b5" style={{letterSpacing:1}}>卖货之外，还有一长串准备。</Words>
 </Base>;
};
const Friction=()=>{
 const f=useCurrentFrame();
 const rows=[['选品','方向在哪？',0],['资料','又翻了一遍',15],['内容','还是要重改',30]] as const;
 return <Base>
  <Words top={165} size={82}>忙了一圈，<br/>还没往前走。</Words>
  <div style={{position:'absolute',width:1260,top:555,left:-90,transform:`rotate(-7deg) translateX(${-ease(f,0,149,0,55)}px)`}}>
   {rows.map(([label,detail,delay],i)=><div key={label} style={{display:'flex',alignItems:'center',gap:32,height:214,paddingLeft:245,background:i===1?ink:i===2?coral:lime,color:i===1?paper:ink,marginBottom:24,transform:`translateX(${(1-enter(f,delay))*(i%2?-950:950)}px)`,boxShadow:'0 10px 24px #0001'}}><span style={{fontSize:91,fontWeight:800,letterSpacing:-4}}>{label}</span><span style={{width:96,height:1,background:'currentColor',opacity:.5}}/><span style={{fontSize:46,letterSpacing:0}}>{detail}</span><span style={{fontSize:60}}>↻</span></div>)}
  </div>
  <div style={{position:'absolute',left:20,top:1240,transform:`scale(.36) rotate(${ease(f,0,149,-20,12)}deg)`,transformOrigin:'left top'}}><Parcel id="friction"/></div>
  <Words top={1478} size={42} style={{letterSpacing:0}}>工具越换越多，流程反复重来。</Words>
 </Base>;
};
const Reveal=()=>{
 const f=useCurrentFrame(),p=enter(f,4);
 return <Base dark>
  <div style={{position:'absolute',width:800,height:800,left:140,top:620,borderRadius:'50%',background:'radial-gradient(circle,#dceb8c4d,transparent 70%)',transform:`scale(${1+f*.0015})`}}/>
  <Words top={180} size={152} color={paper} style={{opacity:p,transform:`translateY(${(1-p)*30}px)`}}>捷境</Words>
  <Words top={395} size={61} color={lime} style={{letterSpacing:-1}}>面向跨境卖家的<br/>AI 电商工作台</Words>
  <svg width="1080" height="1100" style={{position:'absolute',top:570}} viewBox="0 0 1080 1100"><defs><linearGradient id="orbit"><stop stopColor="#e9f6a8"/><stop offset="1" stopColor="#a7c4bb"/></linearGradient></defs>{[0,1,2].map(i=><ellipse key={i} cx="540" cy="564" rx={270+i*95} ry={160+i*57} fill="none" stroke="url(#orbit)" opacity={.75-i*.2} strokeWidth="2" transform={`rotate(${-23+i*8+f*.05} 540 564)`}/>)}<path d="M200 650 505 473 824 590 522 776Z" fill="#e9f0d1" opacity=".13"/><path d="M200 650V711L522 837V776M824 590V651L522 837" fill="#b7c1a8" opacity=".15"/></svg>
  <div style={{position:'absolute',left:270,top:725,transform:`translateY(${(1-p)*120+Math.sin(f/25)*8}px) scale(.91)`}}><Parcel id="reveal"/></div>
  <Words top={1505} size={40} color={paper} style={{letterSpacing:2}}>把零散的准备，接成一条线。</Words>
 </Base>;
};
const Connected=()=>{
 const f=useCurrentFrame(),progress=ease(f,10,115);
 const stages=[{x:180,y:650,name:'调研',detail:'找方向'},{x:650,y:965,name:'商品内容',detail:'写草稿'},{x:220,y:1290,name:'图片视频',detail:'做素材'}];
 return <Base>
  <Words top={158} size={83}>不是多一个工具。<br/><span style={{color:'#557549'}}>是少一次切换。</span></Words>
  <svg width="1080" height="1920" style={{position:'absolute',inset:0}}><path d="M260 710C280 920 770 760 770 1035S320 1140 330 1380" fill="none" stroke="#cdd1bd" strokeWidth="4" strokeDasharray="10 15"/><path d="M260 710C280 920 770 760 770 1035S320 1140 330 1380" fill="none" stroke="#63804b" strokeWidth="9" pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/></svg>
  {stages.map((s,i)=>{const p=enter(f,i*24);return <div key={s.name} style={{position:'absolute',left:s.x,top:s.y,opacity:p,transform:`translateY(${(1-p)*75}px) rotate(${i===1?6:-6}deg)`}}><div style={{width:236,height:170,padding:25,background:i===1?ink:lime,borderRadius:12,boxShadow:'12px 22px 0 #bcc4af55',color:i===1?paper:ink}}><div style={{fontSize:33,fontWeight:760}}>{s.name}</div><div style={{fontSize:25,marginTop:20,opacity:.75}}>{s.detail} <span style={{float:'right'}}>↗</span></div></div></div>})}
  <div style={{position:'absolute',left:414+Math.sin(progress*Math.PI)*140,top:635+progress*560,transform:'scale(.32)',transformOrigin:'left top'}}><Parcel id="connected"/></div>
  <Words top={1585} size={35} style={{letterSpacing:0}}>围绕同一个商品，接着往下做。</Words>
 </Base>;
};
const Decision=()=>{
 const f=useCurrentFrame(),p=enter(f,10);
 return <Base>
  <Words top={172} size={87}>AI 做准备。<br/>你做决定。</Words>
  <div style={{position:'absolute',top:455,left:94,color:'#536b4b',fontSize:35,letterSpacing:1}}>现阶段支持 eBay</div>
  <div style={{position:'absolute',left:145,top:650,width:750,height:642,padding:65,background:'#fcfcf7',boxShadow:'22px 30px 0 #d8ddce,0 55px 100px #16281a24',transform:`perspective(1800px) rotateY(${ease(f,0,108,-14,0)}deg) rotateZ(-3deg)`}}>
   <div style={{fontSize:34,color:'#61705b',marginBottom:40}}>商品内容草稿</div>
   <div style={{fontSize:56,fontWeight:760,marginBottom:30}}>核对，再往前走。</div>
   {[.92,.73,.88].map((w,i)=><div key={i} style={{width:`${w*100}%`,height:13,background:'#d9dfd1',marginBottom:28,borderRadius:10}}/>)}
   <div style={{display:'flex',gap:20,marginTop:70}}><div style={{fontSize:30,padding:'23px 32px',border:'2px solid #9caa8b',borderRadius:10}}>修改内容</div><div style={{fontSize:30,padding:'23px 32px',background:ink,color:lime,borderRadius:10}}>确认后发布 ↗</div></div>
  </div>
  <div style={{position:'absolute',left:750,top:1130,width:70,height:100,transform:`translate(${(1-p)*130}px,${(1-p)*180}px) rotate(-20deg)`}}><svg viewBox="0 0 70 100"><path d="M5 4 59 56 34 59 25 88Z" fill={coral} stroke={paper} strokeWidth="5"/></svg></div>
  <Words top={1495} size={39} style={{letterSpacing:0}}>可编辑 · 可确认 · 不替你擅自发布</Words>
 </Base>;
};
const Close=()=>{
 const f=useCurrentFrame();
 return <Base dark>
  <Words top={171} size={86} color={paper}>少一点切换。<br/><span style={{color:lime}}>多一点进展。</span></Words>
  <div style={{position:'absolute',left:256,top:695,transform:`translateY(${Math.sin(f/24)*7}px) scale(.96)`}}><Parcel id="close"/></div>
  <div style={{position:'absolute',left:128,top:990,transform:`rotate(-13deg) scale(.4) translateY(${-enter(f,8)*80}px)`,transformOrigin:'left top'}}><Sheet label="调研与方向" color={lime}/></div>
  <div style={{position:'absolute',left:758,top:759,transform:`rotate(13deg) scale(.45) translateY(${-enter(f,14)*60}px)`,transformOrigin:'left top'}}><Sheet label="商品内容"/></div>
  <div style={{position:'absolute',left:105,top:1283,right:105,height:2,background:'#ecf4c64d'}}/>
  <Words top={1338} size={63} color={paper}>捷境 <span style={{fontSize:32,fontWeight:400,letterSpacing:0}}>AI 电商工作台</span></Words>
  <Words top={1450} size={79} color={lime} style={{fontFamily:'Arial,sans-serif',fontWeight:600,letterSpacing:-2}}>jiejing.shop <span style={{fontSize:58}}>↗</span></Words>
  <Words top={1571} size={35} color="#e7eddfba" style={{letterSpacing:0}}>带上一个商品，从这里开始。</Words>
 </Base>;
};
const scenes=[{from:0,duration:136,C:Hook},{from:136,duration:153,C:Friction},{from:289,duration:132,C:Reveal},{from:421,duration:136,C:Connected},{from:557,duration:110,C:Decision},{from:667,duration:173,C:Close}];
const captions=[
 [0,69,'做跨境，货有了'],[69,132,'时间却全花在上架前'],[136,206,'选品没方向，资料来回找'],[206,285,'标题和图片反复改'],
 [289,330,'捷境'],[330,416,'是面向跨境卖家的 AI 电商工作台'],[421,492,'调研、文案、图片视频'],[492,553,'在这里接着做'],
 [557,603,'目前先支持 eBay'],[603,662,'修改后由你确认发布'],[667,707,'少来回切换'],[707,770,'让商品准备更完整'],
] as const;
export const JiejingV17:React.FC<{withAudio?:boolean}>=({withAudio=false})=>{
 const f=useCurrentFrame(); const caption=captions.find(([a,b])=>f>=a&&f<b);
 return <AbsoluteFill>
  {scenes.map(({from,duration,C})=><Sequence key={from} from={from} durationInFrames={duration} premountFor={30}><C/></Sequence>)}
  {caption?<div style={{position:'absolute',left:68,right:100,bottom:126,textAlign:'center',fontSize:34,lineHeight:1.5,fontWeight:600,color:'#fff',textShadow:'0 2px 10px #000b'}}><span style={{background:'#182327da',borderRadius:8,padding:'12px 24px',boxDecorationBreak:'clone'}}>{caption[2]}</span></div>:null}
  {withAudio?<Audio src={staticFile('v17-narration.wav')}/>:null}
 </AbsoluteFill>;
};
