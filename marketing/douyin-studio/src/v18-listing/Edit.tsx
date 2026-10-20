import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Brand,Cursor,Stage,colors,ease,typed,VoiceCaption} from './Shared';

export const V18Edit:React.FC = () => {
 const f=useCurrentFrame(); const chosen=f>25&&f<48;const edited=f>=48;const prefix=edited?typed('500 ml ',f,48,70):'';
 return <Stage>
  <div style={{position:'absolute',left:88,top:185,fontSize:94,fontWeight:800,lineHeight:1.2}}>你要改的，<br/><span style={{color:colors.blue}}>就在这里改。</span></div>
  <div style={{position:'absolute',left:45,top:505,width:990,height:535,background:'#fffdfa',padding:'48px 42px',boxShadow:'0 25px 70px #0e294822',borderLeft:`5px solid ${colors.orange}`}}>
   <Brand size={32}/><div style={{fontSize:33,color:colors.muted,marginTop:30}}>英文标题</div>
   <div style={{fontSize:52,lineHeight:1.4,fontFamily:'Arial,sans-serif',marginTop:25,fontWeight:650}}><span style={{color:colors.blue}}>{prefix}</span><span style={{background:chosen?'#bad9f3':'transparent'}}>Orange Stainless Steel Water Bottle{!edited?' 500 ml':''} with Screw Cap</span><span style={{color:colors.blue}}>{f<74&&f%20<10?'|':''}</span></div>
   <div style={{fontSize:31,color:colors.muted,marginTop:30}}>调整顺序，保留商品事实。</div>
   <Cursor x={ease(f,0,25,790,240)} y={ease(f,0,25,350,238)} click={f>=24&&f<40?(f-24)/16:0}/>
  </div>
  <div style={{position:'absolute',left:90,top:1150,width:900}}>
   <div style={{fontSize:38,color:colors.muted,marginBottom:30}}>与原始资料再核对</div>
   <div style={{display:'flex',gap:24}}>{['500 mL','不锈钢','橙色'].map((t,i)=><div key={t} style={{flex:1,fontSize:43,fontWeight:650,padding:'22px 0',borderTop:`3px solid ${f>80+i*10?colors.blue:colors.line}`,opacity:ease(f,72+i*10,91+i*10)}}><span style={{color:colors.blue,marginRight:12}}>✓</span>{t}</div>)}</div>
  </div>
  <VoiceCaption captions={[{text:'哪句不合适，直接改。\n规格再核对一遍。',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
