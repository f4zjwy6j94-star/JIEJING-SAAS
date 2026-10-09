import React from "react";
import {AbsoluteFill, Audio, Sequence, staticFile} from "remotion";
import {V14Hook} from "./Hook";
import {V14Hold} from "./Hold";
import {V14Ask} from "./Ask";
import {V14Evidence} from "./Evidence";
import {V14Draft} from "./Draft";
import {V14End} from "./End";

export type V14Props = {voiceFile?: string};

// The empty-voice version is an editable visual timeline, never a publishable silent substitute.
// Timing is provisional until the new accepted narration is available and reviewed.
export const EveningV14VisualEdit: React.FC<V14Props> = ({voiceFile}) => <AbsoluteFill>
  <Sequence name="11.5还是20：冲突即开场" durationInFrames={75}><V14Hook/></Sequence>
  <Sequence name="五秒内先交付判断" from={75} durationInFrames={75}><V14Hold/></Sequence>
  <Sequence name="问实物、包装与实测图" from={150} durationInFrames={180}><V14Ask/></Sequence>
  <Sequence name="两份原资料留存核对" from={330} durationInFrames={90}><V14Evidence/></Sequence>
  <Sequence name="有依据再写草稿" from={420} durationInFrames={150}><V14Draft/></Sequence>
  <Sequence name="结论、品牌与官网" from={570} durationInFrames={120}><V14End/></Sequence>
  {voiceFile ? <Audio src={staticFile(voiceFile)}/> : null}
</AbsoluteFill>;
