import React from 'react';
import type {Caption as CaptionData} from '@remotion/captions';
import {useCurrentFrame,useVideoConfig} from 'remotion';

// Sentence-level captions use verified take boundaries. They are not word-level ASR.
// Keep this Chinese typography inside each scene, not an independent global overlay.
export const Caption:React.FC<{captions:CaptionData[]}>=({captions})=>{
 const f=useCurrentFrame();const {fps}=useVideoConfig();const ms=f/fps*1000;
 const active=captions.find(c=>ms>=c.startMs&&ms<c.endMs);
 if(!active)return null;
 return <div data-caption style={{position:'absolute',left:80,right:106,bottom:208,display:'flex',justifyContent:'center',zIndex:50,pointerEvents:'none'}}>
  <span style={{maxWidth:'100%',padding:'16px 25px',borderRadius:12,background:'#182820ed',color:'#fbfff3',fontFamily:'"Microsoft YaHei",sans-serif',fontSize:40,fontWeight:500,lineHeight:1.5,textAlign:'center',whiteSpace:'pre-line',textWrap:'balance',lineBreak:'strict',boxShadow:'0 6px 24px #10231622'}}>{active.text}</span>
 </div>;
};
