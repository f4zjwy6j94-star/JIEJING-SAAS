import { CanvasImage, Interactive, staticFile } from "remotion";

export const BrandHeader: React.FC<{ label?: string }> = ({
  label = "eBay 卖家的 AI CEO 工作台",
}) => {
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 180,
        top: 84,
        height: 84,
        display: "flex",
        alignItems: "center",
        gap: 22,
      }}
    >
      <CanvasImage
        src={staticFile("brand/jiejing-app-icon.svg")}
        style={{ width: 76, height: 76 }}
      />
      <Interactive.Div
        name="Brand label"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          color: "#111d18",
        }}
      >
        <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: 1 }}>
          捷境 AI 电商
        </div>
        <div style={{ fontSize: 24, color: "#5c6d65" }}>{label}</div>
      </Interactive.Div>
    </div>
  );
};
