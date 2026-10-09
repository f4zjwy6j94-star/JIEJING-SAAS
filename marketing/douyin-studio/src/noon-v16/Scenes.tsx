import React from 'react';
import {useCurrentFrame} from 'remotion';
import {C,Cursor,DrainPad,Logo,move,Paper,Set} from './Objects';

export const V16Conflict:React.FC = () => {
  const f=useCurrentFrame();
  return <Set>
    <div style={{position:'absolute',left:90,top:190,fontSize:51,fontWeight:500}}>同一个商品，两个尺寸？</div>
    <div style={{position:'absolute',left:72,top:320,fontSize:240,lineHeight:1,fontFamily:'Arial, sans-serif',fontWeight:800,letterSpacing:-20,translate:`${move(f,0,22,-18,0)}px 0px`}}>11.5<span style={{fontSize:56,letterSpacing:0,marginLeft:24}}>cm</span></div>
    <DrainPad id="hook" size={960} tilt={move(f,0,88,54,22)} spin={move(f,0,88,-29,-15)} style={{position:'absolute',left:25,top:470,translate:`0px ${move(f,0,45,45,-20)}px`}}/>
    <div style={{position:'absolute',left:480,top:1210,fontSize:224,fontWeight:800,lineHeight:1,fontFamily:'Arial, sans-serif',letterSpacing:-14,color:C.red,rotate:`${move(f,0,50,5,-4)}deg`}}>20<span style={{fontSize:50,letterSpacing:0,marginLeft:20}}>cm</span></div>
    <div style={{position:'absolute',left:94,top:1485,fontSize:39,color:C.muted}}>资料图 ↔ 参数表</div>
  </Set>;
};

export const V16Stop:React.FC = () => {
  const f=useCurrentFrame();
  return <Set dark>
    <Paper label="商品资料图" number="11.5" angle={-12} style={{position:'absolute',left:-35,top:290,scale:.95,translate:`${move(f,0,25,-90,0)}px 0px`}}/>
    <Paper label="商品参数表" number="20" angle={10} style={{position:'absolute',left:430,top:980,scale:.95,translate:`${move(f,0,25,90,0)}px 0px`}}/>
    <div style={{position:'absolute',left:84,top:700,fontSize:155,fontWeight:850,letterSpacing:-8,textShadow:'0 10px 25px #152936'}}>先别抄。</div>
    <div style={{position:'absolute',left:85,top:914,width:move(f,5,23,0,610),height:14,background:'#f29a6c',rotate:'-3deg'}}/>
    <Cursor x={move(f,0,43,620,350)} y={move(f,0,43,1200,970)} rotate={-10}/>
  </Set>;
};

export const V16Separate:React.FC = () => {
  const f=useCurrentFrame();
  return <Set>
    <div style={{position:'absolute',left:84,top:200,fontSize:86,fontWeight:800,lineHeight:1.25}}>先问清<br/><span style={{color:C.red}}>量的是哪里</span></div>
    <div style={{position:'absolute',left:120,top:645,width:810,height:640,transform:'perspective(1500px) rotateX(15deg) rotateZ(-6deg)'}}>
      <div style={{position:'absolute',left:180,top:230,width:560,height:440,background:'linear-gradient(120deg,#c3a784,#a58764)',boxShadow:'28px 35px 40px #554b3b40',border:'2px solid #9d835f',translate:`${move(f,0,90,0,70)}px ${move(f,0,90,0,50)}px`}}>
        <div style={{position:'absolute',left:247,top:0,width:52,height:438,background:'#e0cda87a',borderLeft:'1px solid #b3976e',borderRight:'1px solid #b3976e'}}/>
        <div style={{position:'absolute',left:24,top:286,fontSize:45,color:'#594a35'}}>包装尺寸？</div>
      </div>
      <DrainPad id="separate" size={640} tilt={24} spin={move(f,0,90,-10,-24)} style={{position:'absolute',left:-100,top:-20,translate:`${move(f,0,90,0,-15)}px ${move(f,0,90,0,-35)}px`}}/>
    </div>
    <div style={{position:'absolute',left:117,top:560,fontSize:49,color:C.blue}}>实物尺寸？</div>
    <svg width="900" height="350" viewBox="0 0 900 350" style={{position:'absolute',left:80,top:1280}}><path d="M25 95V170H730V95" fill="none" stroke={C.ink} strokeWidth="3"/><path d="M28 170l18-10v20M727 170l-18-10v20" fill={C.ink}/><text x="290" y="240" fill={C.ink} fontSize="46">两项分别确认</text></svg>
  </Set>;
};

