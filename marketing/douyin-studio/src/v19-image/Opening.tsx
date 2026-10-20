import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Photo,Stage,Tag,move} from './Visual';
export const Opening=()=>{const f=useCurrentFrame();return <Stage dark>
  <div style={{position:'absolute',inset:'0 -180px 310px -180px',overflow:'hidden'}}><Photo kind="suitcase" style={{scale:move(f,0,100,1.17,1.04),translate:`${move(f,0,100,-45,20)}px 0px`}}/></div>
  <div style={{position:'absolute',inset:0,background:'linear-gradient(0deg,#102119 12%,#14271ce8 28%,transparent 66%)'}}/>
  <div style={{position:'absolute',left:86,top:118}}><Tag dark>捷境 AI 生图</Tag></div>
  <div style={{position:'absolute',left:86,top:965,translate:`0 ${move(f,0,14,32,0)}px`,opacity:move(f,0,10),fontSize:88,fontWeight:650,lineHeight:1.18,letterSpacing:-3}}>准备上架了，<br/><span style={{color:'#d2e1b6'}}>商品图还没做好？</span></div>
  <div style={{position:'absolute',left:86,right:90,top:1265,display:'flex',gap:20,translate:`0 ${move(f,10,30,80,0)}px`}}>
    <div style={{position:'relative',width:330,height:242,border:'5px solid #f4f6eb',rotate:'-5deg',boxShadow:'0 24px 50px #0005',background:'#f2eee2',color:'#304335',padding:30,boxSizing:'border-box'}}><div style={{fontSize:32,lineHeight:1.5}}>旅行收纳袋<br/>简洁 · 旅行感<br/><span style={{fontSize:26,color:'#71816d'}}>商品资料</span></div><Tag style={{position:'absolute',bottom:-21,left:14,fontSize:27,padding:'9px 17px'}}>没有原图</Tag></div>
    <div style={{position:'relative',width:330,height:242,border:'5px solid #f4f6eb',rotate:'5deg',translate:`${move(f,20,46,100,0)}px 40px`,opacity:move(f,16,38)}}><Photo kind="source"/><Tag style={{position:'absolute',bottom:-21,left:14,fontSize:27,padding:'9px 17px'}}>授权供应商图</Tag></div>
  </div>
 </Stage>};
