import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Brand,Cursor,Photo,Stage,Tag,move} from './Visual';
export const Handoff=()=>{const f=useCurrentFrame();return <Stage>
  <div style={{position:'absolute',left:86,top:165,fontSize:88,fontWeight:650,lineHeight:1.16}}>核对后选图，<br/>带回商品草稿。</div>
  <div style={{position:'absolute',left:130,top:460,width:805,height:1000,padding:42,boxSizing:'border-box',background:'#fcfdf7',boxShadow:'0 30px 75px #22352626',border:'1px solid #bdc8b6',borderRadius:9}}><Brand/><div style={{fontSize:29,color:'#65745d',marginTop:24,borderBottom:'1px solid #b4c1a9',paddingBottom:22}}>Listing · 可编辑草稿</div>
    <div style={{height:498,marginTop:30,overflow:'hidden',background:'#e2e7dd'}}><Photo kind="collection" style={{opacity:move(f,34,57)}}/></div>
    <div style={{fontSize:47,fontFamily:'Arial,sans-serif',fontWeight:600,lineHeight:1.25,marginTop:28}}>Travel Packing<br/>Cube Set</div><div style={{fontSize:30,color:'#667960',marginTop:20}}>与当前商品资料关联</div>
  </div>
  <div style={{position:'absolute',left:move(f,0,48,40,172),top:move(f,0,48,805,680),width:move(f,0,48,590,719),height:move(f,0,48,460,498),rotate:`${move(f,0,48,-8,0)}deg`,opacity:1-move(f,49,61),boxShadow:'0 18px 55px #17251944',zIndex:4}}><Photo kind="collection"/></div>
  <Tag style={{position:'absolute',left:209,top:1500,fontSize:36,opacity:move(f,46,70)}}>商品资料与候选图，在一起</Tag>
  <Cursor x={move(f,0,45,579,790)} y={move(f,0,45,1035,1130)}/>
 </Stage>};
