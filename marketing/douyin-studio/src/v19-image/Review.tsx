import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Photo,Stage,Tag,move} from './Visual';
export const Review=()=>{const f=useCurrentFrame();return <Stage>
  <div style={{position:'absolute',left:86,top:135,fontSize:87,lineHeight:1.18,fontWeight:650}}>好看之外，<br/>还要对照实物。</div>
  <div style={{position:'absolute',left:65,top:485,width:450,height:605,overflow:'hidden',boxShadow:'0 20px 40px #23382628'}}><Photo kind="source" style={{scale:move(f,0,95,1,1.12)}}/><Tag style={{position:'absolute',left:20,top:20}}>来源图</Tag></div>
  <div style={{position:'absolute',left:538,top:485,width:450,height:605,overflow:'hidden',boxShadow:'0 20px 40px #23382628',translate:`0 ${move(f,0,28,100,0)}px`}}><Photo kind="collection" style={{scale:move(f,0,95,1.12,1)}}/><Tag style={{position:'absolute',left:20,top:20}}>候选图</Tag></div>
  <div style={{position:'absolute',left:88,right:95,top:1185,display:'flex',flexDirection:'column',gap:28}}>{['款式与数量','配色与细节','图片权利与平台要求'].map((item,i)=><div key={item} style={{fontSize:42,paddingBottom:22,borderBottom:'1px solid #b7c2b0',display:'flex',alignItems:'center',justifyContent:'space-between',opacity:move(f,15+i*10,35+i*10)}}><span>{item}</span><span style={{fontSize:28,color:'#67725e'}}>待确认</span></div>)}</div>
 </Stage>};
