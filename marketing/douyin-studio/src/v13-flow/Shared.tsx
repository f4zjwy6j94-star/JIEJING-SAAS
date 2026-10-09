import React from "react";
import {Img, staticFile, interpolate, Easing, useCurrentFrame} from "remotion";

export const paper = "#f3f0e7";
export const ink = "#19382f";
export const accent = "#d2ee7a";
export const font = '"Microsoft YaHei", "Noto Sans SC", sans-serif';
export const ease = {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(.2,.8,.2,1)} as const;

export const Product: React.FC<{style?: React.CSSProperties}> = ({style}) => <Img src={staticFile("v13-product.png")} style={{width:"100%",height:"100%",objectFit:"contain",...style}}/>;

export const Pointer: React.FC<{x:number;y:number;click?:boolean}> = ({x,y,click=false}) => {
 const f=useCurrentFrame();
 return <div style={{position:"absolute",left:x,top:y,width:55,height:66,zIndex:30,scale:click ? interpolate(f%18,[0,6,18],[1,.85,1]) : 1}}>
  {click&&<div style={{position:"absolute",left:-20,top:-20,width:65,height:65,border:"3px solid #9db757",borderRadius:"50%",opacity:.55}}/>}
  <svg viewBox="0 0 50 62"><path d="M5 4 L7 47 L18 37 L28 57 L39 51 L28 32 L43 31 Z" fill="#172a25" stroke="#fff" strokeWidth="3"/></svg>
 </div>;
};

export const Frame: React.FC<{children:React.ReactNode;dark?:boolean}> = ({children,dark=false}) => <div style={{position:"absolute",inset:0,background:dark?ink:paper,color:dark?paper:ink,fontFamily:font,overflow:"hidden"}}>{children}</div>;
