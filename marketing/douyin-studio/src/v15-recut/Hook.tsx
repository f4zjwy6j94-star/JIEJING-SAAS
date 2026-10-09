import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, clamp, Cursor, Product, SceneProps, Stage, TinyLabel} from './Design';

export const V15Hook: React.FC<SceneProps> = ({durationFrames = 88, productSrc}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / durationFrames;
  const edited = t >= .25;
  const mirrored = t >= .49;
  const typed = Math.min(8, Math.floor(Math.max(0, t - .11) * 58));
  return <Stage>
    <div style={{position: 'absolute', left: 82, top: 262, fontSize: 92, fontWeight: 800, lineHeight: 1.17, letterSpacing: -5}}>
      改一个词<span style={{color: C.accent}}>。</span><br />预览跟着变
    </div>
    <div style={{position: 'absolute', left: 85, right: 95, top: 568, color: C.muted, fontSize: 25, letterSpacing: 4}}>EDIT → PREVIEW</div>
    <div style={{position: 'absolute', left: 84, top: 633, width: 892, height: 177, background: '#222c25', border: `1px solid ${C.line}`, borderRadius: 20, padding: '24px 30px', boxSizing: 'border-box', boxShadow: '0 22px 60px #0005', rotate: `${interpolate(frame, [0, .4 * fps], [-2, 0], clamp)}deg`}}>
      <TinyLabel>标题草稿</TinyLabel>
      <div style={{fontFamily: 'Arial, sans-serif', fontSize: 49, marginTop: 19, color: C.ivory, whiteSpace: 'nowrap'}}>
        <span style={{color: C.accent, background: edited ? '#d9fa791b' : 'transparent'}}>{'Desktop '.slice(0, typed)}</span>Phone Stand<span style={{display: 'inline-block', width: 3, height: 46, background: C.accent, verticalAlign: -8, marginLeft: 6, opacity: frame % 16 < 12 ? 1 : 0}} />
      </div>
    </div>
    <svg width="900" height="260" style={{position: 'absolute', left: 80, top: 780}}><path d="M730 0 C800 110,700 190,550 205" fill="none" stroke={C.accent} strokeWidth="3" strokeDasharray="430" strokeDashoffset={interpolate(t, [.23, .54], [430, 0], clamp)} /><path d="M565 191 L550 205 L570 214" fill="none" stroke={C.accent} strokeWidth="3" opacity={mirrored ? 1 : 0} /></svg>
    <div style={{position: 'absolute', left: 162, top: 923, width: 740, height: 526, borderRadius: 36, background: C.paper, color: C.ink, boxShadow: '0 38px 70px #0006', translate: `0px ${interpolate(frame, [0, .6 * fps], [25, 0], clamp)}px`, rotate: `${interpolate(frame, [0, .6 * fps], [3, 0], clamp)}deg`}}>
      <div style={{position: 'absolute', left: 32, top: 27, fontSize: 24, letterSpacing: 3, opacity: .55}}>预览</div>
      <Product src={productSrc} style={{position: 'absolute', width: 355, height: 350, left: 190, top: 30, scale: interpolate(t, [.42, .75], [1, 1.04], clamp)}} />
      <div style={{position: 'absolute', left: 36, right: 30, bottom: 53, fontFamily: 'Arial, sans-serif', fontWeight: 700, fontSize: 43, whiteSpace: 'nowrap'}}>{mirrored && <span style={{background: C.accent}}>Desktop </span>}Phone Stand</div>
      <div style={{position: 'absolute', left: 36, bottom: 28, width: interpolate(t, [.49, .78], [0, 665], clamp), height: 2, background: '#17201a39'}} />
    </div>
    <Cursor x={interpolate(t, [0, .23, .42, .65], [900, 493, 493, 815], clamp)} y={interpolate(t, [0, .23, .42, .65], [892, 736, 736, 1220], clamp)} pressed={t > .22 && t < .32} />
  </Stage>;
};
