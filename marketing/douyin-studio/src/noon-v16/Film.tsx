import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {V16Conflict,V16Stop,V16Separate,V16Evidence,V16Sources,V16Draft,V16Review,V16Finish} from './Scenes';

// Timing conformed to the 21.28s new narration; 0.72s final visual/audio tail.
export const v16Scenes = [
  {name:'同一商品的尺寸冲突',Component:V16Conflict,from:0,duration:116},
  {name:'停止抄入未核实数字',Component:V16Stop,from:116,duration:60},
  {name:'实物与包装分开询问',Component:V16Separate,from:176,duration:90},
  {name:'向供应商要实测图',Component:V16Evidence,from:266,duration:60},
  {name:'原资料保留',Component:V16Sources,from:326,duration:78},
  {name:'整理草稿但尺寸留空',Component:V16Draft,from:404,duration:64},
  {name:'核对之后再确认',Component:V16Review,from:468,duration:82},
  {name:'结果与官网收束',Component:V16Finish,from:550,duration:110},
];
export const JiejingV16:React.FC<{withAudio?:boolean}> = ({withAudio=false}) => <AbsoluteFill>
  {v16Scenes.map(({Component,name,from,duration})=><Sequence key={name} name={name} from={from} durationInFrames={duration} premountFor={30}><Component/></Sequence>)}
  {withAudio?<Sequence durationInFrames={660} name="新旁白" premountFor={30}><Audio src={staticFile('v16-narration.wav')}/></Sequence>:null}
</AbsoluteFill>;
