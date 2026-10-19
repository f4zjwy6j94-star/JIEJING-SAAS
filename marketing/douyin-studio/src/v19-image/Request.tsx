import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Brand,Cursor,Letter,Photo,Stage,Tag,move} from './Visual';
export const Request=()=>{const f=useCurrentFrame();return <Stage>
  <div style={{position:'absolute',left:86,top:120}}><Brand/></div>
  <div style={{position:'absolute',left:86,top:244,fontSize:90,fontWeight:650,lineHeight:1.16}}>有授权原图，<br/>直接说清需求。</div>
  <div style={{position:'absolute',left:84,top:528,width:850,height:635,rotate:`${move(f,0,26,-4,0)}deg`,boxShadow:'0 22px 60px #23322935',scale:move(f,0,28,.94,1)}}><Photo kind="source"/><Tag style={{position:'absolute',left:24,top:24}}>实拍图 / 授权供应商图</Tag></div>
  <div style={{position:'absolute',left:110,right:100,top:1095,padding:'32px 38px',border:'1px solid #9aaa91',borderRadius:26,background:'#fbfcf7',boxShadow:'0 24px 60px #22382633',translate:`0 ${move(f,8,35,90,0)}px`}}>
    <div style={{fontSize:30,color:'#687560',marginBottom:22}}>AI CEO · 画面需求</div>
    <div style={{fontSize:44,lineHeight:1.45,minHeight:130}}><Letter text="放进旅行箱的场景，保留商品外观。" start={18} end={72}/></div>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:24}}><Tag style={{fontSize:30}}>商品生图</Tag><div style={{background:'#344c3a',color:'#fff',padding:'17px 30px',borderRadius:35,fontSize:32}}>生成候选图 ↗</div></div>
  </div>
  <Cursor x={move(f,72,96,905,797)} y={move(f,72,96,1540,1388)} click={f>98&&f<112?move(f,98,112):0}/>
 </Stage>};
