import { AbsoluteFill } from "remotion";
import { BrandHeader } from "./BrandHeader";

export const SceneShell: React.FC<{
  children: React.ReactNode;
  label?: string;
  tone?: "paper" | "mint" | "amber";
}> = ({ children, label, tone = "paper" }) => {
  return (
    <AbsoluteFill
      style={{
        background:
          tone === "mint"
            ? "linear-gradient(180deg, #effaf6 0%, #fffefa 72%)"
            : tone === "amber"
              ? "linear-gradient(180deg, #fff8e9 0%, #fffefa 72%)"
              : "linear-gradient(180deg, #f7faf8 0%, #fffefa 72%)",
        color: "#111d18",
      }}
    >
      <BrandHeader label={label} />
      {children}
    </AbsoluteFill>
  );
};
