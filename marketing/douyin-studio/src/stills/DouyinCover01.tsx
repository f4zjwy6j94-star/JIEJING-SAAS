import { CanvasImage, Interactive, staticFile } from "remotion";

export const DouyinCover01: React.FC = () => {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        padding: "100px 180px 320px 80px",
        background: "linear-gradient(180deg, #eef9f5 0%, #fffefa 74%)",
        color: "#111d18",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
        <CanvasImage
          src={staticFile("brand/jiejing-app-icon.svg")}
          style={{ width: 84, height: 84 }}
        />
        <div>
          <div style={{ fontSize: 36, fontWeight: 900 }}>捷境 AI 电商</div>
          <div style={{ marginTop: 4, fontSize: 25, color: "#5c6d65" }}>
            eBay 卖家的 AI CEO 工作台
          </div>
        </div>
      </div>
      <div
        style={{
          marginTop: 190,
          display: "inline-flex",
          padding: "16px 24px",
          borderRadius: 999,
          backgroundColor: "#dff2eb",
          color: "#08766e",
          fontSize: 30,
          fontWeight: 900,
        }}
      >
        真实页面演示
      </div>
      <Interactive.Div
        name="Cover title"
        style={{
          marginTop: 42,
          fontSize: 112,
          fontWeight: 900,
          lineHeight: 1.08,
          letterSpacing: -5,
        }}
      >
        做一条
        <br />
        eBay Listing
        <br />
        到底要填
        <br />
        <span style={{ color: "#08766e" }}>多少东西？</span>
      </Interactive.Div>
      <div
        style={{
          marginTop: 56,
          width: 760,
          padding: "28px 34px",
          borderRadius: 28,
          backgroundColor: "#ffffff",
          border: "2px solid #cce7df",
          boxShadow: "0 24px 64px rgba(17, 29, 24, 0.12)",
          fontSize: 38,
          fontWeight: 800,
          lineHeight: 1.45,
          color: "#385047",
        }}
      >
        商品身份 · 实物规格 · 价格库存 · 履约与图片权利
      </div>
    </div>
  );
};
