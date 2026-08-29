import {
  CanvasImage,
  Easing,
  Interactive,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { SceneShell } from "../components/SceneShell";

export const CtaScene: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <SceneShell label="当前支持 eBay">
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 180,
          top: 360,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
        }}
      >
        <CanvasImage
          src={staticFile("brand/jiejing-app-icon.svg")}
          style={{
            width: 180,
            height: 180,
            opacity: interpolate(frame, [0, 20], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            }),
          }}
        />
        <Interactive.Div
          name="CTA title"
          style={{
            marginTop: 44,
            fontSize: 92,
            fontWeight: 900,
            lineHeight: 1.12,
            letterSpacing: -3,
            color: "#111d18",
            opacity: interpolate(frame, [10, 30], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.bezier(0.16, 1, 0.3, 1),
            }),
          }}
        >
          把商品资料
          <br />
          变成商家可核对的
          <br />
          <span style={{ color: "#08766e" }}>eBay 草稿</span>
        </Interactive.Div>
        <div
          style={{
            marginTop: 54,
            padding: "28px 36px",
            borderRadius: 24,
            backgroundColor: "#08766e",
            color: "#ffffff",
            fontSize: 44,
            fontWeight: 900,
            boxShadow: "0 22px 60px rgba(8, 118, 110, 0.25)",
          }}
        >
          评论或私信「内测」
        </div>
        <div
          style={{
            marginTop: 26,
            color: "#5c6d65",
            fontSize: 30,
            fontWeight: 700,
          }}
        >
          当前支持 eBay · 关键动作由商家确认
        </div>
      </div>
    </SceneShell>
  );
};
