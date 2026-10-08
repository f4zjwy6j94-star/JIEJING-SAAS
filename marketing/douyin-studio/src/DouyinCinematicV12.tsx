import React from "react";
import type { Caption } from "@remotion/captions";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Img, Interactive, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import timing from "./V12SampleTiming.json";

// Fictional AI-generated scene illustrations, not a customer, supplier or UI recording.
// This is an audible art-direction trial. It is NOT an approved/publishable final film.
type SceneProps = { style?: React.CSSProperties };

const ArrivalInner: React.FC<SceneProps> = ({ style }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ backgroundColor: "#171e16", color: "#fffaf0", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden", ...style }}>
    <Img name="样品开箱场景示意" src={staticFile("noon-unboxing.png")} style={{ width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 136], [1.14, 1.02]), translate: interpolate(frame, [0, 136], ["-24px 22px", "0px 0px"]) }} />
    <AbsoluteFill style={{ background: "linear-gradient(180deg,rgba(12,19,12,.63),transparent 47%,rgba(12,19,12,.48))" }} />
    <Interactive.Div name="开场问题上半句" style={{ position: "absolute", top: 240, left: 80, right: 120, fontSize: 88, lineHeight: 1.24, fontWeight: 700, letterSpacing: -3, opacity: interpolate(frame, [0, 8, 69, 78], [0, 1, 1, 0], { extrapolateRight: "clamp" }), translate: interpolate(frame, [0, 15], ["0px 35px", "0px 0px"], { extrapolateRight: "clamp" }) }}>货源图<br />都有了。</Interactive.Div>
    <Interactive.Div name="问题落点" style={{ position: "absolute", top: 240, left: 80, right: 120, fontSize: 80, lineHeight: 1.28, fontWeight: 700, letterSpacing: -2, opacity: interpolate(frame, [75, 84], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }), translate: interpolate(frame, [75, 89], ["0px 34px", "0px 0px"], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>怎么还卡在<br /><span style={{ color: "#f4cb82" }}>上架前？</span></Interactive.Div>
    <Interactive.Div name="窄金线强调" style={{ position: "absolute", top: 478, left: 83, height: 5, width: interpolate(frame, [95, 117], [0, 475], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }), backgroundColor: "#efc886" }} />
  </AbsoluteFill>;
};

const SourcesInner: React.FC<SceneProps> = ({ style }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ backgroundColor: "#e8e1d4", color: "#273225", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden", ...style }}>
    <Img name="整理照片场景示意" src={staticFile("noon-sorting.png")} style={{ position: "absolute", width: 1080, height: 1080, top: 0, objectFit: "cover", objectPosition: "50% 66%", scale: interpolate(frame, [0, 96], [1.045, 1]) }} />
    <Interactive.Div name="浅色纸张推入" style={{ position: "absolute", top: 1040, bottom: 0, left: 0, right: 0, backgroundColor: "#eee8de", translate: interpolate(frame, [0, 18], ["0px 140px", "0px 0px"], { extrapolateRight: "clamp" }), boxShadow: "0 -18px 55px #211d1838" }}>
      <Interactive.Div name="图片和规格不是一回事" style={{ position: "absolute", left: 80, top: 95, fontSize: 60, lineHeight: 1.34, fontWeight: 700 }}>图片是图片，<br />规格要有依据。</Interactive.Div>
      <Interactive.Div name="规格书写划线" style={{ position: "absolute", left: 81, top: 275, width: interpolate(frame, [35, 62], [0, 462], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }), height: 5, backgroundColor: "#a98451" }} />
    </Interactive.Div>
  </AbsoluteFill>;
};

