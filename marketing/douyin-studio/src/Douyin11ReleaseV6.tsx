import type {CSSProperties, ReactNode} from 'react';
import {Audio} from '@remotion/media';
import {AbsoluteFill, Easing, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {releaseTiming as T} from './ReleaseV6Timing';

const C = {paper: '#F6F4EE', ink: '#141C25', blue: '#2456F5', muted: '#646D78', line: '#D8DCE3'};
const ease = {extrapolateLeft: 'clamp' as const, extrapolateRight: 'clamp' as const, easing: Easing.bezier(.18,.85,.2,1)};
const file = (name: string) => staticFile(`release-v6/${name}`);

function Arrow({size=44,color=C.blue}:{size?:number;color?:string}) {
  return <svg width={size} height={size} viewBox="0 0 40 40" fill="none"><path d="M6 20H33M23 9L34 20L23 31" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}

function Mark({dark=false}:{dark?:boolean}) {
  return <div style={{position:'absolute',left:76,right:160,top:102,display:'flex',alignItems:'center',gap:15,color:dark?'#FFF':C.ink}}>
    <Img src={file('brand.svg')} style={{width:52,height:52,borderRadius:14,background:'white'}}/>
    <span style={{fontSize:36,fontWeight:800}}>捷境</span>
    <span style={{marginLeft:'auto',fontSize:21,letterSpacing:2,opacity:.67}}>跨境电商 AI CEO</span>
  </div>;
}

function Stage({children,dark=false}:{children:ReactNode;dark?:boolean}) {
  return <AbsoluteFill style={{background:dark?C.blue:C.paper,color:dark?'#FFF':C.ink,overflow:'hidden'}}>
    <div style={{position:'absolute',width:1300,height:1300,left:-470,top:860,borderRadius:'50%',background:dark?'radial-gradient(circle,#7B9DFF60 0%,#2456F500 66%)':'radial-gradient(circle,#9CB6FF38 0%,#F6F4EE00 68%)'}}/>
    {children}<Mark dark={dark}/>
  </AbsoluteFill>;
}

function Eyebrow({children,dark=false,style}:{children:ReactNode;dark?:boolean;style?:CSSProperties}) {
  return <div style={{fontSize:27,fontWeight:600,letterSpacing:2,color:dark?'#CAD9FF':C.blue,...style}}>{children}</div>;
}

// Original illustration, representing a generic product rather than merchant goods.
function Package({style,large=false}:{style?:CSSProperties;large?:boolean}) {
  return <div style={{position:'absolute',width:large?590:450,height:large?610:470,...style}}>
    <svg width="100%" height="100%" viewBox="0 0 500 520">
      <defs>
        <linearGradient id={large?'pfrontL':'pfront'} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#FFFFFF"/><stop offset=".45" stopColor="#EDF0F4"/><stop offset="1" stopColor="#CCD4E1"/></linearGradient>
        <linearGradient id={large?'psideL':'pside'}><stop stopColor="#194AD8"/><stop offset="1" stopColor="#4575FD"/></linearGradient>
        <filter id={large?'pshadowL':'pshadow'} x="-40%" width="200%" y="-60%" height="250%"><feGaussianBlur stdDeviation="15"/></filter>
      </defs>
      <ellipse cx="254" cy="454" rx="152" ry="23" fill="#17358135" filter={`url(#${large?'pshadowL':'pshadow'})`}/>
      <path d="M90 139L290 67L415 138L217 217Z" fill="#FDFEFF" stroke="#FFFFFF" strokeWidth="2"/>
      <path d="M90 139L217 217V432L91 353Z" fill={`url(#${large?'psideL':'pside'})`}/>
      <path d="M217 217L415 138V353L217 432Z" fill={`url(#${large?'pfrontL':'pfront'})`}/>
      <path d="M249 83L376 154L338 169L210 98Z" fill="#9AB4FF" opacity=".42"/>
      <path d="M217 217V432" stroke="#F8FBFF" strokeWidth="2"/>
      <path d="M255 259L377 212V295L255 342Z" fill="#FFFFFFA8" stroke="#C7D1E1"/>
      <path d="M276 263L341 238M276 280L358 248M276 295L328 275" stroke="#97A7C4" strokeWidth="4" strokeLinecap="round"/>
      <path d="M119 183L156 205V239L119 216Z" fill="#96B0FE"/>
      <path d="M119 281L181 319M119 300L165 328" stroke="#A7BEFF" strokeWidth="5"/>
      <path d="M284 358L378 322" stroke="#94A0B2" strokeWidth="20" strokeDasharray="2 4 1 3 2 5"/>
    </svg>
  </div>;
}

function Paper({label,style,kind='lines'}:{label:string;style:CSSProperties;kind?:'lines'|'photo'|'spec'}) {
  return <div style={{position:'absolute',width:350,height:224,padding:'23px 25px',background:'#FFFEFA',color:C.ink,border:'1px solid #DFE2E8',borderRadius:10,boxShadow:'0 18px 45px #16213B1B',...style}}>
    <div style={{display:'flex',alignItems:'center',gap:10,fontSize:26,fontWeight:700,marginBottom:22}}><span style={{width:7,height:24,background:C.blue,borderRadius:4}}/>{label}</div>
    {kind==='photo'?<div style={{display:'flex',gap:13}}>{[0,1,2].map(i=><div key={i} style={{height:91,width:90,background:i===0?'#DDE7FF':'#EDEFF1',borderRadius:5,display:'flex',alignItems:'center',justifyContent:'center'}}><svg width="42" height="42" viewBox="0 0 40 40"><path d="M4 31L16 14L24 24L29 18L37 31Z" fill={i===0?'#7A9CF5':'#B4BFCE'}/><circle cx="27" cy="9" r="4" fill={i===0?'#91AEF7':'#C7CED8'}/></svg></div>)}</div>:kind==='spec'?<div style={{display:'flex',gap:16,fontSize:21,color:C.muted}}><span>尺寸<br/><br/>材质</span><div style={{flex:1}}><div style={{height:9,background:'#C5CFDF',width:'78%',marginTop:7,marginBottom:35}}/><div style={{height:9,background:'#DDE3EA',width:'55%'}}/></div></div>:<div>{[260,200,235].map(w=><div key={w} style={{height:10,width:w,background:'#D0D9E8',marginTop:15,borderRadius:4}}/>)}</div>}
  </div>;
}

function Hook() {
  const f=useCurrentFrame();
  return <Stage>
    <div style={{position:'absolute',left:76,top:255,right:140}}>
      <Eyebrow>给已有店铺、准备新品的你</Eyebrow>
      <div style={{marginTop:31,fontSize:88,fontWeight:800,lineHeight:1.17,letterSpacing:-3}}>商品有了。</div>
      <div style={{marginTop:16,fontSize:135,fontWeight:900,lineHeight:1.13,letterSpacing:-7}}>上架准备，<br/><span style={{color:C.blue}}>还这么累？</span></div>
    </div>
    <div style={{position:'absolute',left:75,top:822,width:860,height:2,background:'#CBD3E2',opacity:.6}}/>
    <Paper label="商品参数" kind="spec" style={{left:90,top:925,rotate:`${interpolate(f,[0,90],[-10,-6],ease)}deg`,translate:`0 ${interpolate(f,[0,60],[35,0],ease)}px`}}/>
    <Paper label="真实图片" kind="photo" style={{left:565,top:1088,rotate:`${interpolate(f,[0,100],[9,4],ease)}deg`,translate:`0 ${interpolate(f,[0,90],[-18,0],ease)}px`}}/>
    <Package large style={{left:258,top:820,rotate:`${interpolate(f,[0,100],[-7,0],ease)}deg`,translate:`0 ${interpolate(f,[0,90],[46,0],ease)}px`}}/>
    <div style={{position:'absolute',left:88,top:1395,fontSize:31,fontWeight:650,display:'flex',alignItems:'center',gap:17}}><span style={{width:32,height:32,border:'2px solid #A9B9D7',borderRadius:'50%',display:'inline-block'}}/>写商品页、备素材、反复核对…</div>
  </Stage>;
}

function Brand() {
  const f=useCurrentFrame();
  return <Stage dark>
    <div style={{position:'absolute',left:77,top:270}}>
      <Eyebrow dark>把分散的准备，接着往前做</Eyebrow>
      <div style={{fontSize:177,fontWeight:900,letterSpacing:-8,marginTop:43,lineHeight:1.1,translate:`${interpolate(f,[0,16],[42,0],ease)}px 0`}}>捷境<span style={{fontSize:59,letterSpacing:-1,marginLeft:25,fontWeight:600}}>AI CEO</span></div>
      <div style={{fontSize:41,lineHeight:1.5,marginTop:36,color:'#E0E8FF'}}>跨境电商经营，<br/>从一个清楚的目标开始。</div>
    </div>
    <div style={{position:'absolute',left:95,top:819,width:812,height:521,border:'1px solid #A4BDFF',borderRadius:32,background:'linear-gradient(125deg,#D1DEFF28,#224CCE30)',boxShadow:'0 32px 90px #1539AC30',rotate:`${interpolate(f,[0,110],[-4,0],ease)}deg`}}>
      <div style={{position:'absolute',left:31,right:31,top:26,height:44,borderBottom:'1px solid #BDD0FF48',fontSize:23,letterSpacing:3,color:'#D8E4FF'}}>YOUR PRODUCT. YOUR GOAL.</div>
      <Package style={{left:5,top:35,scale:.77}}/>
      <div style={{position:'absolute',left:387,top:136,right:35,fontSize:51,lineHeight:1.58,fontWeight:750}}>你说目标<br/>它来协助<br/><span style={{color:'#BFD3FF'}}>你定关键一步</span></div>
    </div>
    <div style={{position:'absolute',left:86,top:1395,fontSize:25,color:'#D7E2FF',letterSpacing:1}}>从真实资料出发，不靠猜测商品事实。</div>
  </Stage>;
}

function Use() {
  const f=useCurrentFrame();
  const split=interpolate(f,[75,128],[0,1],ease);
  return <Stage>
    <div style={{position:'absolute',left:76,top:253}}>
      <Eyebrow>商家要做的第一步</Eyebrow>
      <div style={{fontSize:100,fontWeight:850,letterSpacing:-4,lineHeight:1.19,marginTop:31}}>说目标。给资料。<br/><span style={{color:C.blue}}>工作继续往前。</span></div>
    </div>
    <div style={{position:'absolute',left:76,top:622,width:846,height:273,border:'1px solid #C8D2E5',borderRadius:19,background:'#FFFFFF',boxShadow:'0 24px 65px #304D7D12',overflow:'hidden'}}>
      <div style={{height:63,borderBottom:'1px solid #E0E5ED',padding:'17px 23px',fontSize:25,fontWeight:650}}>用中文告诉捷境</div>
      <div style={{position:'absolute',left:19,top:83,width:808,height:139,overflow:'hidden',borderRadius:9,border:'1px solid #D7E0E9'}}>
        {f<111?<OffthreadVideo src={file('goal.mp4')} muted style={{position:'absolute',width:1131,left:-274,top:-807}}/>:<Img src={file('workspace-goal.png')} style={{position:'absolute',width:1131,left:-274,top:-807}}/>}
      </div>
      <div style={{position:'absolute',left:24,top:235,fontSize:20,color:C.muted}}>真实界面 · 输入示例</div>
    </div>
    <Paper label="图片 + 参数" kind="photo" style={{left:109-12*split,top:1033-78*split,scale:1-.18*split,transformOrigin:'top left',rotate:`${-6+6*split}deg`,opacity:1-.13*split}}/>
    <svg width="835" height="510" viewBox="0 0 835 510" style={{position:'absolute',left:84,top:970,opacity:split}}><path d="M252 87H338Q367 87 367 116V277Q367 307 397 307H444M367 120H444M367 300V425Q367 445 397 445H444" stroke="#87A5F2" strokeWidth="3" fill="none" strokeDasharray="1100" strokeDashoffset={1100*(1-split)}/><circle cx="367" cy="120" r="6" fill={C.blue}/></svg>
    <div style={{position:'absolute',left:529,top:967,width:394,opacity:split}}>
      {['市场调研','商品页草稿','素材准备'].map((text,i)=><div key={text} style={{height:145,padding:'18px 2px',borderBottom:i<2?'1px solid #D1D9E5':'none',opacity:interpolate(f,[100+i*17,128+i*17],[.2,1],ease),translate:`${interpolate(f,[100+i*17,128+i*17],[28,0],ease)}px 0`}}><div style={{fontSize:21,color:C.muted,marginBottom:9}}>0{i+1} / {i===0?'协助了解市场':i===1?'准备并继续修改':'围绕真实商品'}</div><div style={{fontSize:41,fontWeight:750}}>{text}</div></div>)}
    </div>
    <div style={{position:'absolute',left:86,top:1410,fontSize:22,color:C.muted,opacity:split}}>准备流程示意</div>
  </Stage>;
}

function Confirmation() {
  const f=useCurrentFrame();
  const press=interpolate(f,[58,68,83],[0,1,0],ease);
  return <Stage>
    <div style={{position:'absolute',left:77,top:263}}>
      <Eyebrow>协助推进，不替你擅自做决定</Eyebrow>
      <div style={{fontSize:116,fontWeight:850,lineHeight:1.18,letterSpacing:-5,marginTop:30}}>发布之前，<br/><span style={{color:C.blue}}>你来确认。</span></div>
    </div>
    <div style={{position:'absolute',left:77,top:712,width:845,height:537,border:'1px solid #C8D2E4',borderRadius:25,background:'white',boxShadow:'0 27px 70px #1A335517',padding:36}}>
      <div style={{fontSize:25,fontWeight:650,borderBottom:'1px solid #DFE5F0',paddingBottom:23}}>发布前，先把条件核对清楚</div>
      <div style={{display:'flex',justifyContent:'space-between',marginTop:39}}>
        <div><div style={{fontSize:23,color:C.muted}}>01</div><div style={{fontSize:37,fontWeight:750,marginTop:10}}>事实核对</div></div><div style={{paddingTop:31}}><Arrow size={34}/></div>
        <div><div style={{fontSize:23,color:C.muted}}>02</div><div style={{fontSize:37,fontWeight:750,marginTop:10}}>预检通过</div></div><div style={{paddingTop:31}}><Arrow size={34}/></div>
        <div><div style={{fontSize:23,color:C.blue}}>03</div><div style={{fontSize:37,fontWeight:750,marginTop:10,color:C.blue}}>你确认</div></div>
      </div>
      <div style={{position:'absolute',left:38,right:38,bottom:75,height:119,borderRadius:14,background:C.blue,boxShadow:`0 ${18-12*press}px ${32-14*press}px #2456F52E`,scale:1-.018*press,display:'flex',alignItems:'center',justifyContent:'space-between',padding:'0 30px',color:'white'}}><span style={{fontSize:41,fontWeight:750}}>确认后，调用平台接口</span><Arrow size={45} color="white"/></div>
      <div style={{position:'absolute',left:39,bottom:29,fontSize:21,color:C.muted}}>流程示意 · 需符合店铺与平台条件</div>
    </div>
    <div style={{position:'absolute',left:85,top:1322,fontSize:30,color:C.muted}}>准备、核对、发布，是接续的工作。</div>
  </Stage>;
}

function Ending({cover=false}:{cover?:boolean}) {
  const frame=useCurrentFrame();const f=cover?80:frame;
  return <Stage dark>
    <div style={{position:'absolute',left:77,top:255}}>
      <Eyebrow dark>先支持 eBay，逐步拓展</Eyebrow>
      <div style={{fontSize:119,fontWeight:850,letterSpacing:-5,lineHeight:1.18,marginTop:32}}>从一件商品，<br/>开始试起来。</div>
    </div>
    <Package large style={{left:232,top:689,scale:1.02,translate:`0 ${interpolate(f,[0,90],[36,0],ease)}px`}}/>
    <div style={{position:'absolute',left:75,top:1230,width:846,borderTop:'1px solid #AAC1FF80',paddingTop:25,display:'flex',alignItems:'center',justifyContent:'space-between'}}><div><div style={{fontSize:78,fontWeight:850,letterSpacing:-3}}>捷境</div><div style={{fontSize:28,marginTop:4,color:'#D3E0FF'}}>跨境电商 AI CEO</div></div><div style={{display:'flex',alignItems:'center',gap:13,fontSize:30,fontWeight:650}}>了解捷境<Arrow size={44} color="white"/></div></div>
    <div style={{position:'absolute',left:80,top:1431,fontSize:26,color:'#D1DEFF'}}>规划中：亚马逊 · TikTok Shop · 抖音等，尚未接入</div>
  </Stage>;
}

export function Douyin11ReleaseCover() {
  return <AbsoluteFill style={{fontFamily:'"ReleaseSans", "Noto Sans CJK SC", sans-serif'}}><Fonts/><Hook/></AbsoluteFill>;
}

function Fonts() {
  return <style>{`@font-face{font-family:ReleaseSans;src:url('${file('sans.otf')}');font-weight:100 600;}@font-face{font-family:ReleaseSans;src:url('${file('bold.otf')}');font-weight:650 950;}`}</style>;
}

export function Douyin11ReleaseV6({includeAudio=true}:{includeAudio?:boolean}) {
  const f=useCurrentFrame();const ms=f/30*1000;
  const caption=T.captions.find(x=>ms>=x.startMs&&ms<x.endMs)?.text??'';
  const dark=(f>=T.beats.brand&&f<T.beats.use)||f>=T.beats.end;
  return <AbsoluteFill style={{fontFamily:'"ReleaseSans", "Noto Sans CJK SC", sans-serif',background:C.paper,overflow:'hidden'}}>
    <Fonts/>
    {includeAudio?<Audio src={file('soundtrack.wav')}/>:null}
    <Sequence name="商家痛点" durationInFrames={T.beats.brand}><Hook/></Sequence>
    <Sequence name="介绍捷境" from={T.beats.brand} durationInFrames={T.beats.use-T.beats.brand}><Brand/></Sequence>
    <Sequence name="说目标与交资料" from={T.beats.use} durationInFrames={T.beats.confirm-T.beats.use}><Use/></Sequence>
    <Sequence name="预检与商家确认" from={T.beats.confirm} durationInFrames={T.beats.end-T.beats.confirm}><Confirmation/></Sequence>
    <Sequence name="从一件商品开始" from={T.beats.end} durationInFrames={T.durationInFrames-T.beats.end}><Ending/></Sequence>
    <div style={{position:'absolute',left:74,right:155,top:1521,display:'flex',justifyContent:'center',alignItems:'center',minHeight:92,padding:'14px 19px',fontSize:37,fontWeight:600,lineHeight:1.43,textAlign:'center',color:dark?'#FFFFFF':C.ink,background:dark?'#1742C44D':'#F6F4EEEE',borderRadius:10}}>{caption}</div>
    <div style={{position:'absolute',left:78,top:1648,fontSize:20,color:dark?'#C0D1FF':C.muted,opacity:.88}}>AI 合成配音 · 原创动画与流程示意</div>
  </AbsoluteFill>;
}
