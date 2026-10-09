import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {C, Stage} from './Design';

export const V15Question: React.FC = () => {
  const f = useCurrentFrame();
  const clamp = {extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
  return <Stage dark={false}>
    <div style={{position:'absolute',left:82,top:205,fontSize:88,fontWeight:800,letterSpacing:-5,lineHeight:1.2}}>
      商品图有了。<br/><span style={{color:'#527444'}}>文案呢？</span>
    </div>
    <div style={{position:'absolute',left:104,top:750,width:842,height:555,borderRadius:'50%',background:'#dce3cd',scale:interpolate(f,[0,114],[0.96,1.05],clamp)}}/>
    <Img src={staticFile('v15-product.png')} style={{position:'absolute',width:794,left:122,top:610,rotate:interpolate(f,[0,114],['-6deg','2deg'],clamp),translate:interpolate(f,[0,114],['0px 45px','0px -25px'],clamp),filter:'drop-shadow(0px 45px 32px #17251845)'}}/>
    <div style={{position:'absolute',left:115,top:1370,right:130,display:'flex',alignItems:'center',gap:24}}>
      <span style={{width:17,height:66,background:C.bg,opacity:f%24<16?1:0.3}}/>
      <span style={{fontSize:43,color:'#697462'}}>从你的商品资料开始</span>
    </div>
  </Stage>;
};
