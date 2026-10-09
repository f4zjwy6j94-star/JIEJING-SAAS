import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import captions from './Captions.json';
import {V15Hook} from './Hook';
import {V15Question} from './Question';
import {V15Ingest} from './Ingest';
import {V15Draft} from './Draft';
import {V15Verify} from './Verify';
import {V15Confirm} from './Confirm';
import {V15Closing} from './Closing';
import {font} from './Design';

// One recut audio source, no TTS, no time stretching. All subtitles map to that file.
const RecutNarration: React.FC = () => {
  const frame=useCurrentFrame();
  const {fps}=useVideoConfig();
  const line=captions.find(c=>frame/fps*1000>=c.startMs&&frame/fps*1000<c.endMs);
  return <>
    <Audio src={staticFile('v15-recut.wav')}/>
    {line?<div style={{position:'absolute',left:80,right:120,top:1570,display:'flex',justifyContent:'center',fontFamily:font}}>
      <span style={{color:'#fffef2',background:'#17211bea',fontSize:44,fontWeight:650,lineHeight:1.4,padding:'13px 24px',borderRadius:9,textAlign:'center'}}>{line.text}</span>
    </div>:null}
  </>;
};

export const JiejingV15Recut: React.FC = () => {
  const {fps}=useVideoConfig();
  return <AbsoluteFill>
    <Sequence name="改标题，预览即时响应" durationInFrames={88} premountFor={fps}><V15Hook durationFrames={88}/></Sequence>
    <Sequence name="商品有了，内容怎么做" from={88} durationInFrames={114} premountFor={fps}><V15Question/></Sequence>
    <Sequence name="原图参数目标汇合" from={202} durationInFrames={92} premountFor={fps}><V15Ingest durationFrames={92}/></Sequence>
    <Sequence name="从资料形成可修改草稿" from={294} durationInFrames={94} premountFor={fps}><V15Draft durationFrames={94}/></Sequence>
    <Sequence name="人工核对信息与修改" from={388} durationInFrames={77} premountFor={fps}><V15Verify durationFrames={77}/></Sequence>
    <Sequence name="eBay先行，商家确认" from={465} durationInFrames={93} premountFor={fps}><V15Confirm/></Sequence>
    <Sequence name="品牌与官网完整收束" from={558} durationInFrames={150} premountFor={fps}><V15Closing/></Sequence>
    <Sequence name="沿用已发布旁白的重剪音轨" durationInFrames={708} premountFor={fps}><RecutNarration/></Sequence>
  </AbsoluteFill>;
};
