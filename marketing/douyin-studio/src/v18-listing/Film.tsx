import React from 'react';
import {Audio} from '@remotion/media';
import {Series,staticFile,useVideoConfig} from 'remotion';
import {V18Hook} from './Hook';
import {V18Scattered} from './Scattered';
import {V18Collect} from './Collect';
import {V18Draft} from './Draft';
import {V18Edit} from './Edit';
import {V18Result} from './Result';
import {V18Close} from './Close';
import {v18Timing as t} from './timing';

export const JiejingV18:React.FC<{withAudio:boolean}> = ({withAudio=false}) => {
 const {fps}=useVideoConfig();
 return <>
  <Series>
   <Series.Sequence name="有货但文案空白" durationInFrames={t.hook} premountFor={fps}><V18Hook/></Series.Sequence>
   <Series.Sequence name="零散商品资料" durationInFrames={t.scattered} premountFor={fps}><V18Scattered/></Series.Sequence>
   <Series.Sequence name="商品内容模块" durationInFrames={t.collect} premountFor={fps}><V18Collect/></Series.Sequence>
   <Series.Sequence name="具体草稿形成" durationInFrames={t.draft} premountFor={fps}><V18Draft/></Series.Sequence>
   <Series.Sequence name="修改和核对" durationInFrames={t.edit} premountFor={fps}><V18Edit/></Series.Sequence>
   <Series.Sequence name="完整可编辑结果" durationInFrames={t.result} premountFor={fps}><V18Result/></Series.Sequence>
   <Series.Sequence name="商品与下一步" durationInFrames={t.close} premountFor={fps}><V18Close/></Series.Sequence>
  </Series>
  {withAudio&&<Audio src={staticFile('captures/v18-listing/narration.wav')} premountFor={fps}/>}
 </>;
};
