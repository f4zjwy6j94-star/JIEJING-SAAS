import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bottle,DraftDocument,Stage,colors,ease,VoiceCaption} from './Shared';

export const V18Draft:React.FC = () => {
 const f=useCurrentFrame();
 return <Stage dark>
  <div style={{position:'absolute',left:88,top:182,fontSize:86,fontWeight:800,lineHeight:1.22}}>标题、卖点、描述。<br/><span style={{color:'#f9b17b'}}>有了具体底稿。</span></div>
  <Bottle x={630} y={385} width={425} rotate={15} opacity={.58}/>
  <div style={{position:'absolute',left:77,top:ease(f,0,22,540,485),width:852,color:colors.ink,rotate:`${ease(f,0,40,-3,0)}deg`}}><DraftDocument reveal={ease(f,10,100)}/></div>
  <VoiceCaption dark captions={[{text:'标题、卖点、描述，\n先得到一份可编辑草稿。',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
