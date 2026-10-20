import React from 'react';
import {useVideoConfig} from 'remotion';
import {Brand,Photo,Stage,Tag} from './Visual';
export const Cover=()=>{const {width}=useVideoConfig();if(width===1280)return <Stage dark>
 <div style={{position:'absolute',left:508,top:-90,width:880,height:850}}><Photo kind="suitcase"/></div>
 <div style={{position:'absolute',inset:0,background:'linear-gradient(90deg,#192b22 35%,#192b22a8 52%,transparent 78%)'}}/>
 <div style={{position:'absolute',left:60,top:57}}><Brand white/></div>
 <div style={{position:'absolute',left:60,top:210,fontSize:71,fontWeight:700,lineHeight:1.23}}>商品图制作<br/><span style={{color:'#d7e5bd'}}>交给 AI 帮忙</span></div>
 <Tag dark style={{position:'absolute',left:60,top:479,fontSize:28}}>原图 + 需求 → 商品图候选</Tag>
 <div style={{position:'absolute',left:60,top:608,fontSize:29,color:'#d6dfcb'}}>场景图 / 陈列图 / 细节图</div>
 </Stage>;
 return <Stage dark>
 <div style={{position:'absolute',left:-170,right:-90,top:-70,height:1700}}><Photo kind="suitcase"/></div>
 <div style={{position:'absolute',inset:0,background:'linear-gradient(0deg,#192b22 21%,#192b22e8 38%,transparent 68%)'}}/>
 <div style={{position:'absolute',left:88,top:138}}><Brand white/></div>
 <div style={{position:'absolute',left:84,top:1000,fontSize:102,fontWeight:700,lineHeight:1.21}}>商品图制作<br/><span style={{color:'#d7e5bd'}}>交给 AI 帮忙</span></div>
 <Tag dark style={{position:'absolute',left:88,top:1300,fontSize:33}}>原图 + 需求 → 商品图候选</Tag>
 <div style={{position:'absolute',left:88,top:1450,fontSize:38,color:'#d9e3cf'}}>场景图 · 陈列图 · 细节图</div>
 <div style={{position:'absolute',left:89,top:1530,fontSize:38,color:'#f6f8ee'}}>jiejing.shop</div>
 </Stage>;
};
