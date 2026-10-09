import React from "react";
import {AbsoluteFill, Sequence} from "remotion";
import {NoonOpening} from "./v12-noon/Opening";
import {NoonThreshold} from "./v12-noon/Threshold";
import {NoonSources} from "./v12-noon/Sources";
import {NoonTriage} from "./v12-noon/Triage";
import {NoonDraft} from "./v12-noon/Draft";
import {NoonWorkspace} from "./v12-noon/Workspace";
import {NoonReview} from "./v12-noon/Review";
import {NoonClosing} from "./v12-noon/Closing";

// Versioned full-film candidate. All scenes are editable; publishing remains QA-gated.
export const DouyinNoonV12: React.FC = () => <AbsoluteFill style={{backgroundColor: "#1d2b1e"}}>
  <Sequence name="货源图都有了" durationInFrames={136}><NoonOpening/></Sequence>
  <Sequence name="不是最后那一下" from={136} durationInFrames={88}><NoonThreshold/></Sequence>
  <Sequence name="散落资料" from={224} durationInFrames={200}><NoonSources/></Sequence>
  <Sequence name="资料分清再写" from={424} durationInFrames={234}><NoonTriage/></Sequence>
  <Sequence name="整理草稿" from={658} durationInFrames={222}><NoonDraft/></Sequence>
  <Sequence name="捷境接起准备" from={880} durationInFrames={117}><NoonWorkspace/></Sequence>
  <Sequence name="由你确认" from={997} durationInFrames={135}><NoonReview/></Sequence>
  <Sequence name="平台范围与问题" from={1132} durationInFrames={188}><NoonClosing/></Sequence>
</AbsoluteFill>;
