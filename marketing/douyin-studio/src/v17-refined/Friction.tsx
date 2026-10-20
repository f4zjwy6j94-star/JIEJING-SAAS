import {useCurrentFrame} from 'remotion';
import {Stage,Heading,Paper,c,move} from './Shared';
export const RefinedFriction=()=>{const f=useCurrentFrame();return <Stage>
 <Heading top={205}>一件商品，<br/>反复准备。</Heading>
 <div style={{position:'absolute',left:121,top:581,width:752,height:746,borderRadius:28,background:'#dfe1d3',transform:'rotate(6deg)',boxShadow:'0 52px 100px #233f3225'}}/>
 <Paper title="选品：方向在哪？" lines={['需求值得看吗','同类商品怎么卖']} style={{left:139,top:568,width:670,transform:`rotate(${move(f,0,42,-10,-4)}deg) translateY(${move(f,0,24,65,0)}px)`}}/>
 <Paper title="资料：又翻了一遍" lines={['图片、链接、规格','散在几个地方']} style={{left:207,top:867,width:635,transform:`rotate(${move(f,20,65,13,4)}deg) translateX(${move(f,18,46,140,0)}px)`}}/>
 <Paper title="内容：还得重改" lines={['标题 / 商品描述 / 图片']} accent style={{left:114,top:1180,width:683,transform:`rotate(-4deg) translateY(${move(f,43,78,100,0)}px)`,opacity:move(f,37,50)}}/>
 <div style={{position:'absolute',left:779,top:567,width:117,height:117,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:80,background:c.coral,fontSize:85,transform:`rotate(${f*1.8}deg)`,boxShadow:'0 20px 36px #bd684b40'}}>↻</div>
</Stage>;};
