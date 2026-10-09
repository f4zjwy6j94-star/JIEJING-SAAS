import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, Stage} from './Design';

export const V15Closing: React.FC = () => {
  const f=useCurrentFrame();
  const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
  return <Stage dark={false}>
    {/* Existing first-party logo geometry from assets/jiejing-logo-mark.svg. */}
    <svg width="610" height="610" viewBox="95 60 325 355" style={{position:'absolute',left:218,top:170,opacity:interpolate(f,[0,16],[0,1],clamp),translate:interpolate(f,[0,28],['0px 30px','0px 0px'],clamp)}}>
      <defs><linearGradient id="v15-gold" x1="334" y1="112" x2="366" y2="152" gradientUnits="userSpaceOnUse"><stop stopColor="#E5B149"/><stop offset="1" stopColor="#C48A23"/></linearGradient></defs>
      <path d="M160 348C173 260 229 204 332.5 141C275 175 262 251 354 337.5C282.5 304.5 229.5 314.5 160 348Z" fill="#181A19"/>
      <path d="M231 335.5C246.5 273 274 222 322.5 175C283.5 230 274 277 300 332C276 323.5 257 326.5 231 335.5Z" fill={C.ivory}/>
      <circle cx="348" cy="133" r="18" fill="url(#v15-gold)"/><circle cx="342.2" cy="126.7" r="4.2" fill="#F7D783" fillOpacity="0.9"/>
    </svg>
    <div style={{position:'absolute',left:84,right:100,top:790,fontSize:150,fontWeight:800,letterSpacing:15,color:C.bg}}>捷境</div>
    <div style={{position:'absolute',left:90,top:1035,fontSize:75,fontWeight:650,letterSpacing:-2,color:C.bg}}>jiejing.shop <span style={{fontSize:60,color:'#587347'}}>↗</span></div>
    <div style={{position:'absolute',left:92,top:1190,fontSize:46,color:'#5a6854',lineHeight:1.5}}>带上你的商品资料<br/>从上架准备开始</div>
  </Stage>;
};
