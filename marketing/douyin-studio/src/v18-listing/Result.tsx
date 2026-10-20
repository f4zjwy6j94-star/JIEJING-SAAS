import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bottle,DraftDocument,Stage,colors,ease,VoiceCaption} from './Shared';

export const V18Result:React.FC = () => {
 const f=useCurrentFrame();
 return <Stage>
  <div style={{position:'absolute',left:88,top:170,fontSize:80,fontWeight:800,lineHeight:1.25}}>最后得到的，<br/>是一份<span style={{color:colors.blue}}>可编辑草稿。</span></div>
  <div style={{position:'absolute',left:295,top:505,width:708,rotate:`${ease(f,0,85,5,0)}deg`,scale:ease(f,0,85,.96,1)}}><DraftDocument compact edited/></div>
  <Bottle x={-108} y={685} width={460} rotate={-12}/>
  <div style={{position:'absolute',left:322,top:1438,width:650,display:'flex',alignItems:'center',justifyContent:'space-between',borderTop:`2px solid ${colors.ink}`,paddingTop:26,fontSize:38}}><b>保存草稿</b><span style={{color:colors.muted}}>发布前，由你确认</span></div>
  <VoiceCaption captions={[{text:'从零散资料，到完整的上架准备。\n发布前，由你确认。',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
