import React from 'react';
import {AbsoluteFill, Easing, interpolate} from 'remotion';

export const font = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif';
export const C = {paper:'#eeeae1', ink:'#1b252c', red:'#c94429', blue:'#234b68', muted:'#696d6d'};
export const ease = {extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.22,.8,.23,1)} as const;
export const move = (f:number, a:number, b:number, x:number, y:number) => interpolate(f,[a,b],[x,y],ease);

export const Set: React.FC<{children:React.ReactNode; dark?:boolean}> = ({children,dark=false}) => <AbsoluteFill style={{fontFamily:font,color:dark?'#fff7e7':C.ink,background:dark?'#172731':C.paper,overflow:'hidden'}}>
  <AbsoluteFill style={{background:dark?'radial-gradient(ellipse at 12% 10%, #47617199, transparent 65%)':'radial-gradient(ellipse at 20% 16%, #fffdf7, transparent 65%), linear-gradient(125deg, #f1eee6, #ddd8cc)'}}/>
  <div style={{position:'absolute',left:-440,top:-320,width:1800,height:440,background:'#ffffff14',transform:'rotate(-36deg)',boxShadow:'0 180px 130px #ffffff0c'}}/>
  {children}
</AbsoluteFill>;

/** Original procedural object. No supplier photo, automatic measurement or verified dimensions. */
export const DrainPad: React.FC<{id:string; size?:number; tilt?:number; spin?:number; style?:React.CSSProperties}> = ({id,size=700,tilt=25,spin=-18,style={}}) => {
  const slots = Array.from({length:19},(_,i)=>{
    const x=175+i*25;
    const half=Math.sqrt(Math.max(0,220**2-(x-400)**2));
    return {x,y:400-half,h:half*2};
  });
  return <div style={{width:size,height:size,transform:`perspective(1300px) rotateX(${tilt}deg) rotateZ(${spin}deg)`,...style}}>
    <svg viewBox="0 0 800 800" width="100%" height="100%" style={{overflow:'visible'}}>
      <defs>
        <linearGradient id={`${id}-face`} x1="0" x2=".8" y1="0" y2="1"><stop stopColor="#7392a4"/><stop offset=".36" stopColor="#315d79"/><stop offset="1" stopColor="#17394f"/></linearGradient>
        <linearGradient id={`${id}-edge`} x1="0" x2="0" y1="0" y2="1"><stop stopColor="#274b60"/><stop offset="1" stopColor="#102936"/></linearGradient>
        <mask id={`${id}-holes`}><rect width="800" height="800" fill="white"/>{slots.map((s,i)=><rect key={i} x={s.x} y={s.y} width="10" height={s.h} rx="5" fill="black"/>)}</mask>
        <filter id={`${id}-shadow`} x="-60%" y="-60%" width="220%" height="240%"><feGaussianBlur stdDeviation="29"/></filter>
      </defs>
      <ellipse cx="430" cy="620" rx="293" ry="102" fill="#152e37" opacity=".28" filter={`url(#${id}-shadow)`}/>
      {[22,17,12,7].map(d=><rect key={d} x="112" y={112+d} width="576" height="576" rx="142" fill={`url(#${id}-edge)`} mask={`url(#${id}-holes)`}/>)}
      <rect x="112" y="112" width="576" height="576" rx="142" fill={`url(#${id}-face)`} stroke="#90aebb" strokeWidth="2.2" mask={`url(#${id}-holes)`}/>
      {slots.map((s,i)=><g key={i} opacity=".62"><path d={`M${s.x-5} ${149+Math.abs(i-9)*5} V${655-Math.abs(i-9)*5}`} stroke="#abd0dd" strokeWidth="1.9" strokeLinecap="round"/><path d={`M${s.x-11} ${149+Math.abs(i-9)*5} V${655-Math.abs(i-9)*5}`} stroke="#102e43" strokeWidth="2.3" strokeLinecap="round"/></g>)}
      <rect x="621" y="352" width="38" height="152" rx="19" fill="#153a4e" stroke="#82a4af" strokeWidth="2"/>
      <rect x="628" y="356" width="24" height="137" rx="12" fill="#ff8b66" stroke="#ffb896" strokeWidth="2"/>
      <path d="M157 247 Q180 142 276 133" fill="none" stroke="#bfd3da" strokeOpacity=".6" strokeWidth="3"/>
    </svg>
  </div>;
};

export const Paper:React.FC<{label:string;number:string;angle?:number;style?:React.CSSProperties}> = ({label,number,angle=0,style={}}) => <div style={{width:650,height:490,color:C.ink,background:'#fffef8',boxShadow:'10px 36px 45px #26312a26',padding:'48px 46px',transform:`rotate(${angle}deg)`,border:'1px solid #dad6cc',...style}}>
  <div style={{fontSize:32,color:C.muted,letterSpacing:3}}>{label}</div>
  <div style={{height:1,background:'#c7c8c0',marginTop:24}}/>
  <div style={{fontSize:130,fontWeight:800,fontFamily:'Arial, sans-serif',letterSpacing:-7,marginTop:26}}>{number}<span style={{fontSize:37,fontWeight:400,letterSpacing:0,marginLeft:12}}>cm</span></div>
  <div style={{marginTop:18,display:'flex',gap:12}}>{[135,220,75].map((w,i)=><div key={i} style={{width:w,height:7,background:'#d9dedb'}}/>)}</div>
</div>;

export const Logo:React.FC<{size?:number;light?:boolean}> = ({size=140,light=false}) => <svg width={size} height={size} viewBox="95 65 325 355">
  <path d="M160 348C173 260 229 204 332.5 141C275 175 262 251 354 337.5C282.5 304.5 229.5 314.5 160 348Z" fill={light?'#fff5e3':C.ink}/>
  <path d="M231 335.5C246.5 273 274 222 322.5 175C283.5 230 274 277 300 332C276 323.5 257 326.5 231 335.5Z" fill={light?'#172731':C.paper}/><circle cx="348" cy="133" r="18" fill="#ee9b52"/>
</svg>;

export const Cursor:React.FC<{x:number;y:number;rotate?:number;press?:boolean}> = ({x,y,rotate=0,press=false}) => <svg width="92" height="110" viewBox="0 0 92 110" style={{position:'absolute',left:x,top:y,transform:`rotate(${rotate}deg) scale(${press?.9:1})`,filter:'drop-shadow(4px 8px 5px #0002)'}}><path d="M8 5L76 67L42 68L28 100Z" fill={C.ink} stroke="#fffdf4" strokeWidth="5" strokeLinejoin="round"/></svg>;
