import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bottle,Stage,colors,ease,VoiceCaption} from './Shared';

export const V18Hook:React.FC = () => {
 const f=useCurrentFrame();
 return <Stage dark>
  <div style={{position:'absolute',left:90,top:172,fontSize:43,color:'#c4ced8'}}>跨境卖家的上架前一刻</div>
  <div style={{position:'absolute',left:86,top:270,fontSize:112,fontWeight:850,lineHeight:1.17,letterSpacing:-4}}>货备好了。<br/><span style={{color:'#ffa968'}}>文案呢？</span></div>
  <div style={{position:'absolute',right:-90,top:580,width:620,height:785,background:'#f5f3ee',color:colors.ink,rotate:`${ease(f,0,80,9,5)}deg`,boxShadow:'-15px 26px 60px #0006',padding:55}}>
   <div style={{fontSize:32,letterSpacing:5,color:colors.muted}}>PRODUCT TITLE</div>
   <div style={{height:155,marginTop:40,borderBottom:'2px solid #bec8cc',fontSize:74,color:colors.muted}}>{Math.floor(f/14)%2===0?'|':''}</div>
   <div style={{fontSize:42,marginTop:65,color:'#8b969e'}}>卖点还没整理</div>
   <div style={{height:2,background:'#d7dcd9',marginTop:30}}/>
   <div style={{fontSize:42,marginTop:45,color:'#8b969e'}}>描述还在等</div>
  </div>
  <Bottle x={ease(f,0,70,-68,4)} y={ease(f,0,70,645,608)} width={610} rotate={ease(f,0,75,-17,-10)}/>
  <div style={{position:'absolute',left:98,top:1480,color:'#b6c8d7',fontSize:34,letterSpacing:4}}>有商品，也要有讲清它的内容。</div>
  <VoiceCaption dark captions={[{text:'货都备好了，\n上架还卡在写文案？',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
