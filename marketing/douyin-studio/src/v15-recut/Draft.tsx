import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, clamp, Product, SceneProps, Stage, TinyLabel} from './Design';

export const V15Draft: React.FC<SceneProps> = ({durationFrames = 94, productSrc}) => {
  const frame = useCurrentFrame();
  const t = frame / durationFrames;
  const title = 'Desktop Phone Stand';
  const reveal = (start: number, end: number) => interpolate(t, [start, end], [0, 1], clamp);
  return <Stage dark={false}>
    <TinyLabel style={{position: 'absolute', left: 86, top: 252, color: '#5c685b'}}>从资料，到表达</TinyLabel>
    <div style={{position: 'absolute', left: 79, top: 311, fontSize: 100, fontWeight: 800, lineHeight: 1.1, letterSpacing: -6}}>先有一份<br /><span style={{fontFamily: 'Georgia, serif', fontWeight: 400, fontStyle: 'italic', color: '#6e8056'}}>Draft.</span></div>
    <Product src={productSrc} style={{position: 'absolute', width: 402, height: 430, right: 70, top: 299, rotate: `${interpolate(t, [0, .8], [8, -3], clamp)}deg`, translate: `0px ${interpolate(t, [0, .8], [35, 0], clamp)}px`}} />
    <div style={{position: 'absolute', left: 84, top: 781, width: 892, height: 658, background: '#fdfbf3', border: '1px solid #d1d5c7', borderRadius: 8, boxShadow: '0 29px 65px #26331d25', rotate: `${interpolate(t, [0, .2], [-3, 0], clamp)}deg`}}>
      <div style={{position: 'absolute', left: 38, top: 31, display: 'flex', alignItems: 'center', gap: 17, fontSize: 25, color: '#737d6c'}}><span style={{width: 12, height: 12, borderRadius: 20, background: '#829b54'}} />可编辑草稿</div>
      <div style={{position: 'absolute', left: 40, top: 112, color: '#727969', fontSize: 25, letterSpacing: 4}}>标题</div>
      <div style={{position: 'absolute', left: 40, right: 28, top: 158, fontFamily: 'Arial, sans-serif', fontSize: 55, fontWeight: 700, letterSpacing: -2}}>{title.slice(0, Math.floor(reveal(.02, .33) * title.length))}<span style={{display: 'inline-block', width: 3, height: 52, verticalAlign: -8, background: '#637b45', marginLeft: 5, opacity: t < .43 ? 1 : 0}} /></div>
      <div style={{position: 'absolute', left: 40, right: 40, top: 269, height: 1, background: '#27372429'}} />
      <div style={{position: 'absolute', left: 40, top: 312, opacity: reveal(.25, .46), translate: `0px ${interpolate(t, [.25, .46], [35, 0], clamp)}px`}}><div style={{fontSize: 25, color: '#727969', letterSpacing: 4}}>卖点</div><div style={{fontSize: 45, fontWeight: 700, marginTop: 18}}>说清桌面使用场景</div></div>
      <div style={{position: 'absolute', left: 40, top: 460, opacity: reveal(.55, .79), translate: `0px ${interpolate(t, [.55, .79], [35, 0], clamp)}px`}}><div style={{fontSize: 25, color: '#727969', letterSpacing: 4}}>描述</div><div style={{fontSize: 42, marginTop: 18}}>依据资料，继续完善。</div></div>
    </div>
    <div style={{position: 'absolute', left: 766, top: 1401, padding: '13px 21px', color: C.bg, fontSize: 27, background: C.accent, borderRadius: 60, opacity: reveal(.75, .92), rotate: '-5deg'}}>可编辑 ↗</div>
  </Stage>;
};
