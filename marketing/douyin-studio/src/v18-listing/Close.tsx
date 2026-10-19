import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Bottle,Brand,Stage,ease,VoiceCaption} from './Shared';

export const V18Close:React.FC = () => {
 const f=useCurrentFrame();
 return <Stage dark>
  <div style={{position:'absolute',left:90,top:170}}><Brand dark size={53}/></div>
  <div style={{position:'absolute',left:88,top:332,fontSize:105,fontWeight:800,lineHeight:1.2,letterSpacing:-3}}>带一个商品，<br/><span style={{color:'#ffa968'}}>把内容准备好。</span></div>
  <Bottle x={ease(f,0,70,590,550)} y={590} width={500} rotate={14}/>
  <div style={{position:'absolute',left:88,top:796,width:510,borderLeft:'3px solid #8b9cac',paddingLeft:35}}>
   <div style={{color:'#9eafbf',fontSize:29,letterSpacing:4}}>你将得到</div>
   <div style={{fontSize:48,lineHeight:1.85,marginTop:23}}>英文标题<br/>商品要点与描述<br/>可修改的草稿</div>
  </div>
  <div style={{position:'absolute',left:88,top:1340,fontSize:68,fontFamily:'Arial,sans-serif',fontWeight:600,letterSpacing:1}}>jiejing.shop</div>
  <div style={{position:'absolute',left:90,top:1455,color:'#b2c3d1',fontSize:42}}>AI 电商工作台 · 当前支持 eBay</div>
  <VoiceCaption dark captions={[{text:'捷境，当前支持 eBay。\n带一个商品，来试试。',startMs:0,endMs:13000,timestampMs:null,confidence:null}]}/>
 </Stage>;
};
