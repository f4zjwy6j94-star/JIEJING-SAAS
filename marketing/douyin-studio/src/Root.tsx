import "./index.css";
import { Douyin11TactileV7 } from "./Douyin11TactileV7";
import { Douyin11ReleaseV6, Douyin11ReleaseCover } from "./Douyin11ReleaseV6";
import { releaseTiming } from "./ReleaseV6Timing";
import { Douyin11ContinuousV4 } from "./Douyin11ContinuousV4";
import { continuousTiming } from "./ContinuousV4Timing";
import { Douyin11NarrativeV3 } from "./Douyin11NarrativeV3";
import { Douyin11VoiceoverV2, Douyin11VoiceoverCover } from "./Douyin11VoiceoverV2";
import { voiceoverDuration } from "./VoiceoverV2Timing";
import { Douyin11CompleteV1, Douyin11CompleteCover } from "./Douyin11CompleteV1";
import { FactsFilm, Douyin11ConceptBoard, Douyin11Storyboard } from "./Douyin11VisualStudy";
import { Composition, Still } from "remotion";
import { DouyinLaunch01 } from "./DouyinLaunch01";
import { DouyinCover01 } from "./stills/DouyinCover01";
import { DouyinCoverHorizontal01 } from "./stills/DouyinCoverHorizontal01";
import { JiejingAvatar } from "./stills/JiejingAvatar";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="Douyin11TactileV7" component={Douyin11TactileV7} durationInFrames={342} fps={24} width={720} height={1280} />
      <Composition id="Douyin11ReleaseV6" component={Douyin11ReleaseV6} durationInFrames={releaseTiming.durationInFrames} fps={30} width={1080} height={1920} />
      <Still id="Douyin11ReleaseCover" component={Douyin11ReleaseCover} width={1080} height={1920} />
      <Composition id="Douyin11ContinuousV4" component={Douyin11ContinuousV4} durationInFrames={continuousTiming.duration_frames} fps={30} width={1080} height={1920} />
      <Composition id="Douyin11NarrativeV3" component={Douyin11NarrativeV3} durationInFrames={480} fps={30} width={1080} height={1920} />
      <Composition id="Douyin11VoiceoverV2" component={Douyin11VoiceoverV2} durationInFrames={voiceoverDuration} fps={30} width={1080} height={1920} />
      <Still id="Douyin11VoiceoverCover" component={Douyin11VoiceoverCover} width={1080} height={1920} />
      <Composition id="Douyin11CompleteV1" component={Douyin11CompleteV1} durationInFrames={1078} fps={30} width={1080} height={1920} />
      <Still id="Douyin11CompleteCover" component={Douyin11CompleteCover} width={1080} height={1920} />
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
