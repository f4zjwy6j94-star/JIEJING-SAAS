import React from "react";
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from "remotion";

export const ink = "#10372e";
export const paper = "#f4f0e6";
export const lime = "#dfff88";
export const coral = "#ff8d70";
export const face = '"Microsoft YaHei", "PingFang SC", sans-serif';
export const numberFace = '"Arial", "Microsoft YaHei", sans-serif';
export const move = (frame: number, start: number, end: number, a: number, b: number) =>
  interpolate(frame, [start, end], [a, b], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.22, 1, 0.36, 1)});

export const Set: React.FC<{children: React.ReactNode; dark?: boolean}> = ({children, dark = false}) => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{background: dark ? "#0b2924" : paper, color: dark ? paper : ink, fontFamily: face, overflow: "hidden"}}>
    <AbsoluteFill style={{background: dark ? `radial-gradient(ellipse at ${30 + f * 0.04}% 47%, #3e6756 0%, transparent 63%)` : "radial-gradient(ellipse at 20% 38%, #ffffff 0%, #f4f0e600 65%)"}} />
    <div style={{position: "absolute", left: -240, top: 1130, width: 1560, height: 600, background: dark ? "#061c1930" : "#d6c8ad19", transform: "rotate(-19deg)", filter: "blur(20px)"}} />
    {children}
  </AbsoluteFill>;
};

// Original vector study: a generic slotted drain mat, not a measurement or a product photograph.
export const Mat: React.FC<{width?: number; angle?: number; tilt?: number; lift?: number}> = ({width = 680, angle = -20, tilt = 52, lift = 0}) => {
  const uid = React.useId().replace(/:/g, "");
  return <div style={{width, height: width * 0.93, position: "relative", transformStyle: "preserve-3d", transform: `perspective(1600px) rotateX(${tilt}deg) rotateZ(${angle}deg) translateY(${-lift}px)`}}>
    <svg viewBox="0 0 550 510" width="100%" height="100%" style={{overflow: "visible", filter: "drop-shadow(24px 42px 22px #00181059)"}}>
      <defs>
        <linearGradient id={`${uid}mat`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#5e9680"/><stop offset=".38" stopColor="#245e4c"/><stop offset="1" stopColor="#123d31"/></linearGradient>
        <linearGradient id={`${uid}rim`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#b6cfb4"/><stop offset=".36" stopColor="#4b8068"/><stop offset="1" stopColor="#123c30"/></linearGradient>
        <mask id={`${uid}slots`}>
          <rect x="40" y="28" width="470" height="440" rx="124" fill="white"/>
          {Array.from({length: 17}, (_, i) => {
            const x = 94 + i * 22;
            const d = Math.abs(i - 8) / 8;
            const h = 326 - d * d * 95;
            return <rect key={i} x={x} y={248 - h / 2} width="10" height={h} rx="5" fill="black"/>;
          })}
        </mask>
      </defs>
      <rect x="40" y="45" width="470" height="438" rx="124" fill="#0a3028"/>
      <rect x="40" y="28" width="470" height="440" rx="124" fill={`url(#${uid}mat)`} mask={`url(#${uid}slots)`}/>
      <rect x="42" y="30" width="466" height="436" rx="122" fill="none" stroke={`url(#${uid}rim)`} strokeWidth="3"/>
      {Array.from({length: 16}, (_, i) => <path key={i} d={`M ${110 + i * 22} ${109 + Math.abs(i - 7.5) * 6} v ${276 - Math.abs(i - 7.5) * 12}`} stroke="#87ae954a" strokeWidth="2" strokeLinecap="round"/>)}
      <rect x="448" y="195" width="35" height="103" rx="17" fill="#062a24"/>
      <rect x="451" y="189" width="29" height="101" rx="14" fill="#e87859"/>
      <path d="M 458 201 v 73" stroke="#ffc6a2" strokeWidth="4" strokeLinecap="round" opacity=".8"/>
    </svg>
  </div>;
};

export const Carton: React.FC<{width?: number; opening?: number}> = ({width = 720, opening = 1}) => <svg width={width} height={width * 0.75} viewBox="0 0 720 540" style={{overflow: "visible", filter: "drop-shadow(20px 38px 30px #3f2f1726)"}}>
  <path d="M100 178 368 100 627 190 354 283Z" fill="#594f36"/>
  <path d="M100 178 354 283 354 497 100 368Z" fill="#bd9c65"/>
  <path d="M354 283 627 190 627 383 354 497Z" fill="#d9b985"/>
  <path d={`M100 178 368 100 ${337 - opening * 49} ${102 - opening * 92} ${100 - opening * 98} ${166 - opening * 62}Z`} fill="#d8bc8b"/>
  <path d={`M368 100 627 190 ${627 + opening * 80} ${188 - opening * 78} ${382 + opening * 59} ${95 - opening * 75}Z`} fill="#e0c697"/>
  <path d={`M100 178 354 283 ${327 - opening * 100} ${283 + opening * 64} ${100 - opening * 90} ${197 + opening * 52}Z`} fill="#ebd4a5"/>
  <path d={`M354 283 627 190 ${627 + opening * 74} ${222 + opening * 60} ${387 + opening * 74} ${317 + opening * 37}Z`} fill="#f2ddb4"/>
  <path d="M354 292 v190" stroke="#9e7e4c" strokeWidth="2"/>
  <path d="M489 388 573 358" stroke="#ad8e61" strokeWidth="4"/>
</svg>;

export const Caption: React.FC<{children: React.ReactNode; dark?: boolean}> = ({children, dark = false}) => <div style={{position: "absolute", left: 90, right: 120, bottom: 268, fontSize: 44, lineHeight: 1.5, textAlign: "center", fontWeight: 500, color: dark ? "#e7ebdc" : "#37564a"}}>{children}</div>;

export const PaperSource: React.FC<{value: string; label: string; rotate?: number; accent?: string}> = ({value, label, rotate = 0, accent = ink}) => <div style={{width: 388, padding: "36px 35px 34px", background: "#fffcf3", color: ink, border: "1px solid #dbd6c5", boxShadow: "0 20px 50px #081e2024", transform: `rotate(${rotate}deg)`}}>
  <div style={{fontSize: 40, letterSpacing: 0, color: "#6d7b6c"}}>{label}</div>
  <div style={{height: 1, background: "#dcdccf", margin: "25px 0"}}/>
  <div style={{fontFamily: numberFace, color: accent, fontSize: 102, fontWeight: 650, letterSpacing: -6, lineHeight: 1}}>{value}<span style={{fontSize: 29, letterSpacing: 0, marginLeft: 8}}>cm</span></div>
  <div style={{marginTop: 31, height: 7, width: "86%", background: "#e0e2d7"}}/>
  <div style={{marginTop: 12, height: 7, width: "58%", background: "#e0e2d7"}}/>
</div>;
