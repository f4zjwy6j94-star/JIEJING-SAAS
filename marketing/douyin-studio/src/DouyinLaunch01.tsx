import { Audio } from "@remotion/media";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { staticFile } from "remotion";
import { CaptionLayer } from "./components/CaptionLayer";
import { CommerceScene } from "./scenes/CommerceScene";
import { CtaScene } from "./scenes/CtaScene";
import { DraftScene } from "./scenes/DraftScene";
import { GuardrailsScene } from "./scenes/GuardrailsScene";
import { HookScene } from "./scenes/HookScene";
import { IdentityScene } from "./scenes/IdentityScene";
import { SpecsScene } from "./scenes/SpecsScene";

export const DouyinLaunch01: React.FC = () => {
  return (
    <>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={105} name="Hook">
          <HookScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 10 })}
        />
        <TransitionSeries.Sequence durationInFrames={180} name="Identity">
          <IdentityScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 10 })}
        />
        <TransitionSeries.Sequence durationInFrames={180} name="Specs">
          <SpecsScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 10 })}
        />
        <TransitionSeries.Sequence durationInFrames={180} name="Commerce">
          <CommerceScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 10 })}
        />
        <TransitionSeries.Sequence durationInFrames={180} name="Draft">
          <DraftScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 10 })}
        />
        <TransitionSeries.Sequence durationInFrames={180} name="Guardrails">
          <GuardrailsScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 10 })}
        />
        <TransitionSeries.Sequence durationInFrames={180} name="CTA">
          <CtaScene />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <Audio src={staticFile("audio/launch-01-voice.wav")} volume={0.95} />
      <CaptionLayer />
    </>
  );
};