export const V16Evidence:React.FC = () => {
  const f=useCurrentFrame();
  return <Set dark>
    <DrainPad id="evidence" size={900} tilt={move(f,0,85,15,5)} spin={move(f,0,85,8,0)} style={{position:'absolute',left:34,top:240,opacity:.85}}/>
    <div style={{position:'absolute',left:100,top:298,width:785,height:840,border:'3px solid #c9d4d680',borderRadius:40}}>
      {[[0,0],[690,0],[0,746],[690,746]].map(([x,y],i)=><div key={i} style={{position:'absolute',left:x-3,top:y-3,width:98,height:98,border:'8px solid #fff5df',borderRadius:14}}/>)}
      <div style={{position:'absolute',left:move(f,0,22,870,82),top:660,width:670,height:100,background:'#cda56a',rotate:`${move(f,0,22,-24,-8)}deg`,boxShadow:'0 15px 25px #071a2477'}}>
        {Array.from({length:34},(_,i)=><div key={i} style={{position:'absolute',left:15+i*19,top:0,width:2,height:i%5===0?48:26,background:'#665033'}}/>)}
      </div>
    </div>
    <div style={{position:'absolute',left:82,top:1220,fontSize:103,fontWeight:800,lineHeight:1.25}}>要一张<br/><span style={{color:'#f4b177'}}>实测图。</span></div>
    <div style={{position:'absolute',left:90,top:1510,fontSize:42,color:'#b9cacd'}}>让尺子和商品一起入镜</div>
  </Set>;
};

export const V16Sources:React.FC = () => {
  const f=useCurrentFrame();
  const p=move(f,30,65,0,1);
  return <Set>
    <div style={{position:'absolute',left:87,top:204,fontSize:89,fontWeight:800,lineHeight:1.3}}>原资料保留<br/>草稿接着做</div>
    <div style={{position:'absolute',left:80,top:move(f,0,24,520,490),width:790,height:900,background:'#365669',borderRadius:16,boxShadow:'16px 38px 65px #19334055',rotate:'-5deg'}}/>
    <Paper label="原始资料 · 01" number="11.5" angle={move(f,0,65,-13,-3)} style={{position:'absolute',left:move(f,0,65,-75,103),top:move(f,0,65,740,550),scale:move(f,0,65,1,.89)}}/>
    <Paper label="原始资料 · 02" number="20" angle={move(f,0,65,12,2)} style={{position:'absolute',left:move(f,0,65,455,147),top:move(f,0,65,920,605),scale:move(f,0,65,1,.89)}}/>
    <div style={{position:'absolute',left:80,top:1160,width:790,height:315,background:'linear-gradient(#31566d,#24475d)',borderRadius:'8px 8px 18px 18px',boxShadow:'0 -5px 12px #152f3933',rotate:'-5deg'}}>
      <div style={{padding:'74px 45px',color:'#ecf0e8',fontSize:50,fontWeight:700}}>商品工作资料 <span style={{opacity:p}}>✓</span></div>
    </div>
    <div style={{position:'absolute',left:410,top:1540,opacity:p,fontSize:38,color:C.blue}}>来源不丢，内容可改</div>
  </Set>;
};

