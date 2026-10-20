import {useCurrentFrame} from 'remotion';
import {Stage,Heading,Bag,c,move} from './Shared';
export const RefinedReveal=()=>{const f=useCurrentFrame();return <Stage dark>
 <Heading dark top={165} size={145}>捷境</Heading>
 <div style={{position:'absolute',left:93,top:374,fontSize:55,lineHeight:1.45,color:c.lime}}>面向跨境卖家的<br/>AI 电商工作台</div>
 <div style={{position:'absolute',left:89,top:703,right:104,padding:42,borderRadius:30,background:'#f6f4e9',color:c.ink,boxShadow:'0 44px 120px #0004',transform:`perspective(1600px) rotateY(${move(f,0,60,-7,0)}deg) translateY(${move(f,0,30,35,0)}px)`}}>
  <div style={{fontSize:28,letterSpacing:3,color:c.muted}}>从你的经营目标开始</div>
  <div style={{fontSize:45,lineHeight:1.5,fontWeight:650,marginTop:25,maxWidth:580}}>我有商品资料，<br/>想准备上架内容。</div>
  <div style={{height:2,background:'#b8c6b2',margin:'37px 0'}}/>
  <div style={{fontSize:41,color:'#46664e'}}>整理资料 → 准备草稿</div>
  <div style={{fontSize:32,marginTop:22,color:c.muted}}>沿着同一件商品，继续往下做。</div>
 </div>
 <div style={{position:'absolute',left:581,top:1160,transform:`translateY(${move(f,0,130,20,-17)}px)`}}><Bag size={385} id="reveal" angle={7}/></div>
 <div style={{position:'absolute',left:101,top:1405,fontSize:40,color:'#f1f3d4c5'}}>资料、内容、素材，彼此衔接。</div>
</Stage>;};
