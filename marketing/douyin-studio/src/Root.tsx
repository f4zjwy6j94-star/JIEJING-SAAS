import "./index.css";
import { FactsFilm, Douyin11ConceptBoard, Douyin11Storyboard } from "./Douyin11VisualStudy";
import { Composition, Still } from "remotion";
import { DouyinLaunch01 } from "./DouyinLaunch01";
import { DouyinCover01 } from "./stills/DouyinCover01";
import { DouyinCoverHorizontal01 } from "./stills/DouyinCoverHorizontal01";
import { JiejingAvatar } from "./stills/JiejingAvatar";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="Douyin11StyleA" component={FactsFilm} durationInFrames={360} fps={30} width={1080} height={1920} />
      <Still id="Douyin11ConceptBoard" component={Douyin11ConceptBoard} width={2320} height={1670} />
      <Still id="Douyin11Storyboard" component={Douyin11Storyboard} width={1800} height={2190} />
      <Composition
        id="DouyinLaunch01"
        component={DouyinLaunch01}
        durationInFrames={1125}
        fps={30}
        width={1080}
        height={1920}
      />
      <Still
        id="DouyinCover01"
        component={DouyinCover01}
        width={1080}
        height={1920}
      />
      <Still
        id="DouyinCoverHorizontal01"
        component={DouyinCoverHorizontal01}
        width={1440}
        height={1080}
      />
      <Still
        id="JiejingAvatar"
        component={JiejingAvatar}
        width={1024}
        height={1024}
      />
    </>
  );
};
