import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Photo,Stage,Tag,move} from './Visual';

export const Expansion=()=>{const f=useCurrentFrame();return <Stage dark>
 <div style={{position:'absolute',left:82,top:128,fontSize:40,color:'#ceddb9'}}>商品生图示例</div>
 <div style={{position:'absolute',left:82,top:228,fontSize:86,fontWeight:650,lineHeight:1.18}}>从原图出发，<br/>拓展画面可能。</div>
 <div style={{position:'absolute',left:86,top:545,width:366,height:285,border:'6px solid #f6f8eb',boxShadow:'0 24px 55px #0006',rotate:'-5deg'}}><Photo kind="source"/><Tag style={{position:'absolute',top:20,left:20,fontSize:27}}>原图</Tag></div>
 <svg style={{position:'absolute',left:440,top:640}} width="525" height="680" viewBox="0 0 525 680"><path d="M5 40C150 40 70 160 170 175M5 40C200 40 160 400 90 435M5 40C280 40 180 530 300 545" fill="none" stroke="#acc798" strokeWidth="3" strokeDasharray="850" strokeDashoffset={850*(1-move(f,4,47))}/></svg>
 <div style={{position:'absolute',left:548,top:578,width:407,height:326,border:'5px solid #eff4e4',rotate:`${move(f,4,32,0,5)}deg`,translate:`${move(f,4,32,-95,0)}px ${move(f,4,32,-20,0)}px`,opacity:move(f,4,20),boxShadow:'0 22px 65px #0007'}}><Photo kind="suitcase"/><Tag dark style={{position:'absolute',bottom:16,left:16,fontSize:28}}>场景</Tag></div>
 <div style={{position:'absolute',left:107,top:971,width:495,height:403,border:'5px solid #eff4e4',rotate:`${move(f,14,42,0,-4)}deg`,translate:`0 ${move(f,14,42,-135,0)}px`,opacity:move(f,14,29),boxShadow:'0 22px 65px #0007'}}><Photo kind="collection"/><Tag dark style={{position:'absolute',bottom:16,left:16,fontSize:28}}>陈列</Tag></div>
 <div style={{position:'absolute',left:574,top:1136,width:400,height:322,border:'5px solid #eff4e4',rotate:`${move(f,24,53,0,7)}deg`,translate:`0 ${move(f,24,53,-160,0)}px`,opacity:move(f,24,42),boxShadow:'0 22px 65px #0007'}}><Photo kind="detail"/><Tag dark style={{position:'absolute',bottom:16,left:16,fontSize:28}}>细节</Tag></div>
 </Stage>};
