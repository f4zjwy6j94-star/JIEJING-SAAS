import { Easing, Interactive, interpolate, useCurrentFrame } from "remotion";
import { SceneShell } from "../components/SceneShell";

export const HookScene: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <SceneShell>
      <div style={{ position: "absolute", left: 80, right: 180, top: 340 }}>
        <Interactive.Div
          name="Hook title"
          style={{
            fontSize: 104,
            fontWeight: 900,
            lineHeight: 1.08,
            letterSpacing: -4,
            opacity: interpolate(frame, [0, 20], [0, 1], {
              easing: Easing.bezier(0.16, 1, 0.3, 1),
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: interpolate(frame, [0, 24], ["0px 44px", "0px 0px"], {
              easing: Easing.bezier(0.16, 1, 0.3, 1),
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          做一条 eBay Listing
          <br />
          到底要整理
          <br />
          <span style={{ color: "#08766e" }}>多少字段？</span>
        </Interactive.Div>
        <Interactive.Div
          name="Hook subtitle"
          style={{
            marginTop: 48,
            padding: "24px 30px",
            width: 680,
            borderRadius: 24,
            backgroundColor: "#ffffff",
            border: "2px solid #cce7df",
            color: "#385047",
            fontSize: 42,
            fontWeight: 700,
            opacity: interpolate(frame, [20, 40], [0, 1], {
              easing: Easing.bezier(0.16, 1, 0.3, 1),
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          不只是标题和描述。
        </Interactive.Div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 80,
          bottom: 210,
          width: 820,
          height: 12,
          borderRadius: 999,
          backgroundColor: "#dfece7",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${interpolate(frame, [0, 100], [8, 100], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })}%`,
            height: "100%",
            borderRadius: 999,
            backgroundColor: "#08766e",
          }}
        />
      </div>
    </SceneShell>
  );
};
