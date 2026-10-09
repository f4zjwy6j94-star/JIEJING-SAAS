import React from "react";
import {AbsoluteFill, Audio, Freeze, Sequence, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import timing from "./V13ReviewTiming.json";
import {ReviewDraft} from "./v13-flow/ReviewDraft";
import {FlowEdit} from "./v13-flow/Edit";
import {ReviewOpening} from "./v13-flow/ReviewOpening";
import {ReviewClose} from "./v13-flow/ReviewClose";
import {font} from "./v13-flow/Shared";

// Computes source time from each output frame; this is a continuous retime,
// not a fixed-frame fallback. Original scenes and the rejected film stay intact.
const Retime: React.FC<{sourceFrames: number; targetFrames: number; children: React.ReactNode}> = ({sourceFrames, targetFrames, children}) => {
  const frame = useCurrentFrame();
  const sourceFrame = Math.min(sourceFrames - 1, Math.max(0, Math.round(frame * (sourceFrames - 1) / Math.max(1, targetFrames - 1))));
  return <Freeze frame={sourceFrame}>{children}</Freeze>;
};

const ReviewNarration: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ms = frame / fps * 1000;
  const caption = timing.captions.find((line) => ms >= line.startMs && ms < line.endMs);
  return <>
    <Audio src={staticFile(timing.voiceFile)} />
    {caption ? <div style={{position: "absolute", left: 80, right: 116, bottom: 310, display: "flex", justifyContent: "center", fontFamily: font}}>
      <div style={{maxWidth: 858, padding: "16px 26px", borderRadius: 15, background: "#11281ff2", color: "#fff", fontSize: 46, lineHeight: 1.45, textAlign: "center", fontWeight: 650, boxShadow: "0 4px 20px #00000020"}}>{caption.text}</div>
    </div> : null}
  </>;
};

export const DouyinFlowV13Review: React.FC = () => {
  const {fps} = useVideoConfig();
  return <AbsoluteFill>
    <Sequence name="商品图与待办进入捷境" durationInFrames={timing.scenes.openingEnd} premountFor={fps}>
      <ReviewOpening sceneDurationFrames={timing.scenes.openingEnd} />
    </Sequence>
    <Sequence name="草稿从资料中展开" from={timing.scenes.openingEnd} durationInFrames={timing.scenes.draftEnd - timing.scenes.openingEnd} premountFor={fps}>
      <ReviewDraft />
    </Sequence>
    <Sequence name="图文任务与标题修改" from={timing.scenes.draftEnd} durationInFrames={timing.scenes.editEnd - timing.scenes.draftEnd} premountFor={fps}>
      <Retime sourceFrames={228} targetFrames={timing.scenes.editEnd - timing.scenes.draftEnd}><FlowEdit /></Retime>
    </Sequence>
    <Sequence name="捷境与发布确认边界" from={timing.scenes.editEnd} durationInFrames={timing.durationFrames - timing.scenes.editEnd} premountFor={fps}>
      <ReviewClose />
    </Sequence>
    <Sequence name="已认可方向的新完整旁白与字幕" from={Math.round(0.2 * fps)} durationInFrames={timing.durationFrames - Math.round(0.2 * fps)} premountFor={fps}>
      <ReviewNarration />
    </Sequence>
  </AbsoluteFill>;
};
