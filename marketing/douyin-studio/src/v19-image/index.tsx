import React from 'react';
import {Audio} from '@remotion/media';
import {Composition,Folder,Series,registerRoot,staticFile,useVideoConfig} from 'remotion';
import {Caption} from './Caption';
import {Opening} from './Opening';
import {Results} from './Results';
import {Request} from './Request';
import {Candidates} from './Candidates';
import {Review} from './Review';
import {Handoff} from './Handoff';
import {Close} from './Close';
import {Generate} from './Generate';
import {Expansion} from './Expansion';
import {Benefit} from './Benefit';
import {Cover} from './Cover';
import {Concept} from './Concept';
import {Adjust} from './Adjust';

export const Film:React.FC<{withAudio:boolean}>=({withAudio})=>{const {fps}=useVideoConfig();return <>
  <Series>
    <Series.Sequence durationInFrames={101} premountFor={fps} name="Product-images-blocking-listing"><Opening/></Series.Sequence>
    <Series.Sequence durationInFrames={126} premountFor={fps} name="No-source-concept-direction"><Concept/><Caption captions={[{text:'还没拍图，可以先用商品资料，\n做概念参考。',startMs:40,endMs:3957,timestampMs:null,confidence:null}]}/></Series.Sequence>
    <Series.Sequence durationInFrames={142} premountFor={fps} name="Authorized-source-and-request"><Request/><Caption captions={[{text:'有供应商授权图，就交给捷境，说清需求。',startMs:40,endMs:4497,timestampMs:null,confidence:null}]}/></Series.Sequence>
    <Series.Sequence durationInFrames={140} premountFor={fps} name="Jiejing-image-generation"><Generate/><Caption captions={[{text:'捷境AI帮你生成，\n场景图、陈列图，还有细节图。',startMs:40,endMs:4250,timestampMs:null,confidence:null}]}/></Series.Sequence>
    <Series.Sequence durationInFrames={135} premountFor={fps} name="Less-image-production-work"><Benefit/><Caption captions={[{text:'先让AI出图，少做从零构图、\n反复找背景的工作。',startMs:40,endMs:4276,timestampMs:null,confidence:null}]}/></Series.Sequence>
    <Series.Sequence durationInFrames={93} premountFor={fps} name="Revise-image-requirements"><Adjust/><Caption captions={[{text:'想换构图，就修改需求，继续生成。',startMs:40,endMs:2776,timestampMs:null,confidence:null}]}/></Series.Sequence>
    <Series.Sequence durationInFrames={105} premountFor={fps} name="Reviewed-candidate-to-product-draft"><Handoff/><Caption captions={[{text:'核对后选好图片，带回商品草稿。',startMs:40,endMs:3105,timestampMs:null,confidence:null}]}/></Series.Sequence>
    <Series.Sequence durationInFrames={90} premountFor={fps} name="Start-your-product-images"><Close/></Series.Sequence>
  </Series>
  {withAudio&&<Audio src={staticFile('audio/narration-image-opening-02.wav')} premountFor={fps}/>}
 </>};
const Root=()=><>
 <Composition id="JiejingV19" component={Film} width={1080} height={1920} fps={30} durationInFrames={932} defaultProps={{withAudio:false}}/>
 <Folder name="V19-scenes">
  <Composition id="V19Opening" component={Opening} width={1080} height={1920} fps={30} durationInFrames={101}/>
  <Composition id="V19Concept" component={Concept} width={1080} height={1920} fps={30} durationInFrames={126}/>
  <Composition id="V19Adjust" component={Adjust} width={1080} height={1920} fps={30} durationInFrames={93}/>
  <Composition id="V19Results" component={Results} width={1080} height={1920} fps={30} durationInFrames={144}/>
 <Composition id="V19Request" component={Request} width={1080} height={1920} fps={30} durationInFrames={142}/>
 <Composition id="V19Candidates" component={Candidates} width={1080} height={1920} fps={30} durationInFrames={80}/>
  <Composition id="V19Review" component={Review} width={1080} height={1920} fps={30} durationInFrames={114}/>
  <Composition id="V19Handoff" component={Handoff} width={1080} height={1920} fps={30} durationInFrames={105}/>
 <Composition id="V19Close" component={Close} width={1080} height={1920} fps={30} durationInFrames={90}/>
 <Composition id="V19Generate" component={Generate} width={1080} height={1920} fps={30} durationInFrames={140}/>
 <Composition id="V19Expansion" component={Expansion} width={1080} height={1920} fps={30} durationInFrames={122}/>
 <Composition id="V19Benefit" component={Benefit} width={1080} height={1920} fps={30} durationInFrames={135}/>
 <Composition id="V19CoverPortrait" component={Cover} width={1080} height={1920} fps={30} durationInFrames={1}/>
 <Composition id="V19CoverLandscape" component={Cover} width={1280} height={720} fps={30} durationInFrames={1}/>
 </Folder>
</>;
registerRoot(Root);
