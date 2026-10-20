import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Photo,Stage,Tag,move} from './Visual';
export const Candidates=()=>{const f=useCurrentFrame();return <Stage dark>
  <div style={{position:'absolute',left:86,top:136,fontSize:86,fontWeight:600,lineHeight:1.18}}>一份商品，<br/><span style={{color:'#dce8c4'}}>不同画面用途。</span></div>
  <div style={{position:'absolute',left:118,top:498,width:820,height:650,rotate:`${move(f,0,38,-8,-3)}deg`,translate:`${move(f,0,38,-100,0)}px 0px`,boxShadow:'0 30px 80px #0008'}}><Photo kind="suitcase"/><Tag dark style={{position:'absolute',left:24,top:24}}>场景候选 · 待核对</Tag></div>
  <div style={{position:'absolute',left:480,top:995,width:490,height:410,rotate:`${move(f,12,48,12,6)}deg`,translate:`0 ${move(f,12,48,220,0)}px`,opacity:move(f,12,40),border:'6px solid #f4f4e9',boxShadow:'0 22px 65px #0007'}}><Photo kind="detail"/></div>
  <div style={{position:'absolute',left:87,top:1245,width:355,fontSize:42,lineHeight:1.48,opacity:move(f,32,54)}}>想更近一点？<br/><span style={{color:'#c8d7b7'}}>继续改构图需求。</span></div>
 </Stage>};
