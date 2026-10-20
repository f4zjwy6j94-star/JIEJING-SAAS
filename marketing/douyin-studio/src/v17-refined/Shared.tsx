import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

export const c = {ink:'#142a2a',paper:'#f2f0e8',lime:'#dfeaaa',coral:'#ef8064',muted:'#66756b'};
export const move = (f:number,a:number,b:number,x=0,y=1) => interpolate(f,[a,b],[x,y],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.2,.75,.2,1)});
export const Stage:React.FC<{dark?:boolean;children:React.ReactNode}> = ({dark=false,children}) => {
 const f=useCurrentFrame();
 return <AbsoluteFill style={{background:dark?c.ink:c.paper,color:dark?c.paper:c.ink,fontFamily:'Microsoft YaHei UI, Microsoft YaHei, sans-serif',overflow:'hidden'}}>
  <AbsoluteFill style={{background:dark?'radial-gradient(ellipse at 18% 45%,#58765b 0%,transparent 65%)':'radial-gradient(ellipse at 85% 24%,#fffefa 0%,transparent 70%)'}}/>
  <div style={{position:'absolute',left:-450,top:510,width:1800,height:800,background:dark?'#a0bb8630':'#c0c9b02a',filter:'blur(80px)',transform:`rotate(-33deg) translateY(${Math.sin(f/60)*8}px)`}}/>
  <AbsoluteFill style={{opacity:.045,backgroundImage:'repeating-linear-gradient(0deg,transparent 0,transparent 3px,#101d14 4px)'}}/>
  {children}
 </AbsoluteFill>;
};
export const Heading:React.FC<{children:React.ReactNode;dark?:boolean;top?:number;size?:number}> = ({children,dark=false,top=200,size=92}) => <div style={{position:'absolute',top,left:88,right:96,fontSize:size,fontWeight:760,lineHeight:1.25,letterSpacing:-4,color:dark?c.paper:c.ink}}>{children}</div>;
export const Label:React.FC<{children:React.ReactNode;top:number;dark?:boolean}> = ({children,top,dark=false}) => <div style={{position:'absolute',left:92,right:100,top,fontSize:42,lineHeight:1.5,color:dark?'#edf2d7b8':c.muted}}>{children}</div>;
export const Mark:React.FC<{dark?:boolean}> = ({dark=false}) => <div style={{fontSize:32,letterSpacing:2,color:dark?c.lime:c.ink,display:'flex',alignItems:'center',gap:18}}><div style={{height:22,width:22,background:dark?c.lime:c.ink,borderRadius:'50% 50% 6px 50%',transform:'rotate(-35deg)'}}/>捷境</div>;
export const Bag:React.FC<{size?:number;id?:string;angle?:number}> = ({size=600,id='bag',angle=-8}) => <svg width={size} height={size*.87} viewBox="0 0 700 610" style={{overflow:'visible',transform:`rotate(${angle}deg)`}}>
 <defs><linearGradient id={`${id}-face`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#e2e7c6"/><stop offset=".47" stopColor="#a8b294"/><stop offset="1" stopColor="#707f6e"/></linearGradient><linearGradient id={`${id}-side`}><stop stopColor="#556659"/><stop offset="1" stopColor="#89987b"/></linearGradient><filter id={`${id}-shadow`} x="-60%" y="-100%" width="230%" height="300%"><feGaussianBlur stdDeviation="22"/></filter><pattern id={`${id}-mesh`} width="11" height="11" patternUnits="userSpaceOnUse"><path d="M0 0L11 11M11 0L0 11" stroke="#e9edcf" strokeWidth="1" opacity=".26"/></pattern></defs>
 <ellipse cx="365" cy="535" rx="243" ry="48" fill="#001c13" opacity=".26" filter={`url(#${id}-shadow)`}/>
 <path d="M112 223Q99 178 152 153L462 91Q491 87 515 107L610 186Q632 208 625 246L595 439Q591 471 556 482L244 552Q220 555 193 535L82 454Z" fill={`url(#${id}-side)`}/>
 <path d="M108 206Q112 176 148 169L468 104Q492 99 518 119L602 191Q618 207 594 219L271 305Q249 310 228 299L124 245Q105 235 108 206Z" fill="#bcc5a8"/>
 <path d="M108 223L245 298Q263 309 286 303L606 217L575 433Q573 454 551 460L247 527Q224 532 202 519L91 446Z" fill={`url(#${id}-face)`}/>
 <path d="M125 266L236 323Q253 332 275 326L584 245L558 419Q556 432 542 435L247 502Q231 506 216 496L114 431Z" fill={`url(#${id}-mesh)`} stroke="#d2dac3" strokeWidth="2"/>
 <path d="M125 203L467 131Q486 127 503 141L574 200L268 279Q249 284 231 274L130 222Z" fill="#8c9c85" stroke="#eef1db" strokeWidth="3"/>
 <path d="M135 207L470 137Q482 136 493 145L563 201L267 273" fill="none" stroke="#31493e" strokeWidth="5" strokeDasharray="3 4"/>
 <path d="M287 322L309 320L304 376L280 380Z" fill="#d9dcc9" stroke="#41584d" strokeWidth="2"/>
 <rect x="378" y="349" width="91" height="47" rx="6" fill="#e9ead5" opacity=".85" transform="rotate(-12 378 349)"/>
 <path d="M264 135C255 39 399 7 423 101" fill="none" stroke="#485f4f" strokeWidth="23"/>
 <path d="M264 131C258 49 393 23 420 98" fill="none" stroke="#b4bca0" strokeWidth="8"/>
</svg>;
export const Paper:React.FC<{title:string;lines:string[];style?:React.CSSProperties;accent?:boolean}> = ({title,lines,style,accent=false}) => <div style={{position:'absolute',background:accent?c.lime:'#fffcf3',borderRadius:9,padding:'30px 34px',width:385,boxShadow:'0 28px 56px #07231425',border:'1px solid #fff9',color:c.ink,...style}}><div style={{fontSize:33,fontWeight:730,paddingBottom:21,borderBottom:'1px solid #31422c36'}}>{title}</div>{lines.map((t,i)=><div key={t} style={{fontSize:27,lineHeight:1.55,paddingTop:15,color:i===0?c.ink:c.muted}}>{t}</div>)}</div>;
export const LocalCaption:React.FC<{items: {text:string;startMs:number;endMs:number;timestampMs:null;confidence:null}[]}> = ({items}) => {const f=useCurrentFrame(),{fps}=useVideoConfig();const item=items.find(x=>f*1000/fps>=x.startMs&&f*1000/fps<x.endMs);return item?<div style={{position:'absolute',left:85,right:115,bottom:340,textAlign:'center',fontSize:37,fontWeight:550,lineHeight:1.45,color:'#fff'}}><span style={{background:'#102927ed',padding:'13px 24px',borderRadius:8,boxDecorationBreak:'clone'}}>{item.text}</span></div>:null;};
