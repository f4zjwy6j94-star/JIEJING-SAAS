import React from "react";
import {AbsoluteFill, Audio, Freeze, Sequence, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import timing from "./V13WebsiteTiming.json";
import {ReviewOpening} from "./v13-flow/ReviewOpening";
import {ReviewDraft} from "./v13-flow/ReviewDraft";
import {FlowEdit} from "./v13-flow/Edit";
import {WebsiteClose} from "./v13-flow/WebsiteClose";
import {font} from "./v13-flow/Shared";

const EditRetime: React.FC = () => {
  const frame = useCurrentFrame();
  return <Freeze frame={Math.min(227, Math.round(frame * 227 / 125))}><FlowEdit /></Freeze>;
};

const WebsiteNarration: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ms = frame / fps * 1000;
  const line = timing.captions.find(c => ms >= c.startMs && ms < c.endMs);
  return <>
    <Audio src={staticFile(timing.voiceFile)} />
    {line ? <div style={{position: "absolute", left: 80, right: 116, bottom: 310, display: "flex", justifyContent: "center", fontFamily: font}}><div style={{maxWidth: 858, padding: "16px 26px", borderRadius: 15, background: "#11281ff2", color: "#fff", fontSize: 46, lineHeight: 1.45, textAlign: "center", fontWeight: 650, boxShadow: "0 4px 20px #00000020"}}>{line.text}</div></div> : null}
  </>;
};

// Separate revision preserves the earlier 26-second film and its narration.
export const DouyinFlowV13Website: React.FC = () => {
  const {fps} = useVideoConfig();
  return <AbsoluteFill>
    <Sequence name="商品资料交给捷境" durationInFrames={207} premountFor={fps}><ReviewOpening sceneDurationFrames={207} /></Sequence>
    <Sequence name="标题卖点描述形成草稿" from={207} durationInFrames={189} premountFor={fps}><ReviewDraft clearResult /></Sequence>
    <Sequence name="修改标题与预览更新" from={396} durationInFrames={126} premountFor={fps}><EditRetime /></Sequence>
    <Sequence name="结果收束与官网入口" from={522} durationInFrames={258} premountFor={fps}><WebsiteClose durationFrames={258} /></Sequence>
    <Sequence name="完整官网版旁白与同源字幕" from={Math.round(0.2 * fps)} durationInFrames={774} premountFor={fps}><WebsiteNarration /></Sequence>
  </AbsoluteFill>;
};
