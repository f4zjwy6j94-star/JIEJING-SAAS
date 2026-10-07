import {Audio} from '@remotion/media';
import {AbsoluteFill, Easing, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from 'remotion';

const asset=(name:string)=>staticFile(`creative-v7/${name}`);
const captions=[
  {start:0,end:3.3,text:'有了商品，上架怎么还这么累？'},
  {start:3.38,end:7.1,text:'捷境，是你的跨境电商 AI CEO。'},
  {start:7.2,end:8.48,text:'用中文说目标，'},
  {start:8.48,end:10.6,text:'给真实图片和参数，'},
  {start:10.66,end:12,text:'它协助调研，'},
  {start:12,end:14.25,text:'准备商品页和素材。'},
];

/** Visual-direction study; the voice and final film are not owner-approved. */
export function Douyin11TactileV7({includeAudio=true}:{includeAudio?:boolean}) {
  const frame=useCurrentFrame();const t=frame/24;
  const caption=captions.find(c=>t>=c.start&&t<c.end)?.text??'';
  const title=interpolate(frame,[81,95,161,170],[0,1,1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.2,.8,.2,1)});
  return <AbsoluteFill style={{background:'#29271F',fontFamily:'"TactileSans",sans-serif',color:'#FFF'}}>
    <style>{`@font-face{font-family:TactileSans;src:url('${asset('sans.otf')}');font-weight:100 600;}@font-face{font-family:TactileSans;src:url('${asset('bold.otf')}');font-weight:650 950;}`}</style>
    <OffthreadVideo src={asset('footage.mp4')} muted/>
    {includeAudio?<Audio src={asset('soundtrack.wav')}/>:null}
    <div style={{position:'absolute',inset:0,background:'linear-gradient(180deg,rgba(10,12,10,.24) 0%,transparent 27%,transparent 69%,rgba(10,12,10,.62) 100%)'}}/>
    <div style={{position:'absolute',left:42,top:61,right:104,display:'flex',alignItems:'center',justifyContent:'space-between',fontSize:22,fontWeight:700,letterSpacing:2}}><span>捷境</span><span style={{fontSize:13,letterSpacing:1,fontWeight:500,opacity:.85}}>视觉方向样片 · 未发布</span></div>
    <div style={{position:'absolute',left:45,top:142,opacity:title,translate:`0 ${interpolate(frame,[81,102],[13,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}px`}}>
      <div style={{fontSize:70,fontWeight:800,letterSpacing:3,textShadow:'0 2px 20px #0003'}}>捷境</div>
      <div style={{fontSize:23,fontWeight:500,letterSpacing:2,marginTop:5,textShadow:'0 2px 15px #0004'}}>跨境电商 AI CEO</div>
    </div>
    {t>=7.1&&t<10.55?<div style={{position:'absolute',left:42,top:116,fontSize:17,background:'#1A272BCF',padding:'7px 11px',borderRadius:3}}>真实本地界面 · 输入示例</div>:null}
    {frame>=171&&frame<254?<div style={{position:'absolute',left:42,right:80,top:560,opacity:interpolate(frame,[171,181],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}),transform:`translateY(${interpolate(frame,[171,190],[18,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}px)`}}>
      <div style={{fontSize:15,letterSpacing:1,color:'#283832',marginBottom:12}}>输入处局部放大</div>
      <div style={{position:'relative',height:118,overflow:'hidden',borderRadius:13,boxShadow:'0 18px 55px #18241B36',border:'1px solid #FFFFFFA0'}}>
        <Img src={asset('workspace-goal.png')} style={{position:'absolute',width:2124,maxWidth:'none',left:-612,top:-1570}}/>
      </div>
    </div>:null}
    <div style={{position:'absolute',left:43,right:102,bottom:174,minHeight:75,display:'flex',alignItems:'center',justifyContent:'center',fontSize:27,fontWeight:550,lineHeight:1.55,textAlign:'center',textShadow:'0 2px 10px #0008'}}>{caption}</div>
    <div style={{position:'absolute',left:44,bottom:133,fontSize:12,letterSpacing:.4,color:'#EEE8DE',opacity:.85}}>原创三维画面与示意道具 · AI 合成配音</div>
  </AbsoluteFill>;
}
