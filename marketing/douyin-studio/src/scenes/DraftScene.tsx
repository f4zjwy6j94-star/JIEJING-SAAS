import { BrowserCrop } from "../components/BrowserCrop";
import { SceneShell } from "../components/SceneShell";
import { SceneTitle } from "../components/SceneTitle";

export const DraftScene: React.FC = () => {
  return (
    <SceneShell tone="mint">
      <SceneTitle
        eyebrow="04 · AI 先整理"
        title="生成待核对草稿"
        detail="捷境把已确认资料组织成标题、描述、类目和 Item specifics。"
      />
      <BrowserCrop y={-1510} x={-260} zoom={1} />
    </SceneShell>
  );
};
