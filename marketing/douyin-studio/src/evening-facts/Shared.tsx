import React from "react";
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from "remotion";

export const cream = "#f3f0e7";
export const ink = "#173a32";
export const lime = "#d6ed91";
export const font = '"Microsoft YaHei", "Noto Sans SC", sans-serif';
export const ease = {extrapolateLeft:"clamp",extrapolateRight:"clamp",easing:Easing.bezier(.16,1,.3,1)} as const;
export const Stage: React.FC<{children:React.ReactNode;dark?:boolean}> = ({children,dark=false}) => <AbsoluteFill style={{background:dark?ink:cream,color:dark?cream:ink,fontFamily:font,overflow:"hidden"}}>
  <div style={{position:"absolute",inset:0,opacity:dark?.04:.035,backgroundImage:`linear-gradient(${dark?cream:ink} 1px,transparent 1px),linear-gradient(90deg,${dark?cream:ink} 1px,transparent 1px)`,backgroundSize:"72px 72px"}}/>
  {children}
</AbsoluteFill>;
export const Heading: React.FC<{children:React.ReactNode;small?:boolean}> = ({children,small=false}) => <div style={{position:"absolute",top:212,left:86,right:128,fontSize:small?78:96,fontWeight:800,lineHeight:1.22,letterSpacing:-3}}>{children}</div>;

// Original diagram, not a supplier photo, software capture, or proof of a measured SKU.
export const DrainDiagram: React.FC<{scale?:number}> = ({scale=1}) => <svg viewBox="0 0 600 480" style={{width:600*scale,height:480*scale,overflow:"visible"}}>
  <defs><linearGradient id="pad-tone" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#648a80"/><stop offset=".5" stopColor="#214b40"/><stop offset="1" stopColor="#102e27"/></linearGradient></defs>
  <ellipse cx="307" cy="375" rx="232" ry="50" fill="#102e27" opacity=".13"/>
  <g transform="translate(74 25) rotate(-9 240 220)">
    <rect x="0" y="0" width="455" height="405" rx="128" fill="url(#pad-tone)" stroke="#769c8b" strokeWidth="3"/>
    {Array.from({length:18},(_,i)=><rect key={i} x={44+i*21} y={i<2||i>15?88:45} width="8" height={i<2||i>15?235:316} rx="4" fill="#0b261e" stroke="#668f7b" strokeWidth="1"/>)}
    <rect x="374" y="275" width="21" height="83" rx="10" fill="#ea9e79"/>
  </g>
</svg>;
export const Ruler: React.FC<{width?:number}> = ({width=760}) => {
  const f=useCurrentFrame();
  return <div style={{width,height:85,background:lime,overflow:"hidden",clipPath:`inset(0 ${interpolate(f,[8,40],[100,0],ease)}% 0 0)`}}>
    <svg width={width} height="85">{Array.from({length:41},(_,i)=><g key={i}><path d={`M ${i*19} 0 v ${i%5===0?42:22}`} stroke={ink} strokeWidth="2"/>{i%5===0&&<text x={i*19+4} y="65" fill={ink} fontFamily={font} fontSize="19">{i/5}</text>}</g>)}</svg>
  </div>;
};
