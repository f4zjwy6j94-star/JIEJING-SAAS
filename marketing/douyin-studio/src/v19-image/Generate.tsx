import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Brand,Photo,Stage,Tag,move} from './Visual';

export const Generate=()=>{
 const f=useCurrentFrame();const active=f<62?'suitcase':f<103?'collection':'detail';const phase=f<62?0:f<103?1:2;
 return <Stage>
  <div style={{position:'absolute',left:82,top:115}}><Brand/></div>
  <div style={{position:'absolute',left:82,top:235,fontSize:88,fontWeight:650,lineHeight:1.18}}>AI 生图，<br/><span style={{color:'#56764a'}}>让商品有更多画面。</span></div>
  <div style={{position:'absolute',left:60,right:60,top:515,height:852,overflow:'hidden',boxShadow:'0 35px 70px #26382f38',rotate:`${move(f,0,23,3,0)}deg`}}><Photo kind={active} style={{scale:move(f%62,0,62,1.09,1.01)}}/><Tag style={{position:'absolute',right:26,top:26,fontSize:27}}>构图示例</Tag></div>
  <div style={{position:'absolute',left:88,top:1187,width:276,height:219,padding:7,background:'#fbfcf4',rotate:'-6deg',boxShadow:'0 20px 40px #18251c4d',translate:`0 ${move(f,0,24,45,0)}px`}}><Photo kind="source"/><Tag style={{position:'absolute',left:16,bottom:-23,fontSize:26,padding:'8px 18px'}}>商品原图</Tag></div>
  <div style={{position:'absolute',left:404,top:1375,fontSize:33,color:'#4d6153',letterSpacing:1}}>需求驱动 · 生成候选</div>
  <div style={{position:'absolute',left:87,right:87,top:1500,display:'flex',justifyContent:'space-between'}}><Tag dark={phase===0}>场景图</Tag><Tag dark={phase===1}>陈列图</Tag><Tag dark={phase===2}>细节图</Tag></div>
 </Stage>;
};
