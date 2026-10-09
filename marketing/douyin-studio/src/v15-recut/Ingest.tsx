import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, clamp, Product, SceneProps, Stage, TinyLabel} from './Design';

export const V15Ingest: React.FC<SceneProps> = ({durationFrames = 92, productSrc}) => {
  const frame = useCurrentFrame();
  const t = frame / durationFrames;
  const travel = interpolate(t, [.4, .83], [0, 1], clamp);
  return <Stage>
    <div style={{position: 'absolute', left: 82, top: 264, fontSize: 88, fontWeight: 800, letterSpacing: -4, lineHeight: 1.19}}>把资料<br /><span style={{color: C.accent}}>交给捷境。</span></div>
    <TinyLabel style={{position: 'absolute', left: 86, top: 526}}>原图 / 参数 / 销售目标</TinyLabel>
    <svg width="1080" height="800" style={{position: 'absolute', top: 600, left: 0}}>
      <path d="M280 200 Q280 490 540 490 M820 220 Q820 490 540 490 M220 600 Q420 600 540 490 M540 490 L540 750" fill="none" stroke="#566351" strokeWidth="2" />
      <path d="M280 200 Q280 490 540 490 M820 220 Q820 490 540 490 M220 600 Q420 600 540 490" fill="none" stroke={C.accent} strokeWidth="4" strokeDasharray="12 300" strokeDashoffset={-frame * 7} />
      <circle cx="540" cy="490" r={interpolate(t, [.6, .9], [67, 92], clamp)} fill={C.accent} />
      <path d="M519 491 L535 507 L566 472" fill="none" stroke={C.bg} strokeWidth="7" strokeLinecap="round" opacity={travel} />
    </svg>
    <div style={{position: 'absolute', left: 83 + travel * 165, top: 636 + travel * 145, width: 344, height: 350, background: C.paper, borderRadius: 24, boxShadow: '0 25px 50px #0006', rotate: `${-8 + travel * 8}deg`, scale: 1 - travel * .17, opacity: 1 - travel * .4}}>
      <Product src={productSrc} style={{position: 'absolute', width: 275, height: 268, left: 36, top: 24}} />
      <div style={{position: 'absolute', left: 27, bottom: 24, color: C.ink, fontSize: 25, letterSpacing: 3}}>原图</div>
    </div>
    <div style={{position: 'absolute', left: 643 - travel * 190, top: 663 + travel * 140, width: 300, height: 233, background: C.accent, color: C.bg, borderRadius: 8, padding: 33, boxSizing: 'border-box', rotate: `${6 - travel * 6}deg`, scale: 1 - travel * .18, boxShadow: '0 20px 40px #0004', opacity: 1 - travel * .3}}>
      <div style={{fontSize: 25, letterSpacing: 3}}>销售目标</div><div style={{fontSize: 55, fontFamily: 'Arial, sans-serif', marginTop: 29, fontWeight: 700}}>eBay</div>
      <svg width="42" height="42" style={{position: 'absolute', right: 32, bottom: 29}}><path d="M3 38 L36 5 M5 5 H36 V36" stroke={C.bg} strokeWidth="3" fill="none" /></svg>
    </div>
    <div style={{position: 'absolute', left: 87 + travel * 90, top: 1125 - travel * 89, width: 330, height: 220, background: '#30382e', border: `1px solid ${C.line}`, borderRadius: 12, padding: 30, boxSizing: 'border-box', rotate: `${-3 + travel * 3}deg`, opacity: 1 - travel * .4}}>
      <div style={{fontSize: 28, color: C.ivory}}>商品参数</div>
      <div style={{marginTop: 28, height: 4, width: 235, background: '#f2eedf69'}} /><div style={{marginTop: 17, height: 4, width: 167, background: '#f2eedf40'}} /><div style={{marginTop: 17, height: 4, width: 206, background: '#f2eedf40'}} />
    </div>
    <div style={{position: 'absolute', left: 477, top: 1263, opacity: interpolate(t, [.63, .88], [0, 1], clamp), color: C.accent, fontSize: 39, fontWeight: 700, translate: `0px ${interpolate(t, [.63, .88], [30, 0], clamp)}px`}}>捷境</div>
  </Stage>;
};
