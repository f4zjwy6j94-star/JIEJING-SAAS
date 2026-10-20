import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {Cursor, Photo, Stage, Tag, move, palette} from './Visual';

// Same licensed example throughout: the motion illustrates a reframing request,
// and does not impersonate a newly completed production image-generation job.
export const Adjust = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const f = frame / fps * 30 * 1.26;
  const prompt = '换成更干净的构图';
  return <Stage dark>
    <Tag dark style={{position:'absolute',left:82,top:165,fontSize:29}}>商品图候选</Tag>
    <div style={{position:'absolute',left:82,top:277,fontSize:83,fontWeight:650,lineHeight:1.2}}>
      画面不合适？<br/><span style={{color:'#dce8c4'}}>说清需求，再调整。</span>
    </div>

    <div style={{position:'absolute',left:78,top:542,width:914,height:765,background:'#c4c9bb',boxShadow:'0 35px 70px #06120a77',rotate:`${move(f,52,95,-1.8,0)}deg`,overflow:'hidden',border:'5px solid #eef1e4',boxSizing:'border-box'}}>
      <Photo kind="collection" style={{scale:move(f,55,101,1.19,1.025),translate:`${move(f,55,101,-34,0)}px ${move(f,55,101,22,0)}px`}}/>
      <div style={{position:'absolute',inset:0,background:'linear-gradient(180deg,#0d1f223d,transparent 24%,transparent 78%,#0d1f2222)'}}/>
      <Tag dark style={{position:'absolute',left:22,top:24,fontSize:26}}>构图调整示例</Tag>
      <svg width="904" height="755" viewBox="0 0 904 755" style={{position:'absolute',left:0,top:0,opacity:move(f,55,72)*move(f,99,112,1,0)}}>
        <rect x={move(f,55,101,74,27)} y={move(f,55,101,104,30)} width={move(f,55,101,710,850)} height={move(f,55,101,550,695)} fill="none" stroke="#faffde" strokeWidth="2.5" strokeDasharray="10 11"/>
        <path d="M28 74V30h45m759 0h45v44M28 681v44h45m759 0h45v-44" fill="none" stroke="#f6ffe3" strokeWidth="5"/>
      </svg>
    </div>

    <div style={{position:'absolute',left:82,top:1346,width:904,height:168,padding:'24px 29px',boxSizing:'border-box',background:palette.cream,color:palette.ink,border:'1px solid #b8c7ad',boxShadow:'0 18px 45px #07150a55',translate:`0 ${move(f,0,23,28,0)}px`}}>
      <div style={{fontSize:25,color:palette.muted,marginBottom:18,letterSpacing:2}}>调整需求</div>
      <div style={{fontSize:39,fontWeight:500,whiteSpace:'nowrap'}}>{prompt.slice(0,Math.round(move(f,4,39)*prompt.length))}<span style={{opacity:f<45 && Math.floor(f/8)%2===0?1:0,color:'#7f9867'}}>|</span></div>
      <div style={{position:'absolute',right:25,top:49,width:72,height:72,borderRadius:'50%',background:f>=52?'#6b8259':palette.ink,color:palette.cream,display:'flex',alignItems:'center',justifyContent:'center',fontSize:49,scale:move(f,49,53,1,.92)*move(f,53,61,1,1/.92)}}>↗</div>
    </div>
    <div style={{opacity:move(f,24,38)*move(f,73,92,1,0)}}>
      <Cursor x={move(f,28,49,1001,919)} y={move(f,28,49,1505,1433)} click={f>=49&&f<72?move(f,49,72,0.01,1):0}/>
    </div>
    <div style={{position:'absolute',left:87,top:1540,fontSize:29,color:'#cfddc0',opacity:move(f,77,99)}}>保留原版本 · 继续按需求打磨</div>
  </Stage>;
};
