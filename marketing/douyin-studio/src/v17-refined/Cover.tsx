import {Stage,Mark,Bag,Paper,c} from './Shared';
export const V17RefinedCover=()=> <Stage dark>
 <div style={{position:'absolute',left:92,top:91}}><Mark dark/></div>
 <div style={{position:'absolute',left:86,top:229,fontSize:103,fontWeight:760,lineHeight:1.25,letterSpacing:-5}}>货有了。<br/><span style={{color:c.lime}}>上架，还在等？</span></div>
 <Paper title="商品资料" lines={['图片 / 规格 / 来源']} style={{left:151,top:598,width:430,transform:'rotate(-12deg)'}}/>
 <Paper title="上架草稿" lines={['可修改 · 待确认']} accent style={{left:517,top:733,width:348,transform:'rotate(10deg)'}}/>
 <div style={{position:'absolute',left:170,top:774}}><Bag size={676} id="cover"/></div>
</Stage>;
export const V17RefinedCoverHorizontal=()=> <Stage dark>
 <div style={{position:'absolute',left:92,top:84}}><Mark dark/></div>
 <div style={{position:'absolute',left:86,top:241,fontSize:92,fontWeight:760,lineHeight:1.28,letterSpacing:-4}}>货有了。<br/><span style={{color:c.lime}}>上架，<br/>还在等？</span></div>
 <Paper title="商品资料 → 上架草稿" lines={['调研 / 内容 / 素材','可修改 · 待确认']} style={{left:788,top:245,width:439,transform:'rotate(8deg)'}}/>
 <div style={{position:'absolute',left:710,top:463}}><Bag size={627} id="cover-horizontal"/></div>
 <div style={{position:'absolute',left:96,top:903,fontSize:35,color:'#edf2d7be'}}>捷境 · AI 电商工作台</div>
</Stage>;
