import "./index.css";
import { DouyinCinematicV12Sample, V12Arrival, V12Sources, V12Notes, V12Focus } from "./DouyinCinematicV12";
import { DouyinFactsV11, FactsCoverV11, FactsOpening, FactsSources, FactsQuestion, FactsMethod, FactsAsk, FactsClosing } from "./DouyinFactsV11";
import { Douyin11CompleteV8, Douyin11CoverV8 } from "./Douyin11CompleteV8";
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
      <Composition id="DouyinCinematicV12Sample" component={DouyinCinematicV12Sample} durationInFrames={431} fps={30} width={1080} height={1920} />
      <Composition id="V12Arrival" component={V12Arrival} durationInFrames={137} fps={30} width={1080} height={1920} />
      <Composition id="V12Sources" component={V12Sources} durationInFrames={97} fps={30} width={1080} height={1920} />
      <Composition id="V12Notes" component={V12Notes} durationInFrames={85} fps={30} width={1080} height={1920} />
      <Composition id="V12Focus" component={V12Focus} durationInFrames={112} fps={30} width={1080} height={1920} />
      <Composition id="DouyinFactsV11" component={DouyinFactsV11} durationInFrames={900} fps={30} width={1080} height={1920} />
      <Still id="FactsCoverV11" component={FactsCoverV11} width={1080} height={1920} />
      <Composition id="FactsOpening" component={FactsOpening} durationInFrames={105} fps={30} width={1080} height={1920} />
      <Composition id="FactsSources" component={FactsSources} durationInFrames={135} fps={30} width={1080} height={1920} />
      <Composition id="FactsQuestion" component={FactsQuestion} durationInFrames={120} fps={30} width={1080} height={1920} />
      <Composition id="FactsMethod" component={FactsMethod} durationInFrames={210} fps={30} width={1080} height={1920} />
      <Composition id="FactsAsk" component={FactsAsk} durationInFrames={180} fps={30} width={1080} height={1920} />
      <Composition id="FactsClosing" component={FactsClosing} durationInFrames={150} fps={30} width={1080} height={1920} />
      <Composition id="Douyin11CompleteV8" component={Douyin11CompleteV8} durationInFrames={672} fps={24} width={1080} height={1920} />
      <Still id="Douyin11CoverV8" component={Douyin11CoverV8} width={1080} height={1920} />
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
