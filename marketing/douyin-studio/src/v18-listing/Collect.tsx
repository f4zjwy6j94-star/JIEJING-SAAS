import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bottle,Brand,Cursor,Stage,SourceFacts,colors,ease,VoiceCaption} from './Shared';

export const V18Collect:React.FC = () => {
 const f=useCurrentFrame(); const p=ease(f,12,52);const hit=ease(f,80,100);
 return <Stage>
  <div style={{position:'absolute',left:88,top:164}}><Brand size={46}/></div>
  <div style={{position:'absolute',left:88,top:270,fontSize:92,fontWeight:800,lineHeight:1.18}}>资料进来，<br/>内容<span style={{color:colors.blue}}>接着做。</span></div>
  <div style={{position:'absolute',left:65,top:580,width:950,height:880,background:'#fffdfa',boxShadow:'0 30px 90px #15233118',borderTop:`6px solid ${colors.blue}`}}>
   <div style={{padding:'34px 44px',fontSize:42,borderBottom:`1px solid ${colors.line}`}}>商品内容 <span style={{color:colors.muted,fontSize:31,marginLeft:20}}>整理上架草稿</span></div>
   <div style={{position:'absolute',left:45,top:140,width:345,height:505,background:'#edf0f1',border:`2px dashed ${p>.9?'#7199b6':'#b6c3cb'}`,borderRadius:12}}/>
   <Bottle x={ease(f,12,52,-180,42)} y={ease(f,12,52,-120,140)} width={350} rotate={ease(f,12,52,-16,0)} shadow={false}/>
   <div style={{position:'absolute',left:435,top:178,width:460,opacity:ease(f,28,60)}}><SourceFacts large/></div>
   <div style={{position:'absolute',left:45,top:683,width:850,height:106,background:hit>.1?'#1b4b7d':colors.blue,color:'#fff',fontSize:43,borderRadius:10,display:'flex',alignItems:'center',justifyContent:'center',scale:hit>.01&&hit<.8?.985:1}}>{hit>.3?'正在整理内容…':'生成草稿'}</div>
   <Cursor x={ease(f,60,83,770,650)} y={ease(f,60,83,565,730)} click={f>=84&&f<102?(f-84)/18:0} dark/>
  </div>
  <VoiceCaption captions={[{text:'在捷境，把商品资料\n交给商品内容模块。',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