export const V16Draft:React.FC = () => {
  const f=useCurrentFrame();
  const text='软胶排水过滤垫';
  return <Set>
    <div style={{position:'absolute',left:85,top:208,fontSize:88,fontWeight:800}}>这格，先留空。</div>
    <div style={{position:'absolute',left:82,top:430,width:796,height:1005,background:'#fffdf7',borderRadius:12,boxShadow:'20px 35px 65px #26373525',transform:`perspective(1800px) rotateY(${move(f,0,110,8,0)}deg)`,padding:55}}>
      <div style={{display:'flex',alignItems:'center',gap:18,borderBottom:'1px solid #cfd5d2',paddingBottom:30}}><Logo size={65}/><span style={{fontSize:35,color:C.muted}}>捷境 · 商品草稿</span></div>
      <div style={{fontSize:33,color:C.muted,marginTop:40}}>标题</div>
      <div style={{fontSize:55,fontWeight:750,marginTop:16,height:95}}>{text.slice(0,Math.floor(move(f,0,36,0,text.length)))}<span style={{opacity:f<36?1:0,color:C.red}}>|</span></div>
      <div style={{height:1,background:'#d6d9d2'}}/>
      <div style={{fontSize:33,color:C.muted,marginTop:38}}>尺寸</div>
      <div style={{marginTop:20,height:145,border:'3px dashed #c77347',background:'#faf0dc',padding:'35px 24px',display:'flex',justifyContent:'space-between',alignItems:'center'}}><span style={{fontSize:48,color:'#895335'}}>待核实</span><span style={{fontSize:50,color:'#895335'}}>—</span></div>
      <div style={{marginTop:38,fontSize:36,color:C.muted}}>原始来源</div>
      <div style={{display:'flex',gap:20,marginTop:21}}>{['资料图','参数表'].map(x=><div key={x} style={{fontSize:33,padding:'15px 27px',background:'#e6ece9',borderRadius:5}}>{x} ↗</div>)}</div>
    </div>
    <Cursor x={move(f,30,70,900,795)} y={move(f,30,70,1490,989)} rotate={-8}/>
  </Set>;
};

export const V16Review:React.FC = () => {
  const f=useCurrentFrame();
  return <Set dark>
    <div style={{position:'absolute',left:90,top:220,fontSize:91,fontWeight:800,lineHeight:1.3}}>先核对<br/>再确认发布</div>
    <div style={{position:'absolute',left:100,top:600,width:750,height:685,padding:'53px 42px',borderTop:'2px solid #738d99',borderBottom:'2px solid #738d99'}}>
      {['核实尺寸','核对内容','由你确认'].map((s,i)=><div key={s} style={{height:175,fontSize:i===2?65:56,display:'flex',alignItems:'center',gap:30,opacity:move(f,i*14,i*14+18,.22,1),translate:`${move(f,i*14,i*14+18,35,0)}px 0px`}}><span style={{width:67,height:67,border:'2px solid #bdc9cb',borderRadius:100,display:'flex',alignItems:'center',justifyContent:'center',fontSize:37,color:'#edb07b'}}>→</span>{s}</div>)}
    </div>
    <div style={{position:'absolute',left:101,top:1390,fontSize:37,color:'#b7cbd1'}}>核实前，不把猜测当商品事实</div>
  </Set>;
};

export const V16Finish:React.FC = () => {
  const f=useCurrentFrame();
  return <Set>
    <DrainPad id="finish" size={630} tilt={35} spin={move(f,0,75,-12,-3)} style={{position:'absolute',left:378,top:182}}/>
    <div style={{position:'absolute',left:64,top:247,rotate:'-8deg',width:405,height:515,background:'#fffdf7',padding:'39px 29px',boxShadow:'8px 35px 35px #192c3525'}}>
      <div style={{fontSize:31,color:C.muted}}>商品草稿</div><div style={{fontSize:43,fontWeight:750,marginTop:30,lineHeight:1.3}}>资料有来源<br/>内容可修改</div><div style={{marginTop:45,fontSize:29,padding:'17px 8px',border:'2px dashed #c77347',color:'#985532'}}>尺寸：待核实</div>
    </div>
    <div style={{position:'absolute',left:76,top:879,display:'flex',alignItems:'center',gap:24}}><Logo size={150}/><span style={{fontSize:116,fontWeight:800,letterSpacing:8}}>捷境</span></div>
    <div style={{position:'absolute',left:95,top:1110,fontSize:59,lineHeight:1.45,fontWeight:600}}>把上架前的准备<br/>一步步做清楚。</div>
    <div style={{position:'absolute',left:94,top:1380,fontSize:69,fontWeight:700,fontFamily:'Arial, sans-serif',letterSpacing:-1}}>jiejing.shop <span style={{color:C.red}}>↗</span></div>
    <div style={{position:'absolute',left:97,top:1500,fontSize:35,color:C.muted}}>了解完整流程</div>
  </Set>;
};
