import { BrowserCrop } from "../components/BrowserCrop";
import { SceneShell } from "../components/SceneShell";
import { SceneTitle } from "../components/SceneTitle";

export const SpecsScene: React.FC = () => {
  return (
    <SceneShell>
      <SceneTitle
        eyebrow="02 · 实物规格"
        title="重量不能混着填"
        detail="材质、尺寸、净重、包装重量和产地，都要来自真实资料。"
      />
      <BrowserCrop y={-310} x={-680} zoom={1} />
    </SceneShell>
  );
};
