import { BrowserCrop } from "../components/BrowserCrop";
import { SceneShell } from "../components/SceneShell";
import { SceneTitle } from "../components/SceneTitle";

export const CommerceScene: React.FC = () => {
  return (
    <SceneShell tone="amber">
      <SceneTitle
        eyebrow="03 · 经营与履约"
        title="成本和承诺不能猜"
        detail="售价、库存、实际发货地和图片权利，最后都由商家确认。"
        accent="amber"
      />
      <BrowserCrop y={-930} x={-280} zoom={1} accent="amber" />
    </SceneShell>
  );
};
