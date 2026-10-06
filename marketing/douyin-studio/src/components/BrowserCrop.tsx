import {
  CanvasImage,
  Easing,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

export const BrowserCrop: React.FC<{
  y: number;
  x?: number;
  zoom?: number;
  accent?: "teal" | "amber";
}> = ({ y, x = -300, zoom = 1, accent = "teal" }) => {
  const frame = useCurrentFrame();

  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        top: 500,
        width: 820,
        height: 850,
        overflow: "hidden",
        borderRadius: 34,
        backgroundColor: "#ffffff",
        border: `3px solid ${accent === "teal" ? "#cce7df" : "#ead6aa"}`,
        boxShadow: "0 32px 80px rgba(17, 29, 24, 0.14)",
        scale: interpolate(frame, [0, 24], [0.96, 1], {
          easing: Easing.bezier(0.16, 1, 0.3, 1),
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          output: "perceptual-scale",
        }),
        opacity: interpolate(frame, [0, 16], [0, 1], {
          easing: Easing.bezier(0.16, 1, 0.3, 1),
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      }}
    >
      <CanvasImage
        src={staticFile("captures/listing-page.png")}
        style={{
          position: "absolute",
          left: x,
          top: y,
          width: 1380 * zoom,
          height: 2961 * zoom,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: 30,
          boxShadow: "inset 0 0 0 1px rgba(17, 29, 24, 0.06)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
};
