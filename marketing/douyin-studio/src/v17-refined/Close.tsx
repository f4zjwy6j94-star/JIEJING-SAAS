import {useCurrentFrame} from 'remotion';
import {Stage,Heading,Bag,Paper,c,move} from './Shared';
export const RefinedClose=()=>{const f=useCurrentFrame();return <Stage dark>
 <Heading dark top={195} size={88}>把反复准备，<br/><span style={{color:c.lime}}>变成下一步。</span></Heading>
 <Paper title="商品内容草稿" lines={['旅行收纳袋','标题 / 描述 / 属性','可修改 · 待你确认']} style={{left:474,top:596,width:382,transform:`rotate(8deg) translateY(${move(f,0,50,42,0)}px)`}}/>
 <div style={{position:'absolute',left:100,top:693,transform:`scale(${move(f,0,173,.97,1.03)})`}}><Bag size={575} id="close" angle={-10}/></div>
 <div style={{position:'absolute',top:1220,left:92,right:118,height:1,background:'#dfeaaa59'}}/>
 <div style={{position:'absolute',top:1252,left:92,color:c.paper,fontSize:49,fontWeight:700}}>捷境<span style={{fontSize:28,marginLeft:22,fontWeight:400}}>AI 电商工作台</span></div>
 <div style={{position:'absolute',left:90,top:1350,fontFamily:'Arial,sans-serif',fontSize:85,fontWeight:550,letterSpacing:-3,color:c.lime}}>jiejing.shop <span style={{fontSize:51}}>↗</span></div>
 <div style={{position:'absolute',left:96,top:1480,fontSize:36,color:'#f1f4d6ad',opacity:move(f,106,118)}}>带上商品资料，了解工作流程。</div>
</Stage>;};
