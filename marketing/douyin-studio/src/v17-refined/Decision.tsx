import {useCurrentFrame} from 'remotion';
import {Stage,Heading,Bag,c,move} from './Shared';
export const RefinedDecision=()=>{const f=useCurrentFrame();const edited=f>=48;return <Stage>
 <Heading top={181} size={88}>AI 做准备，<br/>决定权在你。</Heading>
 <div style={{position:'absolute',left:92,top:453,fontSize:40,color:'#567448'}}>目前先支持 eBay</div>
 <div style={{position:'absolute',left:93,top:643,width:779,height:782,background:'#fffdf7',padding:43,borderRadius:23,boxShadow:'15px 19px 0 #d4ddc6,0 46px 85px #28443020',transform:`perspective(1500px) rotateY(${move(f,0,38,-5,0)}deg)`}}>
  <div style={{fontSize:30,color:c.muted}}>商品内容草稿</div>
  <div style={{fontSize:52,fontWeight:700,marginTop:30}}>旅行收纳袋</div>
  <div style={{position:'absolute',right:0,top:20}}><Bag size={219} id="edit"/></div>
  <div style={{fontSize:27,color:c.muted,marginTop:58}}>英文标题</div>
  <div style={{fontFamily:'Arial,sans-serif',fontSize:40,fontWeight:500,marginTop:13,padding:'18px 14px',background:edited?'#dfeaaa7d':'#e7e9df',borderRadius:8,whiteSpace:'nowrap'}}>{edited?'Travel Packing Organizer':'Travel Storage Bag'}<span style={{opacity:f<95?1:0,color:'#71833e'}}>│</span></div>
  <div style={{fontSize:27,color:c.muted,marginTop:33}}>商品描述</div>
  <div style={{fontSize:33,marginTop:17,lineHeight:1.55}}>用于旅行物品分类收纳。<br/>规格与图片由你核对。</div>
  <div style={{display:'flex',gap:18,marginTop:43}}><div style={{fontSize:28,padding:'21px 27px',border:'1px solid #8a9b80',borderRadius:9}}>可继续修改</div><div style={{fontSize:28,padding:'21px 27px',background:c.ink,color:c.lime,borderRadius:9}}>确认后发布 ↗</div></div>
 </div>
 <svg width="67" height="87" viewBox="0 0 67 87" style={{position:'absolute',left:755,top:955,transform:`translate(${move(f,0,46,70,-33)}px,${move(f,0,46,130,0)}px)`}}><path d="M6 3 58 51 32 57 26 81Z" fill={c.coral} stroke="#fffbed" strokeWidth="4"/></svg>
</Stage>;};
