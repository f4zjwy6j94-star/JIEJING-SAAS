import { BrowserCrop } from "../components/BrowserCrop";
import { SceneShell } from "../components/SceneShell";
import { SceneTitle } from "../components/SceneTitle";

export const IdentityScene: React.FC = () => {
  return (
    <SceneShell tone="mint">
      <SceneTitle
        eyebrow="01 · 商品身份"
        title="先确认卖的是什么"
        detail="商品名、SKU、品牌、状态和来源，各自有明确责任。"
      />
      <BrowserCrop y={-300} x={-250} zoom={1} />
    </SceneShell>
  );
};
