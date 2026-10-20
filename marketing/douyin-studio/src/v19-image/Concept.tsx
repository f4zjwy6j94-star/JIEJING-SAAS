import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {Stage, Tag, move, palette} from './Visual';

// Original schematic artwork: this is a concept board, not a generated product photo.
export const Concept = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const f = frame / fps * 30;
  return <Stage>
    <Tag style={{position:'absolute',left:82,top:164,fontSize:29}}>还没拍图，先找画面方向</Tag>
    <div style={{position:'absolute',left:82,top:278,fontSize:82,fontWeight:650,lineHeight:1.2}}>
      从商品资料，<br/><span style={{color:'#56764a'}}>到画面方向。</span>
    </div>

    <div style={{position:'absolute',left:82,right:82,top:535,height:207,padding:'28px 32px',boxSizing:'border-box',background:palette.cream,border:'1px solid #bbc5b5',boxShadow:'0 18px 35px #2132290c',rotate:`${move(f,0,28,-2,0)}deg`,translate:`0 ${move(f,0,25,24,0)}px`}}>
      <div style={{fontSize:27,color:palette.muted,letterSpacing:2,marginBottom:20}}>商品资料 + 画面需求</div>
      <div style={{fontSize:39,fontWeight:500}}>旅行收纳用品 · 简洁陈列</div>
      <div style={{fontSize:31,color:'#637460',marginTop:13,opacity:move(f,8,28)}}>明亮背景 / 留白构图 / 旅行氛围</div>
    </div>

    <svg width="88" height="94" style={{position:'absolute',left:493,top:748}} viewBox="0 0 88 94">
      <path d="M44 1v68m-17-17 17 17 17-17" fill="none" stroke="#748663" strokeWidth="3" strokeDasharray="115" strokeDashoffset={115*(1-move(f,12,40))}/>
      <circle cx="44" r="7" fill="#8da171" opacity={move(f,25,42)} cy={move(f,25,58,14,61)}/>
    </svg>

    <div style={{position:'absolute',left:110,top:834,width:877,height:630,background:'#cdd5c3',rotate:`${move(f,16,60,3,1.5)}deg`,translate:`0 ${move(f,16,54,65,0)}px`,opacity:move(f,16,39)}}/>
    <div style={{position:'absolute',left:82,top:808,width:896,height:641,background:'#f7f6ee',border:'1px solid #bac5b4',boxShadow:'0 25px 55px #26382c22',rotate:`${move(f,20,65,-4,-1)}deg`,translate:`0 ${move(f,20,56,55,0)}px`,opacity:move(f,20,39),overflow:'hidden'}}>
      <div style={{position:'absolute',inset:0,backgroundImage:'linear-gradient(#687d5010 1px,transparent 1px),linear-gradient(90deg,#687d5010 1px,transparent 1px)',backgroundSize:'56px 56px',opacity:.7}}/>
      <Tag style={{position:'absolute',left:27,top:26,fontSize:29,background:'#ecf1df'}}>概念构图</Tag>
      <div style={{position:'absolute',right:30,top:47,fontSize:27,color:'#819079',letterSpacing:3}}>构图草案</div>
      <svg width="846" height="491" viewBox="0 0 846 491" style={{position:'absolute',left:25,top:112}}>
        <defs>
          <linearGradient id="v19-concept-plane" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#edf0df"/><stop offset="1" stopColor="#c6d1b4"/>
          </linearGradient>
        </defs>
        <ellipse cx="428" cy="354" rx="266" ry="58" fill="#23361a" opacity={move(f,33,69,0,.075)}/>
        <g opacity={move(f,27,52)} style={{translate:`0 ${move(f,27,69,29,0)}px`}}>
          <path d="M107 270 352 158 726 307 454 435Z" fill="url(#v19-concept-plane)" stroke="#a5b391" strokeWidth="2"/>
          <path d="M107 270v13l347 166 272-128v-14" fill="none" stroke="#b4bea2" strokeWidth="2"/>
          <path d="M177 111 385 78 443 138 233 174Z" fill="#e3e8d7" fillOpacity={move(f,42,82)} stroke="#617451" strokeWidth="3" pathLength="1" strokeDasharray="1" strokeDashoffset={1-move(f,35,77)}/>
          <path d="m177 111 5 179 56 64-5-180m210-36-2 173-203 43m-61-243 208-33 58 60-210 36Z" fill="none" stroke="#607451" strokeWidth="3" strokeLinejoin="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1-move(f,39,86)}/>
          <path d="m194 149 29 32 164-28m-4-57-2 203-125 37" fill="none" stroke="#81916f" strokeWidth="2" pathLength="1" strokeDasharray="1" strokeDashoffset={1-move(f,46,92)}/>
          <path d="m472 231 119-43 100 48-121 50-98-55v90l98 51 120-49v-87m-120 50v86" fill="#d3dcc5" fillOpacity={move(f,60,96,0,.55)} stroke="#758665" strokeWidth="3" strokeLinejoin="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1-move(f,50,99)}/>
          <path d="m499 238 75 35 91-37M301 40v-19m-13 7 13 12 13-12M737 201h44m-12-12 12 12-12 12" fill="none" stroke="#91a375" strokeWidth="2.5" opacity={move(f,64,95)}/>
        </g>
        <g opacity={move(f,68,99)} fill="#66765b" fontFamily="Microsoft YaHei,sans-serif" fontSize="24">
          <text x="608" y="141">前后层次</text><path d="m666 155-18 42" fill="none" stroke="#92a078" strokeWidth="2"/>
          <text x="72" y="405">简洁留白</text>
        </g>
      </svg>
    </div>
    <div style={{position:'absolute',left:88,top:1502,fontSize:37,color:palette.green,opacity:move(f,66,92)}}>先探索画面方向</div>
  </Stage>;
};
