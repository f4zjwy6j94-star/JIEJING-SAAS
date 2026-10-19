import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Brand,Photo,Stage,Tag,move} from './Visual';

export const Benefit=()=>{const f=useCurrentFrame();return <Stage>
 <div style={{position:'absolute',left:84,top:125}}><Brand/></div>
 <div style={{position:'absolute',left:84,top:256,fontSize:92,fontWeight:650,lineHeight:1.2}}>先让 AI 出图，<br/><span style={{color:'#55704c'}}>再按需求调整。</span></div>
 <div style={{position:'absolute',left:84,top:575,width:878,height:612,overflow:'hidden',borderRadius:5,boxShadow:'0 32px 70px #263a2f3d'}}><Photo kind="packing" style={{scale:move(f,0,140,1.13,1.02)}}/></div>
 <div style={{position:'absolute',left:555,top:994,width:410,height:292,border:'6px solid #fbf9ee',rotate:`${move(f,10,43,-7,4)}deg`,translate:`0 ${move(f,10,43,100,0)}px`,boxShadow:'0 24px 60px #1a2d204d'}}><Photo kind="detail"/></div>
 <div style={{position:'absolute',left:84,top:1370,fontSize:41,lineHeight:1.7,color:'#47584b',opacity:move(f,17,38)}}>少做从零构图<br/>少花时间反复找背景</div>
 <Tag style={{position:'absolute',left:84,top:1210,fontSize:31}}>商品图片制作 · 捷境 AI</Tag>
 </Stage>};
