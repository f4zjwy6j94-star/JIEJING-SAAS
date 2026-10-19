import {useCurrentFrame} from 'remotion';
import {Stage,Heading,Mark,Bag,Paper,c,move} from './Shared';
export const RefinedHook=()=>{const f=useCurrentFrame();return <Stage dark>
 <div style={{position:'absolute',left:92,top:122}}><Mark dark/></div>
 <Heading dark top={230}>货有了。<br/><span style={{color:c.lime}}>上架，还在等？</span></Heading>
 <div style={{position:'absolute',top:574,left:139,width:731,height:756,border:'1px solid #e1ecc23c',borderRadius:'380px 380px 50px 50px',background:'linear-gradient(155deg,#f7f2d412,#d2ecc705)',boxShadow:'inset 0 1px 0 #f6f4d32b'}}/>
 <Paper title="商品资料" lines={['收纳用品','图片 / 规格 / 来源']} style={{left:133,top:705,transform:`rotate(-15deg) translateY(${move(f,0,30,40,0)}px)`}}/>
 <Paper title="上架草稿" lines={['标题还没定','描述又要重写']} accent style={{left:503,top:880,transform:`rotate(12deg) translateY(${move(f,5,40,70,0)}px)`}}/>
 <div style={{position:'absolute',left:164,top:910,transform:`translateY(${move(f,0,100,30,-15)}px) scale(${move(f,0,136,.96,1.06)})`}}><Bag size={700} id="hook"/></div>
 <div style={{position:'absolute',top:1440,left:94,fontSize:43,color:'#e4edcbaa'}}>时间，都花在准备上。</div>
</Stage>;};
