import type { Caption } from "@remotion/captions";
import { useEffect, useState } from "react";
import {
  AbsoluteFill,
  staticFile,
  useCurrentFrame,
  useDelayRender,
  useVideoConfig,
} from "remotion";

export const CaptionLayer: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const [captions, setCaptions] = useState<Caption[] | null>(null);
  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender("load launch captions"));

  useEffect(() => {
    fetch(staticFile("captions/launch-01.json"))
      .then((response) => response.json())
      .then((data: Caption[]) => {
        setCaptions(data);
        continueRender(handle);
      })
      .catch((error: unknown) => cancelRender(error));
  }, [cancelRender, continueRender, handle]);

  const currentMs = (frame / fps) * 1000;
  const current = captions?.find(
    (caption) => caption.startMs <= currentMs && caption.endMs > currentMs,
  );

  if (!current) {
    return null;
  }

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 180,
          bottom: 260,
          display: "flex",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            maxWidth: 820,
            padding: "18px 28px",
            borderRadius: 22,
            backgroundColor: "rgba(17, 29, 24, 0.92)",
            color: "#ffffff",
            fontSize: 44,
            fontWeight: 700,
            lineHeight: 1.35,
            textAlign: "center",
            boxShadow: "0 16px 42px rgba(17, 29, 24, 0.18)",
          }}
        >
          {current.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
