import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, Stage} from './Design';

export const V15Confirm: React.FC = () => {
  const f=useCurrentFrame();
  const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
  return <Stage>
    <div style={{position:'absolute',left:85,top:220,fontSize:50,color:C.muted}}>当前先支持</div>
    <div style={{position:'absolute',left:79,top:320,fontSize:184,fontWeight:650,letterSpacing:-10,color:C.ivory}}>eBay</div>
    <div style={{position:'absolute',left:90,top:665,width:800,height:3,background:'#465044'}}/>
    <div style={{position:'absolute',left:90,top:788,fontSize:99,fontWeight:750,lineHeight:1.25}}>准备好，<br/><span style={{color:C.accent}}>由你确认。</span></div>
    <div style={{position:'absolute',left:95,top:1225,width:795,height:158,borderRadius:80,border:`2px solid ${C.accent}`,display:'flex',alignItems:'center',justifyContent:'space-between',padding:'0 50px',background:interpolate(f,[48,68],[0,1],clamp)>0.5?C.accent:'transparent',color:f>58?C.bg:C.accent,scale:interpolate(f,[48,54,62],[1,0.975,1],clamp)}}>
      <span style={{fontSize:47,fontWeight:700}}>发布前核对</span><span style={{fontSize:75}}>↗</span>
    </div>
    <svg width="65" height="83" viewBox="0 0 65 83" style={{position:'absolute',left:interpolate(f,[0,48],[965,780],clamp),top:interpolate(f,[0,48],[1490,1310],clamp),filter:'drop-shadow(0 6px 9px #0007)'}}><path d="M5 4L58 47L35 50L47 74L34 80L22 55L5 71Z" fill={C.ivory} stroke={C.bg} strokeWidth="4"/></svg>
  </Stage>;
};
