import {useCurrentFrame} from 'remotion';
import {Stage,Heading,Bag,c,move} from './Shared';
export const RefinedConnected=()=>{const f=useCurrentFrame();return <Stage>
 <Heading top={174} size={88}>一份商品资料，<br/><span style={{color:'#57764e'}}>接着往下做。</span></Heading>
 <div style={{position:'absolute',left:78,top:559,width:803,height:894,background:'#fffdf6',borderRadius:25,boxShadow:'20px 22px 0 #c7d2b73d,0 35px 70px #264e3d20',transform:`rotate(${move(f,0,125,-2,1)}deg)`}}>
  <div style={{position:'absolute',left:36,top:29,fontSize:28,color:c.muted}}>商品准备工作流</div>
  <div style={{position:'absolute',left:506,top:16}}><Bag id="flow" size={207}/></div>
  <div style={{position:'absolute',left:62,top:203,height:559,width:3,background:'#d8dfd0'}}/>
  <div style={{position:'absolute',left:62,top:203,height:move(f,3,119,0,559),width:5,background:'#718c52'}}/>
  {[['调研','选品方向与依据'],['商品内容','标题、描述、属性草稿'],['图片与视频','图片方案、视频脚本']].map(([name,detail],i)=><div key={name} style={{position:'absolute',left:30,top:190+i*213,width:724,opacity:move(f,i*26,i*26+16,.3,1),transform:`translateX(${move(f,i*26,i*26+25,24,0)}px)`}}><div style={{position:'absolute',top:15,left:12,width:42,height:42,borderRadius:30,background:f>i*26?c.lime:'#e1e5d9',border:'7px solid #fdfcf4'}}/><div style={{marginLeft:101,padding:'0 0 32px',borderBottom:i<2?'1px solid #d1d8c9':'none'}}><div style={{fontSize:47,fontWeight:730}}>{name}</div><div style={{fontSize:34,marginTop:21,color:c.muted}}>{detail}</div></div></div>)}
 </div>
</Stage>;};
