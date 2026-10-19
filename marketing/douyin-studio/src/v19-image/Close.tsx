import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Brand,Photo,Stage,move} from './Visual';
export const Close=()=>{const f=useCurrentFrame();return <Stage dark>
  <div style={{position:'absolute',top:0,left:-80,right:-80,height:1360,overflow:'hidden'}}><Photo kind="collection" style={{scale:move(f,0,130,1.12,1.02)}}/></div>
  <div style={{position:'absolute',inset:0,background:'linear-gradient(0deg,#192a22 29%,#192a22dd 45%,transparent 72%)'}}/>
  <div style={{position:'absolute',left:88,top:965}}><Brand white/></div>
  <div style={{position:'absolute',left:88,top:1100,fontSize:91,fontWeight:600,lineHeight:1.2}}>把商品图制作，<br/><span style={{color:'#d0dfb8'}}>交给 AI 帮忙。</span></div>
  <div style={{position:'absolute',left:92,top:1370,fontSize:62,letterSpacing:1,fontFamily:'Arial,sans-serif',color:'#fcfff3'}}>jiejing.shop</div>
  <div style={{position:'absolute',left:93,top:1490,fontSize:34,color:'#c5d0bd'}}>打开捷境 · 从商品资料或授权原图开始</div>
 </Stage>};
