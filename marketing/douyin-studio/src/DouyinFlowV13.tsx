import React from "react";
import {AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {FlowIngest} from "./v13-flow/Ingest";
import {FlowDraft} from "./v13-flow/Draft";
import {FlowEdit} from "./v13-flow/Edit";
import {FlowClose} from "./v13-flow/Close";
import {font} from "./v13-flow/Shared";

// Historical visual-review composition: the owner REJECTED this Serena voice.
// Preserve for editing only; do not use as a publication candidate.
// Sentence windows grounded in encoded v10 captions, not an ASR or listening pass.
const captions = [
 {text:"有货源就更直接",startMs:0,endMs:2170,timestampMs:null,confidence:null},
 {text:"上传商品原图和参数",startMs:2170,endMs:4420,timestampMs:null,confidence:null},
 {text:"说清销售目标",startMs:4420,endMs:6170,timestampMs:null,confidence:null},
 {text:"就能开始准备",startMs:6170,endMs:7970,timestampMs:null,confidence:null},
 {text:"AI 根据真实信息",startMs:7970,endMs:10320,timestampMs:null,confidence:null},
 {text:"写好商品标题",startMs:10320,endMs:11920,timestampMs:null,confidence:null},
 {text:"卖点和描述",startMs:11920,endMs:13120,timestampMs:null,confidence:null},
 {text:"开通相应功能后",startMs:13120,endMs:14770,timestampMs:null,confidence:null},
 {text:"还能生成商品图片和展示视频",startMs:14770,endMs:17820,timestampMs:null,confidence:null},
 {text:"这些内容都能在捷境里继续修改",startMs:17820,endMs:20570,timestampMs:null,confidence:null},
];
const Narration = () => {
 const f=useCurrentFrame(); const {fps}=useVideoConfig(); const line=captions.find(c=>f/fps*1000>=c.startMs&&f/fps*1000<c.endMs);
 return <><Audio src={staticFile("serena-flow-original.wav")}/>{line&&<div style={{position:"absolute",left:70,right:100,bottom:310,display:"flex",justifyContent:"center",fontFamily:font}}><div style={{padding:"17px 25px",borderRadius:14,background:"#11281fed",color:"#fff",fontSize:43,lineHeight:1.45,textAlign:"center",fontWeight:600,maxWidth:850}}>{line.text}</div></div>}</>;
};
export const DouyinFlowV13: React.FC = () => {
 const {fps}=useVideoConfig();
 return <AbsoluteFill>
  <Sequence name="商品资料进入捷境" durationInFrames={228} premountFor={fps}><FlowIngest/></Sequence>
  <Sequence name="草稿内容展开" from={228} durationInFrames={180} premountFor={fps}><FlowDraft/></Sequence>
  <Sequence name="选择与修改有可见反馈" from={408} durationInFrames={228} premountFor={fps}><FlowEdit/></Sequence>
  <Sequence name="捷境范围与收束" from={636} durationInFrames={84} premountFor={fps}><FlowClose/></Sequence>
  <Sequence name="旧Serena声轨与同组字幕" from={12} durationInFrames={618} premountFor={fps}><Narration/></Sequence>
 </AbsoluteFill>;
};