const NotesInner: React.FC<SceneProps> = ({ style }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ backgroundColor: "#222b20", color: "#fffaf0", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden", ...style }}>
    <Img name="聊天补充资料的情境而非聊天记录" src={staticFile("noon-sorting.png")} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "68% 46%", scale: 1.32, translate: interpolate(frame, [0, 84], ["-20px 15px", "12px -12px"]) }} />
    <AbsoluteFill style={{ background: "linear-gradient(180deg,rgba(13,24,13,.25),rgba(13,24,13,.82))" }} />
    <Interactive.Div name="聊天中的补充不遗漏" style={{ position: "absolute", top: 930, left: 78, right: 130, fontSize: 70, lineHeight: 1.32, fontWeight: 700, opacity: interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" }), translate: interpolate(frame, [0, 18], ["0px 40px", "0px 0px"], { extrapolateRight: "clamp" }) }}>还有那些<br /><span style={{ color: "#f4cb82" }}>散在聊天里的补充。</span></Interactive.Div>
    <Interactive.Div name="补充说明强调" style={{ position: "absolute", top: 1200, left: 83, fontSize: 32, letterSpacing: 5, color: "#eee3cd", opacity: interpolate(frame, [26, 41], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>一起整理 · 保留来源</Interactive.Div>
  </AbsoluteFill>;
};

const FocusInner: React.FC<SceneProps> = ({ style }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ backgroundColor: "#282a1f", color: "#fffaf0", fontFamily: '"Microsoft YaHei", sans-serif', overflow: "hidden", ...style }}>
    <Img name="检查实物场景示意" src={staticFile("noon-detail.png")} style={{ width: "100%", height: "100%", objectFit: "cover", scale: interpolate(frame, [0, 111], [1.08, 1.015]) }} />
    <AbsoluteFill style={{ background: "linear-gradient(180deg,rgba(15,20,11,.5),transparent 60%,rgba(15,20,11,.35))" }} />
    <Interactive.Div name="先整理" style={{ position: "absolute", top: 240, left: 80, right: 120, fontSize: 97, lineHeight: 1.29, letterSpacing: -3, fontWeight: 700, opacity: interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) }}>先理清，</Interactive.Div>
    <Interactive.Div name="再写草稿" style={{ position: "absolute", top: 390, left: 80, right: 120, fontSize: 97, lineHeight: 1.29, letterSpacing: -3, fontWeight: 700, color: "#f4cb82", opacity: interpolate(frame, [45, 59], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }), translate: interpolate(frame, [45, 65], ["0px 30px", "0px 0px"], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>再开始写。</Interactive.Div>
  </AbsoluteFill>;
};

// Remotion 4.0.518 predates wrapInSequence. Keep explicit connected scene groups.
export const V12Arrival = ArrivalInner;
export const V12Sources = SourcesInner;
export const V12Notes = NotesInner;
export const V12Focus = FocusInner;

const SpokenCaption: React.FC = () => {
  const frame = useCurrentFrame();
  const ms = frame / 30 * 1000;
  const captions: Caption[] = timing.captions;
  const active = captions.find((caption) => ms >= caption.startMs && ms < caption.endMs);
  if (!active) return null;
  return <div style={{ position: "absolute", left: 65, right: 135, bottom: 300, display: "flex", justifyContent: "center", fontFamily: '"Microsoft YaHei", sans-serif' }}><div style={{ color: "#fffdf5", fontSize: 37, lineHeight: 1.5, textAlign: "center", padding: "10px 22px", backgroundColor: "#141c13c9", borderRadius: 3 }}>{active.text}</div></div>;
};

export const DouyinCinematicV12Sample: React.FC = () => <AbsoluteFill style={{ backgroundColor: "#171e16" }}>
  <Sequence name="开箱与开场问题" durationInFrames={137}><V12Arrival /></Sequence>
  <Sequence name="整理图片和规格" from={137} durationInFrames={97}><V12Sources /></Sequence>
  <Sequence name="保留补充资料来源" from={234} durationInFrames={85}><V12Notes /></Sequence>
  <Sequence name="核对后再写" from={319} durationInFrames={112}><V12Focus /></Sequence>
  <Audio name="中文合成旁白试音" src={staticFile("v12-sample-narration.wav")} />
  <Sequence name="语句级字幕，时间取自生成片段" durationInFrames={431}><SpokenCaption /></Sequence>
</AbsoluteFill>;
