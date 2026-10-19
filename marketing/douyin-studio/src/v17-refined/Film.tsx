import React from 'react';
import {AbsoluteFill, Sequence, staticFile, useVideoConfig} from 'remotion';
import {Audio} from '@remotion/media';
import {RefinedHook} from './Hook';
import {RefinedFriction} from './Friction';
import {RefinedReveal} from './Reveal';
import {RefinedConnected} from './Connected';
import {RefinedDecision} from './Decision';
import {RefinedClose} from './Close';
import {LocalCaption} from './Shared';

export const JiejingV17Refined:React.FC<{withAudio?:boolean}> = ({withAudio=false})=>{const {fps}=useVideoConfig();return <AbsoluteFill>
 <Sequence name="货有了但准备还没完" from={0} durationInFrames={136} premountFor={fps}><RefinedHook/><LocalCaption items={[{text:'做跨境，货有了',startMs:0,endMs:2300,timestampMs:null,confidence:null},{text:'时间却全花在上架前',startMs:2300,endMs:4400,timestampMs:null,confidence:null}]}/></Sequence>
 <Sequence name="反复找资料和改内容" from={136} durationInFrames={153} premountFor={fps}><RefinedFriction/><LocalCaption items={[{text:'选品没方向，资料来回找',startMs:0,endMs:2333,timestampMs:null,confidence:null},{text:'标题和图片反复改',startMs:2333,endMs:4967,timestampMs:null,confidence:null}]}/></Sequence>
 <Sequence name="捷境接收经营任务" from={289} durationInFrames={132} premountFor={fps}><RefinedReveal/><LocalCaption items={[{text:'捷境',startMs:0,endMs:1367,timestampMs:null,confidence:null},{text:'面向跨境卖家的 AI 电商工作台',startMs:1367,endMs:4233,timestampMs:null,confidence:null}]}/></Sequence>
 <Sequence name="从资料到内容和素材" from={421} durationInFrames={136} premountFor={fps}><RefinedConnected/><LocalCaption items={[{text:'调研、文案、图片视频',startMs:0,endMs:2367,timestampMs:null,confidence:null},{text:'在这里接着做',startMs:2367,endMs:4400,timestampMs:null,confidence:null}]}/></Sequence>
 <Sequence name="修改草稿并保留确认" from={557} durationInFrames={110} premountFor={fps}><RefinedDecision/><LocalCaption items={[{text:'目前先支持 eBay',startMs:0,endMs:1533,timestampMs:null,confidence:null},{text:'修改后由你确认发布',startMs:1533,endMs:3500,timestampMs:null,confidence:null}]}/></Sequence>
 <Sequence name="成果与官网" from={667} durationInFrames={173} premountFor={fps}><RefinedClose/><LocalCaption items={[{text:'少来回切换',startMs:0,endMs:1333,timestampMs:null,confidence:null},{text:'让商品准备更完整',startMs:1333,endMs:3433,timestampMs:null,confidence:null}]}/></Sequence>
 {withAudio?<Audio src={staticFile('v17-narration.wav')} premountFor={fps}/>:null}
</AbsoluteFill>;};
