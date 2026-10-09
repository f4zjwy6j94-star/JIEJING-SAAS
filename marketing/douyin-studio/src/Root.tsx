import "./index.css";
import {JiejingV16} from "./noon-v16/Film";
import {JiejingV15Recut} from "./v15-recut/Film";
import {V15Hook} from "./v15-recut/Hook";
import {V15Question} from "./v15-recut/Question";
import {V15Ingest} from "./v15-recut/Ingest";
import {V15Draft} from "./v15-recut/Draft";
import {V15Verify} from "./v15-recut/Verify";
import {V15Confirm} from "./v15-recut/Confirm";
import {V15Closing} from "./v15-recut/Closing";
import {EveningV14VisualEdit} from "./evening-v14/Film";
import {V14Hook} from "./evening-v14/Hook";
import {V14Hold} from "./evening-v14/Hold";
import {V14Ask} from "./evening-v14/Ask";
import {V14Evidence} from "./evening-v14/Evidence";
import {V14Draft} from "./evening-v14/Draft";
import {V14End} from "./evening-v14/End";
import {EveningConflict} from "./evening-facts/Conflict";
import {EveningSources} from "./evening-facts/Sources";
import {EveningSeparate} from "./evening-facts/Separate";
import {EveningAsk} from "./evening-facts/Ask";
import {EveningResolve} from "./evening-facts/Resolve";
import {EveningClosing} from "./evening-facts/Closing";
import {DouyinFlowV13Website} from "./DouyinFlowV13Website";
import {WebsiteClose} from "./v13-flow/WebsiteClose";
import {DouyinFlowV13Review} from "./DouyinFlowV13Review";
import {ReviewOpening} from "./v13-flow/ReviewOpening";
import {ReviewClose} from "./v13-flow/ReviewClose";
import {ReviewDraft} from "./v13-flow/ReviewDraft";
import {DouyinFlowV13} from "./DouyinFlowV13";
import {FlowIngest} from "./v13-flow/Ingest";
import {FlowDraft} from "./v13-flow/Draft";
import {FlowEdit} from "./v13-flow/Edit";
import {FlowClose} from "./v13-flow/Close";
import { DouyinNoonV12 } from "./DouyinNoonV12";
import { NoonOpening } from "./v12-noon/Opening";
import { NoonThreshold } from "./v12-noon/Threshold";
import { NoonSources } from "./v12-noon/Sources";
import { NoonTriage } from "./v12-noon/Triage";
import { NoonDraft } from "./v12-noon/Draft";
import { NoonWorkspace } from "./v12-noon/Workspace";
import { NoonReview } from "./v12-noon/Review";
import { NoonClosing } from "./v12-noon/Closing";
import { NoonCover } from "./v12-noon/Cover";
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
      <Composition id="JiejingV16" component={JiejingV16} durationInFrames={660} fps={30} width={1080} height={1920} defaultProps={{withAudio:false}}/>
      <Composition id="JiejingV15Recut" component={JiejingV15Recut} durationInFrames={708} fps={30} width={1080} height={1920}/>
      <Composition id="V15Hook" component={V15Hook} durationInFrames={88} fps={30} width={1080} height={1920} defaultProps={{durationFrames:88}}/>
      <Composition id="V15Question" component={V15Question} durationInFrames={114} fps={30} width={1080} height={1920}/>
      <Composition id="V15Ingest" component={V15Ingest} durationInFrames={92} fps={30} width={1080} height={1920} defaultProps={{durationFrames:92}}/>
      <Composition id="V15Draft" component={V15Draft} durationInFrames={94} fps={30} width={1080} height={1920} defaultProps={{durationFrames:94}}/>
      <Composition id="V15Verify" component={V15Verify} durationInFrames={77} fps={30} width={1080} height={1920} defaultProps={{durationFrames:77}}/>
      <Composition id="V15Confirm" component={V15Confirm} durationInFrames={93} fps={30} width={1080} height={1920}/>
      <Composition id="V15Closing" component={V15Closing} durationInFrames={150} fps={30} width={1080} height={1920}/>
      <Composition id="EveningV14VisualEdit" component={EveningV14VisualEdit} durationInFrames={690} fps={30} width={1080} height={1920}/>
      <Composition id="V14Hook" component={V14Hook} durationInFrames={75} fps={30} width={1080} height={1920}/>
      <Composition id="V14Hold" component={V14Hold} durationInFrames={75} fps={30} width={1080} height={1920}/>
      <Composition id="V14Ask" component={V14Ask} durationInFrames={180} fps={30} width={1080} height={1920}/>
      <Composition id="V14Evidence" component={V14Evidence} durationInFrames={90} fps={30} width={1080} height={1920}/>
      <Composition id="V14Draft" component={V14Draft} durationInFrames={150} fps={30} width={1080} height={1920}/>
      <Composition id="V14End" component={V14End} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="EveningConflict" component={EveningConflict} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="EveningSources" component={EveningSources} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="EveningSeparate" component={EveningSeparate} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="EveningAsk" component={EveningAsk} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="EveningResolve" component={EveningResolve} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="EveningClosing" component={EveningClosing} durationInFrames={120} fps={30} width={1080} height={1920}/>
      <Composition id="DouyinFlowV13Website" component={DouyinFlowV13Website} durationInFrames={780} fps={30} width={1080} height={1920}/>
      <Composition id="WebsiteClose" component={WebsiteClose} durationInFrames={258} fps={30} width={1080} height={1920} defaultProps={{durationFrames:258}}/>
      <Composition id="WebsiteOpening" component={ReviewOpening} durationInFrames={207} fps={30} width={1080} height={1920} defaultProps={{sceneDurationFrames:207}}/>
      <Composition id="WebsiteDraft" component={ReviewDraft} durationInFrames={189} fps={30} width={1080} height={1920} defaultProps={{clearResult:true}}/>
      <Composition id="DouyinFlowV13Review" component={DouyinFlowV13Review} durationInFrames={780} fps={30} width={1080} height={1920}/>
      <Composition id="ReviewOpening" component={ReviewOpening} durationInFrames={219} fps={30} width={1080} height={1920} defaultProps={{sceneDurationFrames:219}}/>
      <Composition id="ReviewClose" component={ReviewClose} durationInFrames={210} fps={30} width={1080} height={1920}/>
      <Composition id="ReviewDraft" component={ReviewDraft} durationInFrames={198} fps={30} width={1080} height={1920}/>
      <Composition id="DouyinFlowV13" component={DouyinFlowV13} durationInFrames={720} fps={30} width={1080} height={1920}/>
      <Composition id="FlowIngest" component={FlowIngest} durationInFrames={228} fps={30} width={1080} height={1920}/>
      <Composition id="FlowDraft" component={FlowDraft} durationInFrames={180} fps={30} width={1080} height={1920}/>
      <Composition id="FlowEdit" component={FlowEdit} durationInFrames={228} fps={30} width={1080} height={1920}/>
      <Composition id="FlowClose" component={FlowClose} durationInFrames={84} fps={30} width={1080} height={1920}/>
      <Composition id="DouyinNoonV12" component={DouyinNoonV12} durationInFrames={1320} fps={30} width={1080} height={1920} />
      <Still id="NoonCover" component={NoonCover} width={1080} height={1920} />
      <Composition id="NoonOpening" component={NoonOpening} durationInFrames={136} fps={30} width={1080} height={1920} />
      <Composition id="NoonThreshold" component={NoonThreshold} durationInFrames={88} fps={30} width={1080} height={1920} />
      <Composition id="NoonSources" component={NoonSources} durationInFrames={200} fps={30} width={1080} height={1920} />
      <Composition id="NoonTriage" component={NoonTriage} durationInFrames={234} fps={30} width={1080} height={1920} />
      <Composition id="NoonDraft" component={NoonDraft} durationInFrames={222} fps={30} width={1080} height={1920} />
      <Composition id="NoonWorkspace" component={NoonWorkspace} durationInFrames={117} fps={30} width={1080} height={1920} />
      <Composition id="NoonReview" component={NoonReview} durationInFrames={135} fps={30} width={1080} height={1920} />
      <Composition id="NoonClosing" component={NoonClosing} durationInFrames={188} fps={30} width={1080} height={1920} />
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
