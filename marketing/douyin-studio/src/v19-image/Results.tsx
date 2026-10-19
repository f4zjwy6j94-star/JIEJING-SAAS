import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Photo,Stage,Tag,move} from './Visual';
export const Results=()=>{const f=useCurrentFrame();const active=f<72?'collection':f<104?'packing':'detail';const current=f<72?0:f<104?1:2;return <Stage>
  <div style={{position:'absolute',left:86,top:125,fontSize:49,fontWeight:500}}>看这组收纳袋示例</div>
  <div style={{position:'absolute',left:86,top:220,fontSize:88,fontWeight:650,lineHeight:1.15}}>{f<72?'整套，先看清。':f<104?'用法，看得见。':'细节，拉近看。'}</div>
  <div style={{position:'absolute',left:60,right:60,top:465,height:870,overflow:'hidden',boxShadow:'0 36px 75px #23392b2c',rotate:`${move(f,0,20,-2,0)}deg`}}><Photo kind={active} style={{scale:1.04+(.035*(f%54)/54)}}/></div>
  <div style={{position:'absolute',left:86,right:86,top:1410,display:'flex',justifyContent:'space-between',gap:15}}>{['整套陈列','使用场景','细节特写'].map((label,i)=><Tag key={label} dark={current===i} style={{fontSize:32,padding:'16px 23px'}}>{label}</Tag>)}</div>
 </Stage>};
