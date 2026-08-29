import { CanvasImage, Interactive, staticFile } from "remotion";

export const DouyinCoverHorizontal01: React.FC = () => {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "grid",
        gridTemplateColumns: "1.25fr 0.75fr",
        gap: 70,
        padding: "86px 96px",
        background: "linear-gradient(135deg, #eef9f5 0%, #fffefa 72%)",
        color: "#111d18",
      }}
    >
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
          <CanvasImage
            src={staticFile("brand/jiejing-app-icon.svg")}
            style={{ width: 84, height: 84 }}
          />
          <div>
            <div style={{ fontSize: 38, fontWeight: 900 }}>捷境 AI 电商</div>
            <div style={{ marginTop: 5, fontSize: 26, color: "#5c6d65" }}>
              eBay 卖家的 AI CEO 工作台
            </div>
          </div>
        </div>
        <div
          style={{
            marginTop: 92,
            display: "inline-flex",
            padding: "13px 22px",
            borderRadius: 999,
            backgroundColor: "#dff2eb",
            color: "#08766e",
            fontSize: 27,
            fontWeight: 900,
          }}
        >
          真实页面演示
        </div>
        <Interactive.Div
          name="Horizontal cover title"
          style={{
            marginTop: 32,
            fontSize: 82,
            fontWeight: 900,
            lineHeight: 1.08,
            letterSpacing: -4,
          }}
        >
          做一条 eBay Listing
          <br />
          到底要填
          <span style={{ color: "#08766e" }}>多少东西？</span>
        </Interactive.Div>
      </div>
      <div
        style={{
          alignSelf: "center",
          display: "flex",
          flexDirection: "column",
          gap: 22,
          padding: "38px 34px",
          borderRadius: 32,
          backgroundColor: "#ffffff",
          border: "2px solid #cce7df",
          boxShadow: "0 28px 70px rgba(17, 29, 24, 0.12)",
        }}
      >
        {[
          "商品身份",
          "实物规格",
          "价格库存",
          "履约与图片权利",
        ].map((item, index) => (
          <div
            key={item}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 18,
              padding: "16px 18px",
              borderRadius: 18,
              backgroundColor: index === 3 ? "#fff6e4" : "#f2faf7",
              color: index === 3 ? "#8d5a0e" : "#27483d",
              fontSize: 31,
              fontWeight: 850,
            }}
          >
            <span style={{ color: index === 3 ? "#b98228" : "#08766e" }}>
              {index === 3 ? "!" : "✓"}
            </span>
            {item}
          </div>
        ))}
      </div>
    </div>
  );
};
