import {Audio} from '@remotion/media';
import {AbsoluteFill, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {releaseTiming} from './ReleaseV6Timing';

const asset=(name:string)=>staticFile(`complete-v8/${name}`);
const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
const cuts=[0,80,170,254,346,436,506,672];

function FilmShot({name,stillMode}:{name:string;stillMode:boolean}) {
  return <AbsoluteFill>{stillMode?<Img src={asset(`${name}-preview.png`)} style={{width:'100%',height:'100%',objectFit:'cover'}}/>:<OffthreadVideo src={asset(`${name}.mp4`)} muted style={{width:'100%',height:'100%',objectFit:'cover'}}/>}</AbsoluteFill>;
}

export function Douyin11CompleteV8({stillMode=false,includeAudio=true}:{stillMode?:boolean;includeAudio?:boolean}) {
  const frame=useCurrentFrame();const t=frame/24;
  const shot=Math.max(0,cuts.findIndex((c,i)=>frame>=c&&frame<(cuts[i+1]??673)));
  const local=frame-cuts[shot];const dark=shot===1||shot===4||shot===5;
  const caption=releaseTiming.captions.find(c=>t*1000>=c.startMs&&t*1000<c.endMs)?.text??'';
  const reveal=interpolate(local,[0,9],[0,1],clamp);
  return <AbsoluteFill style={{fontFamily:'"JiejingFilm",sans-serif',background:'#EBE8DF',color:dark?'#FFFFFF':'#172B34'}}>
    <style>{`@font-face{font-family:JiejingFilm;src:url('${asset('sans.otf')}');font-weight:100 600;}@font-face{font-family:JiejingFilm;src:url('${asset('bold.otf')}');font-weight:650 950;}`}</style>
    <Sequence durationInFrames={80} name="01 Merchant materials" premountFor={24}><FilmShot name="01_materials" stillMode={stillMode}/></Sequence>
    <Sequence from={80} durationInFrames={90} name="02 Jiejing brand space" premountFor={24}><FilmShot name="02_brand" stillMode={stillMode}/></Sequence>
    <Sequence from={170} durationInFrames={84} name="03 Real input example" premountFor={24}><FilmShot name="03_input" stillMode={stillMode}/></Sequence>
    <Sequence from={254} durationInFrames={92} name="04 Editorial preparation" premountFor={24}><FilmShot name="04_editorial" stillMode={stillMode}/></Sequence>
    <Sequence from={346} durationInFrames={90} name="05 Merchant confirmation" premountFor={24}><FilmShot name="05_confirm" stillMode={stillMode}/></Sequence>
    <Sequence from={436} durationInFrames={70} name="06 eBay first" premountFor={24}><FilmShot name="06_world" stillMode={stillMode}/></Sequence>
    <Sequence from={506} durationInFrames={166} name="07 Website invitation" premountFor={24}><FilmShot name="07_open_path" stillMode={stillMode}/></Sequence>
    {includeAudio?<Audio src={asset('soundtrack.wav')}/>:null}
    <AbsoluteFill style={{background:dark?'linear-gradient(180deg,#051023AB 0%,#05102388 23%,transparent 48%,transparent 69%,#071227D9 100%)':'linear-gradient(180deg,#F3F0E898 0%,transparent 31%,transparent 67%,#F0EDE5ED 100%)'}}/>
    <div style={{position:'absolute',left:64,right:160,top:91,display:'flex',alignItems:'center',justifyContent:'space-between',fontSize:32,fontWeight:750,letterSpacing:2}}>
      <span>捷境</span><span style={{fontSize:19,fontWeight:500,letterSpacing:1.2,opacity:.80}}>跨境电商 AI CEO</span>
    </div>
    <div style={{position:'absolute',left:66,right:165,top:225,opacity:reveal,translate:`0 ${interpolate(local,[0,13],[15,0],clamp)}px`}}>
      {shot===0?<><div style={{fontSize:83,fontWeight:800,lineHeight:1.19,letterSpacing:-2}}>商品有了。</div><div style={{fontSize:69,fontWeight:700,lineHeight:1.35,marginTop:12}}>准备还一堆？</div><div style={{width:66,height:7,background:'#D46135',marginTop:32}}/></>:null}
      {shot===1?<><div style={{fontSize:35,letterSpacing:5,opacity:.85}}>跨境电商</div><div style={{fontSize:83,fontWeight:750,lineHeight:1.2,letterSpacing:1,marginTop:12}}>AI CEO</div></>:null}
      {shot===2?<><div style={{fontSize:76,fontWeight:750,lineHeight:1.2}}>用中文，<br/>说清经营目标。</div><div style={{fontSize:25,marginTop:28,opacity:.75}}>下方为真实界面的输入示例</div></>:null}
      {shot===3?<><div style={{fontSize:36,fontWeight:500,letterSpacing:2}}>从真实资料出发</div><div style={{fontSize:72,fontWeight:750,lineHeight:1.3,marginTop:17}}>调研与内容准备</div></>:null}
      {shot===4?<><div style={{fontSize:74,fontWeight:750,lineHeight:1.25}}>你来核对。<br/>你来确认。</div><div style={{fontSize:27,marginTop:24,color:'#EDD6B8'}}>预检通过后，受控发布</div></>:null}
      {shot===5?<><div style={{fontSize:36,letterSpacing:2,opacity:.85}}>当前支持</div><div style={{fontSize:96,fontWeight:750,marginTop:10}}>eBay</div></>:null}
      {shot===6?<><div style={{fontSize:93,fontWeight:800,lineHeight:1.2,letterSpacing:-2}}>从一件商品<br/>开始。</div><div style={{marginTop:38,display:'flex',gap:19,alignItems:'center',fontSize:43,fontWeight:600}}><span style={{width:10,height:49,background:'#D45B2B'}}/><span>jiejing.shop</span><span style={{fontSize:36,translate:`${interpolate(local,[12,75],[0,13],clamp)}px 0`}}>↗</span></div></>:null}
    </div>
    {shot===6?<div style={{position:'absolute',left:66,right:160,top:885,textAlign:'center',opacity:interpolate(local,[20,38],[0,1],clamp),scale:interpolate(local,[20,75],[.93,1],clamp)}}>
      <div style={{fontSize:152,fontWeight:800,letterSpacing:10,color:'#15354B',textShadow:'0 8px 28px #FFFFFF99'}}>捷境</div>
      <div style={{fontSize:29,letterSpacing:4,marginTop:15}}>跨境电商 AI CEO</div>
    </div>:null}
    {shot===6?<div style={{position:'absolute',left:66,right:160,bottom:437,opacity:interpolate(local,[69,87],[0,1],clamp),fontSize:25,fontWeight:500,lineHeight:1.7,color:'#203444'}}>
      <div>后续规划：Amazon · TikTok Shop · 抖音</div>
      <div style={{fontSize:22,opacity:.78}}>以上平台尚未接入</div>
    </div>:null}
    <div style={{position:'absolute',left:65,right:160,bottom:281,minHeight:116,display:'flex',alignItems:'center',justifyContent:'center',textAlign:'center',fontSize:43,fontWeight:550,lineHeight:1.5,textShadow:dark?'0 2px 12px #0006':'0 1px 8px #FFFFFF88'}}>{caption}</div>
    <div style={{position:'absolute',left:66,bottom:222,fontSize:19,letterSpacing:.5,opacity:.75}}>AI 合成画面与配音 · 流程示意</div>
    <div style={{position:'absolute',left:66,right:160,bottom:182,height:2,background:dark?'#FFFFFF21':'#152B3221'}}><div style={{height:'100%',width:`${interpolate(frame,[0,671],[0,100],clamp)}%`,background:dark?'#D69666':'#244C87'}}/></div>
  </AbsoluteFill>;
}

export function Douyin11CoverV8() {
  return <AbsoluteFill style={{fontFamily:'"JiejingFilm",sans-serif',background:'#152133',color:'#FFFFFF'}}>
    <style>{`@font-face{font-family:JiejingFilm;src:url('${asset('bold.otf')}');font-weight:700;}`}</style>
    <Img src={asset('02_brand-preview.png')} style={{height:'100%',width:'100%',objectFit:'cover'}}/>
    <AbsoluteFill style={{background:'linear-gradient(180deg,#07101CCC 0%,transparent 60%,#07101CDD 100%)'}}/>
    <div style={{position:'absolute',left:76,top:165,fontSize:40,fontWeight:700}}>捷境 · 跨境电商 AI CEO</div>
    <div style={{position:'absolute',left:76,top:294,fontSize:99,fontWeight:700,lineHeight:1.22}}>商品有了，<br/>接下来怎么做？</div>
    <div style={{position:'absolute',left:78,bottom:268,fontSize:40}}>从一件商品开始 · 当前支持 eBay</div>
    <div style={{position:'absolute',left:78,bottom:204,fontSize:27,opacity:.8}}>jiejing.shop</div>
  </AbsoluteFill>;
}
