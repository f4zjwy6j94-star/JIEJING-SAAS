import { Easing, Interactive, interpolate, useCurrentFrame } from "remotion";
import { SceneShell } from "../components/SceneShell";
import { SceneTitle } from "../components/SceneTitle";

const items = [
  "不知道的事实留空",
  "图片权利单独核对",
  "发布、改价、退款由商家确认",
];

export const GuardrailsScene: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <SceneShell tone="amber">
      <SceneTitle
        eyebrow="05 · 风险边界"
        title="缺口不会让 AI 乱猜"
        detail="能自动的先自动，需要负责的明确交回商家。"
        accent="amber"
      />
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 180,
          top: 650,
          display: "flex",
          flexDirection: "column",
          gap: 28,
        }}
      >
        {items.map((item, index) => (
          <Interactive.Div
            key={item}
            name={`Guardrail ${index + 1}`}
            style={{
              minHeight: 150,
              display: "flex",
              alignItems: "center",
              gap: 26,
              padding: "28px 34px",
              borderRadius: 28,
              backgroundColor: "#ffffff",
              border: "2px solid #ead6aa",
              boxShadow: "0 18px 50px rgba(73, 48, 8, 0.09)",
              color: "#273a32",
              fontSize: 42,
              fontWeight: 800,
              opacity: interpolate(frame, [index * 16, index * 16 + 18], [0, 1], {
                easing: Easing.bezier(0.16, 1, 0.3, 1),
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
              translate: interpolate(
                frame,
                [index * 16, index * 16 + 18],
                ["0px 28px", "0px 0px"],
                {
                  easing: Easing.bezier(0.16, 1, 0.3, 1),
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                },
              ),
            }}
          >
            <div
              style={{
                width: 64,
                height: 64,
                flex: "0 0 64px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                borderRadius: 20,
                backgroundColor: index === 2 ? "#f8e9c9" : "#dff2eb",
                color: index === 2 ? "#9b610b" : "#08766e",
                fontSize: 34,
                fontWeight: 900,
              }}
            >
              {index === 2 ? "!" : "✓"}
            </div>
            {item}
          </Interactive.Div>
        ))}
      </div>
    </SceneShell>
  );
};
