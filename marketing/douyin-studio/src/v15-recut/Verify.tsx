import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, clamp, Cursor, Product, SceneProps, Stage, TinyLabel} from './Design';

export const V15Verify: React.FC<SceneProps> = ({durationFrames = 77, productSrc}) => {
  const frame = useCurrentFrame();
  const t = frame / durationFrames;
  const revised = t >= .49;
  return <Stage>
    <div style={{position: 'absolute', left: 82, top: 263, fontSize: 88, fontWeight: 800, letterSpacing: -4, lineHeight: 1.18}}>草稿，<br />还要<span style={{color: C.accent}}>过一遍。</span></div>
    <TinyLabel style={{position: 'absolute', left: 88, top: 518}}>核对信息，再把表达改顺</TinyLabel>
    <div style={{position: 'absolute', left: 83, top: 645, width: 365, height: 604, borderRadius: 20, background: C.paper, color: C.ink, rotate: '-4deg', boxShadow: '0 28px 50px #0006'}}>
      <div style={{position: 'absolute', left: 30, top: 30, fontSize: 25, letterSpacing: 3, color: '#68705f'}}>原资料</div>
      <Product src={productSrc} style={{position: 'absolute', left: 40, top: 101, width: 280, height: 290}} />
      <div style={{position: 'absolute', left: 29, right: 24, top: 421, fontSize: 33, lineHeight: 1.6}}>手机支架<br /><span style={{background: t > .22 ? C.accent : 'transparent'}}>桌面使用</span></div>
    </div>
    <div style={{position: 'absolute', left: 539, top: 695, width: 427, height: 553, border: `1px solid ${C.line}`, borderRadius: 20, background: '#243025', boxShadow: '0 28px 50px #0005', rotate: '3deg'}}>
      <div style={{position: 'absolute', left: 30, top: 30, fontSize: 25, letterSpacing: 3, color: C.muted}}>草稿表达</div>
      <div style={{position: 'absolute', left: 30, right: 26, top: 128, fontSize: 42, fontWeight: 700, lineHeight: 1.5, color: C.ivory}}>{revised ? <>桌面手机支架</> : <>手机支架</>}</div>
      <div style={{position: 'absolute', left: 30, top: 203, height: 3, width: interpolate(t, [.49, .75], [0, 319], clamp), background: C.accent}} />
      <div style={{position: 'absolute', left: 30, right: 24, top: 290, fontSize: 31, color: C.muted, lineHeight: 1.6}}>继续核对参数<br />再完善描述</div>
      <div style={{position: 'absolute', left: 30, bottom: 38, color: C.accent, fontSize: 27, opacity: revised ? 1 : .25}}>编辑中 <span style={{fontSize: 31}}>↗</span></div>
    </div>
    <svg width="170" height="220" style={{position: 'absolute', top: 914, left: 423, zIndex: 4}}><path d="M0 105 C55 105 65 30 145 30" stroke={C.accent} strokeWidth="3" fill="none" strokeDasharray="220" strokeDashoffset={interpolate(t, [.18, .51], [220, 0], clamp)} /><path d="M126 13 L146 30 L126 47" stroke={C.accent} strokeWidth="3" fill="none" opacity={t >= .4 ? 1 : 0} /></svg>
    <Cursor x={interpolate(t, [0, .34, .55, 1], [893, 739, 739, 830], clamp)} y={interpolate(t, [0, .34, .55, 1], [1270, 872, 872, 1164], clamp)} pressed={t > .43 && t < .56} />
    <div style={{position: 'absolute', left: 160, right: 160, top: 1343, display: 'flex', gap: 24, alignItems: 'center', opacity: interpolate(t, [.63, .9], [0, 1], clamp)}}><div style={{height: 1, flex: 1, background: '#f2eedf37'}} /><span style={{fontSize: 33, color: C.ivory}}>改到合适为止</span><div style={{height: 1, flex: 1, background: '#f2eedf37'}} /></div>
  </Stage>;
};
