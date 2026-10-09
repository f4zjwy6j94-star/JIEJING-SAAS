import React from "react";
import {Audio} from "@remotion/media";
import {Sequence, staticFile} from "remotion";

// Each caption and its generated speech share one timeline group. No burned-in production labels.
export const SpokenLine: React.FC<{from: number; frames: number; file: string; children: React.ReactNode}> = ({from, frames, file, children}) => <Sequence from={from} durationInFrames={frames} name={file}>
  <Audio src={staticFile(`noon-voice-01/${file}`)} />
  <div style={{position: "absolute", left: 70, right: 140, bottom: 310, display: "flex", justifyContent: "center", fontFamily: '"Microsoft YaHei", sans-serif'}}>
    <div style={{fontSize: 40, lineHeight: 1.45, color: "#fffdf5", textAlign: "center", backgroundColor: "#142017df", padding: "12px 24px", borderRadius: 4}}>{children}</div>
  </div>
</Sequence>;
