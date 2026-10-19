import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import type {Caption} from '@remotion/captions';

export const colors = {ink:'#152331',paper:'#f3f1eb',orange:'#e6793c',blue:'#225b96',line:'#d2d7d7',muted:'#78818a'};
export const font = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif';
export const ease = (frame:number,start:number,end:number,a=0,b=1) => interpolate(frame,[start,end],[a,b],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.2,.75,.2,1)});
export const typed = (text:string,frame:number,start:number,end:number) => text.slice(0,Math.round(ease(frame,start,end)*text.length));

export const Stage:React.FC<{children:React.ReactNode;dark?:boolean}> = ({children,dark=false}) => <AbsoluteFill className="notranslate" translate="no" style={{background:dark?colors.ink:colors.paper,color:dark?'#fff':colors.ink,fontFamily:font,overflow:'hidden'}}>
  <AbsoluteFill style={{background:dark?'radial-gradient(ellipse at 10% 80%,#375570 0%,transparent 62%),linear-gradient(155deg,transparent 45%,#090f18 100%)':'radial-gradient(ellipse at 100% 0%,#fff 0%,transparent 64%),linear-gradient(130deg,transparent 40%,#e0e5e7 100%)'}}/>
  <div style={{position:'absolute',left:-200,top:150,width:1400,height:900,rotate:'-22deg',background:'linear-gradient(180deg,transparent,rgba(255,255,255,.08),transparent)',pointerEvents:'none'}}/>
  {children}
</AbsoluteFill>;

export const Bottle:React.FC<{x:number;y:number;width:number;rotate?:number;opacity?:number;shadow?:boolean}> = ({x,y,width,rotate=0,opacity=1,shadow=true}) => <div style={{position:'absolute',left:x,top:y,width,height:width*1.5,rotate:`${rotate}deg`,opacity}}>
  {shadow&&<div style={{position:'absolute',left:'22%',bottom:'5%',width:'62%',height:40,borderRadius:'50%',background:'#0c223a55',filter:'blur(25px)'}}/>}
  <Img src={staticFile('captures/v18-listing/product.png')} style={{width:'100%',height:'100%',objectFit:'contain',filter:shadow?'drop-shadow(12px 26px 24px rgba(6,18,29,.20))':'none'}}/>
</div>;

export const Cursor:React.FC<{x:number;y:number;click?:number;dark?:boolean}> = ({x,y,click=0,dark=false}) => <div style={{position:'absolute',left:x,top:y,width:60,height:75,zIndex:8}}>
  {click>0&&<div style={{position:'absolute',width:70,height:70,left:-25,top:-25,border:`3px solid ${colors.orange}`,borderRadius:'50%',scale:1+click*1.1,opacity:1-click}}/>}
  <svg width="60" height="75" viewBox="0 0 40 50"><path d="M5 3v36l9-10 9 18 8-4-9-18h14z" fill={dark?'#fff':colors.ink} stroke={dark?colors.ink:'#fff'} strokeWidth="2"/></svg>
</div>;

export const VoiceCaption:React.FC<{captions:Caption[];dark?:boolean}> = ({captions,dark=false}) => {
  const f=useCurrentFrame();
  const line=captions.find(c=>f*1000/30>=c.startMs&&f*1000/30<c.endMs);
  return line?<div data-caption style={{position:'absolute',left:94,right:94,bottom:174,textAlign:'center',fontSize:45,lineHeight:1.5,fontWeight:600,color:dark?'#fff':colors.ink,textShadow:dark?'0 2px 14px #0008':'0 1px 8px #ffffffaa',zIndex:20,whiteSpace:'pre-line'}}>{line.text}</div>:null;
};

export const Brand:React.FC<{dark?:boolean;size?:number}> = ({dark=false,size=39}) => <div style={{display:'flex',alignItems:'center',gap:14,fontSize:size,fontWeight:750,color:dark?'#fff':colors.ink}}><span style={{display:'inline-block',width:size,height:size,borderRadius:size*.28,background:colors.orange,rotate:'-8deg',boxShadow:'inset 0 0 0 2px #ffffff33'}}/><span>捷境</span></div>;

export const SourceFacts:React.FC<{large?:boolean}> = ({large=false}) => <div style={{fontSize:large?46:38,lineHeight:1.95}}>
  <div style={{display:'flex',justifyContent:'space-between',borderBottom:`1px solid ${colors.line}`}}><span style={{color:colors.muted}}>容量</span><b>500 mL</b></div>
  <div style={{display:'flex',justifyContent:'space-between',borderBottom:`1px solid ${colors.line}`}}><span style={{color:colors.muted}}>材质</span><b>不锈钢</b></div>
  <div style={{display:'flex',justifyContent:'space-between',borderBottom:`1px solid ${colors.line}`}}><span style={{color:colors.muted}}>颜色</span><b>橙色</b></div>
  <div style={{display:'flex',justifyContent:'space-between'}}><span style={{color:colors.muted}}>瓶盖</span><b>旋盖</b></div>
</div>;

export const DraftDocument:React.FC<{reveal?:number;compact?:boolean;edited?:boolean}> = ({reveal=1,compact=false,edited=false}) => <div style={{background:'#fffdf8',padding:compact?42:52,borderRadius:5,boxShadow:'0 24px 50px #13243516',border:'1px solid #d8d9d6'}}>
  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',paddingBottom:24,borderBottom:`2px solid ${colors.ink}`}}><Brand size={compact?30:36}/><span style={{fontSize:compact?26:32,color:colors.blue}}>商品内容 · 草稿</span></div>
  <div style={{fontSize:compact?25:32,color:colors.muted,marginTop:30,letterSpacing:3}}>TITLE</div>
  <div style={{fontFamily:'Arial, sans-serif',fontWeight:650,fontSize:compact?38:49,lineHeight:1.25,marginTop:14,minHeight:compact?132:180}}>{(edited?'500 ml Orange Stainless Steel Water Bottle with Screw Cap':'Orange Stainless Steel Water Bottle 500 ml with Screw Cap').slice(0,Math.round(reveal*70))}</div>
  <div style={{height:2,background:colors.line,margin:'24px 0'}}/>
  <div style={{opacity:Math.max(0,(reveal-.45)/.2),fontSize:compact?31:40,lineHeight:1.75}}>
    <b style={{color:colors.blue,fontSize:compact?26:32}}>商品要点</b>
    <div>500 ml capacity</div><div>Stainless steel body</div><div>Orange finish · Screw cap</div>
  </div>
  <div style={{opacity:Math.max(0,(reveal-.65)/.2),borderTop:`1px solid ${colors.line}`,paddingTop:24,marginTop:24,fontSize:compact?29:37,lineHeight:1.55}}>
    <b style={{fontSize:compact?26:32,color:colors.blue}}>描述</b>
    <p style={{margin:'12px 0 0'}}>A 500 ml stainless steel water bottle in orange, finished with a screw cap.</p>
  </div>
  <div style={{marginTop:35,fontSize:compact?25:31,color:colors.muted}}>可编辑　/　发布前核对</div>
</div>;
