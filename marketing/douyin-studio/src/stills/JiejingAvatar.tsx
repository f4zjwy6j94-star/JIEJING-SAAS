import { CanvasImage, staticFile } from "remotion";

export const JiejingAvatar: React.FC = () => {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#fffefa",
      }}
    >
      <CanvasImage
        src={staticFile("brand/jiejing-app-icon.svg")}
        style={{ width: 860, height: 860 }}
      />
    </div>
  );
};
