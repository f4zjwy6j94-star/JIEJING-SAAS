import { Easing, Interactive, interpolate, useCurrentFrame } from "remotion";

export const SceneTitle: React.FC<{
  eyebrow: string;
  title: string;
  detail: string;
  accent?: "teal" | "amber";
}> = ({ eyebrow, title, detail, accent = "teal" }) => {
  const frame = useCurrentFrame();

  return (
    <div style={{ position: "absolute", left: 80, right: 180, top: 220 }}>
      <Interactive.Div
        name="Scene eyebrow"
        style={{
          color: accent === "teal" ? "#08766e" : "#a66b10",
          fontSize: 28,
          fontWeight: 800,
          letterSpacing: 3,
          opacity: interpolate(frame, [0, 12], [0, 1], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {eyebrow}
      </Interactive.Div>
      <Interactive.Div
        name="Scene title"
        style={{
          marginTop: 16,
          fontSize: 82,
          fontWeight: 900,
          lineHeight: 1.1,
          letterSpacing: -3,
          opacity: interpolate(frame, [5, 22], [0, 1], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: interpolate(frame, [5, 22], ["0px 28px", "0px 0px"], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {title}
      </Interactive.Div>
      <Interactive.Div
        name="Scene detail"
        style={{
          marginTop: 16,
          maxWidth: 780,
          color: "#5c6d65",
          fontSize: 34,
          fontWeight: 600,
          lineHeight: 1.4,
          opacity: interpolate(frame, [12, 30], [0, 1], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {detail}
      </Interactive.Div>
    </div>
  );
};
