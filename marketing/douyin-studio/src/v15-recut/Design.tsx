import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';

export const C = {
  bg: '#161b19', ivory: '#f2eedf', accent: '#d9fa79', muted: '#a9b0a4',
  coral: '#ef9a7f', line: '#465148', ink: '#17201a', paper: '#e8e5d8',
};
export const font = '"Microsoft YaHei", "PingFang SC", Arial, sans-serif';
export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export type SceneProps = {durationFrames?: number; productSrc?: string};

export const Stage: React.FC<{children: React.ReactNode; dark?: boolean}> = ({children, dark = true}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <AbsoluteFill style={{background: dark ? C.bg : C.ivory, color: dark ? C.ivory : C.ink, fontFamily: font, overflow: 'hidden'}}>
    <div style={{position: 'absolute', width: 1180, height: 1180, left: -100, top: 280, borderRadius: '50%', background: dark ? 'radial-gradient(circle,rgba(163,186,124,.12),transparent 66%)' : 'radial-gradient(circle,#fffdf2,transparent 68%)', translate: `${interpolate(frame, [0, 4 * fps], [0, 45], clamp)}px 0px`}} />
    <div style={{position: 'absolute', left: 58, right: 58, top: 192, height: 1, background: dark ? '#f2eedf17' : '#17201a1c'}} />
    {children}
  </AbsoluteFill>;
};

export const Product: React.FC<{src?: string; style?: React.CSSProperties}> = ({src = staticFile('v15-product.png'), style}) => <Img src={src} style={{width: 480, height: 480, objectFit: 'contain', filter: 'drop-shadow(0px 30px 30px rgba(0,0,0,.25))', ...style}} />;

export const Cursor: React.FC<{x: number; y: number; pressed?: boolean; color?: string}> = ({x, y, pressed = false, color = C.ivory}) => <svg width="58" height="70" viewBox="0 0 58 70" style={{position: 'absolute', left: x, top: y, scale: pressed ? .87 : 1, filter: 'drop-shadow(0 5px 4px #0005)', zIndex: 6}}><path d="M6 4 L46 42 L27 44 L20 62 Z" fill={color} stroke={C.bg} strokeWidth="3" strokeLinejoin="round" /></svg>;

export const TinyLabel: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => <div style={{fontSize: 25, lineHeight: 1.2, letterSpacing: 4, fontWeight: 600, color: C.muted, ...style}}>{children}</div>;
