import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bottle,Stage,SourceFacts,colors,ease,VoiceCaption} from './Shared';

export const V18Scattered:React.FC = () => {
 const f=useCurrentFrame();
 return <Stage>
  <div style={{position:'absolute',left:88,top:185,fontSize:92,fontWeight:800,lineHeight:1.2}}>一件新品，<br/>又从<span style={{color:colors.blue}}>空白页</span>开始。</div>
  <div style={{position:'absolute',left:50,top:505,width:455,height:690,background:'#e4ded4',rotate:`${ease(f,0,100,-9,-5)}deg`,boxShadow:'20px 22px 35px #11233720'}}>
   <div style={{padding:32,fontSize:32,color:colors.muted}}>商品图.jpg</div>
   <Bottle x={25} y={90} width={400} shadow={false}/>
  </div>
  <div style={{position:'absolute',left:440,top:570,width:545,padding:46,background:'#fffdfa',rotate:`${ease(f,0,100,7,2)}deg`,boxShadow:'-10px 25px 48px #15233125'}}>
   <div style={{fontSize:35,color:colors.blue,borderBottom:`2px solid ${colors.ink}`,paddingBottom:20,marginBottom:20}}>供应资料</div><SourceFacts/>
  </div>
  <div style={{position:'absolute',left:175,top:ease(f,45,95,1290,1160),width:740,height:250,background:colors.ink,padding:42,color:'#fff',boxShadow:'0 20px 45px #15233130',rotate:'-3deg'}}>
   <div style={{fontSize:27,color:'#aabacc',letterSpacing:5}}>ENGLISH DESCRIPTION</div>
   <div style={{fontSize:44,lineHeight:1.5,marginTop:30,color:'#dde2e9'}}>从标题到描述，<br/>还得重新写一遍<span style={{color:colors.orange}}>{f%28<14?' |':''}</span></div>
  </div>
  <VoiceCaption captions={[{text:'图片、参数，到英文介绍，\n又得从头整理。',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
