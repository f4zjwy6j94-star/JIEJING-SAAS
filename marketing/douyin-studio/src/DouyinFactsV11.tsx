import React from "react";
import { AbsoluteFill, Easing, Interactive, Sequence, interpolate, useCurrentFrame } from "remotion";

const paper = "#f2f1e9";
const ink = "#143d32";
const acid = "#d5f285";
const sans = '"Microsoft YaHei", "PingFang SC", sans-serif';
const serif = '"SimSun", "Songti SC", serif';
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.22, 1, 0.36, 1) } as const;

// Original vector illustration. Not a supplier photograph, product render or UI proof.
const DrainSculpture: React.FC<{ size?: number; tilt?: number }> = ({ size = 690, tilt = -16 }) => (
  <div style={{ width: size, height: size, transform: `perspective(1400px) rotateX(32deg) rotateZ(${tilt}deg)`, filter: "drop-shadow(10px 40px 30px #183d3238)" }}>
    <svg width={size} height={size} viewBox="0 0 700 700">
      <defs>
        <linearGradient id="v11-body" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#597e69" /><stop offset="0.5" stopColor="#254f42" /><stop offset="1" stopColor="#10392e" /></linearGradient>
        <linearGradient id="v11-ridge" x1="0" y1="0" x2="1" y2="0"><stop stopColor="#62836e" /><stop offset="0.2" stopColor="#355f4b" /><stop offset="1" stopColor="#173a2c" /></linearGradient>
        <clipPath id="v11-round"><rect x="76" y="58" width="548" height="548" rx="158" /></clipPath>
      </defs>
      <rect x="55" y="74" width="590" height="576" rx="173" fill="#12392d" />
      <rect x="55" y="50" width="590" height="576" rx="173" fill="url(#v11-body)" stroke="#718d713d" strokeWidth="3" />
      <circle cx="350" cy="337" r="188" fill="#0b2c24" />
      <g clipPath="url(#v11-round)">
        {Array.from({ length: 23 }, (_, i) => <rect key={i} x={88 + i * 24} y="74" width="14" height="535" rx="7" fill="url(#v11-ridge)" stroke="#78937944" strokeWidth="1.4" />)}
      </g>
      <rect x="543" y="280" width="42" height="134" rx="21" fill="#092c24" />
      <rect x="548" y="279" width="31" height="121" rx="15" fill="#e59b76" />
      <path d="M564 292V382" stroke="#f7c09c" strokeWidth="3" strokeLinecap="round" />
      <path d="M164 79Q318 51 455 70" stroke="#8fac9275" strokeWidth="3" fill="none" />
    </svg>
  </div>
);

const Frame: React.FC<{ children: React.ReactNode; dark?: boolean; chapter: string }> = ({ children, dark = false, chapter }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ background: dark ? ink : paper, color: dark ? paper : ink, fontFamily: sans, overflow: "hidden" }}>
    <AbsoluteFill style={{ backgroundImage: dark ? "radial-gradient(ellipse at 90% 60%,#48684f 0%,transparent 65%)" : "radial-gradient(ellipse at 90% 35%,#ffffff 0%,transparent 60%)" }} />
    <div style={{ position: "absolute", width: 1300, height: 1300, borderRadius: "50%", border: `1px solid ${dark ? "#fafae51c" : "#25453616"}`, top: 400, left: 160, translate: `${interpolate(frame, [0, 210], [0, -25], clamp)}px 0` }} />
    <div style={{ position: "absolute", top: 128, left: 78, right: 120, display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 24, letterSpacing: 2 }}><span>捷境 · AI 电商观察</span><span style={{ opacity: .62 }}>{chapter}</span></div>
    {children}
    <div style={{ position: "absolute", bottom: 292, left: 78, fontSize: 32, opacity: .7 }}>资料核对示例 · 画面为示意</div>
  </AbsoluteFill>;
};

const Headline: React.FC<{ children: React.ReactNode; top?: number; size?: number }> = ({ children, top = 232, size = 92 }) => <div style={{ position: "absolute", top, left: 78, right: 128, fontFamily: serif, fontWeight: 700, fontSize: size, lineHeight: 1.26, letterSpacing: -3 }}>{children}</div>;

export const FactsOpening: React.FC = () => {
  const frame = useCurrentFrame();
  return <Frame chapter="01 / 尺寸冲突">
    <Headline>先别让 AI<br /><span style={{ position: "relative" }}>猜尺寸。<span style={{ display: "block", position: "absolute", left: 0, right: 24, height: 15, bottom: 0, background: acid, zIndex: -1 }} /></span></Headline>
    <div style={{ position: "absolute", width: 650, height: 650, borderRadius: "50%", background: acid, top: 590, left: 200, scale: interpolate(frame, [0, 105], [.9, 1], clamp) }} />
    <Interactive.Div name="旋转商品示意" style={{ position: "absolute", top: 603, left: 155, rotate: `${interpolate(frame, [0, 134], [-6, 4], clamp)}deg`, translate: `0 ${interpolate(frame, [0, 36], [55, 0], clamp)}px` }}><DrainSculpture /></Interactive.Div>
    <Interactive.Div name="第一份尺寸" style={{ position: "absolute", top: 518, left: 72, fontSize: 130, fontFamily: "Georgia, serif", letterSpacing: -7, rotate: "-7deg", translate: `${interpolate(frame, [0, 18], [-40, 0], clamp)}px 0` }}>11.5<span style={{ fontSize: 36, letterSpacing: 0 }}>cm</span></Interactive.Div>
    <Interactive.Div name="第二份尺寸" style={{ position: "absolute", top: 1230, left: 663, fontSize: 125, fontFamily: "Georgia, serif", letterSpacing: -7, rotate: "6deg", opacity: interpolate(frame, [15, 25], [0, 1], clamp), translate: `0 ${interpolate(frame, [15, 43], [35, 0], clamp)}px` }}>20<span style={{ fontSize: 32, letterSpacing: 0, marginLeft: 10 }}>cm</span></Interactive.Div>
    <div style={{ position: "absolute", top: 1410, left: 78, fontSize: 42, lineHeight: 1.5 }}>同一商品页面，<br /><span style={{ opacity: .7 }}>出现两套尺寸。</span></div>
  </Frame>;
};

export const FactsSources: React.FC = () => {
  const frame = useCurrentFrame();
  return <Frame chapter="02 / 看清来源" dark>
    <Headline size={82}>这不是一道<br /><span style={{ color: acid }}>选择题。</span></Headline>
    <div style={{ position: "absolute", top: 565, left: 95, width: 790, height: 365, background: paper, color: ink, padding: 48, rotate: "-4deg", boxShadow: "0 25px 60px #001d2650", translate: `0 ${interpolate(frame, [0, 22], [65, 0], clamp)}px` }}>
      <div style={{ fontSize: 38 }}>摘录 A · 商品详情图</div>
      <div style={{ fontFamily: "Georgia,serif", fontSize: 101, marginTop: 50, letterSpacing: -4 }}>11.5 × 11.5<span style={{ fontSize: 33 }}> cm</span></div>
      <div style={{ height: 9, background: acid, width: interpolate(frame, [10, 40], [0, 520], clamp), marginTop: 22 }} />
    </div>
    <div style={{ position: "absolute", top: 990, left: 123, width: 790, height: 355, border: "2px solid #adc1ad", padding: 48, rotate: "3deg", background: "#1f493b", translate: `0 ${interpolate(frame, [16, 46], [70, 0], clamp)}px`, opacity: interpolate(frame, [15, 30], [0, 1], clamp) }}>
      <div style={{ fontSize: 38, opacity: .82 }}>摘录 B · 尺寸重量栏</div>
      <div style={{ fontFamily: "Georgia,serif", fontSize: 114, marginTop: 45 }}>20 × 20<span style={{ fontSize: 33 }}> cm</span></div>
      <div style={{ height: 1, background: "#a5b79e", marginTop: 30 }} />
    </div>
    <div style={{ position: "absolute", top: 1440, left: 80, fontSize: 42, color: acid }}>文字摘录，不是实测结果。</div>
  </Frame>;
};

export const FactsQuestion: React.FC = () => {
  const frame = useCurrentFrame();
  return <Frame chapter="03 / 不要猜测">
    <Headline size={87}>一个写实物？<br />一个写包装？</Headline>
    <div style={{ position: "absolute", top: 725, left: 38, scale: .7, transformOrigin: "0 0", rotate: `${interpolate(frame, [0, 149], [-4, 4], clamp)}deg` }}><DrainSculpture size={620} tilt={-8} /></div>
    <svg width="530" height="580" viewBox="0 0 530 580" style={{ position: "absolute", top: 643, left: 475, opacity: interpolate(frame, [10, 30], [0, 1], clamp) }}>
      <path d="M30 170L278 65L475 198L221 305Z" fill="#dedfc3" /><path d="M30 170L221 305V555L30 408Z" fill="#c4caaa" /><path d="M221 305L475 198V440L221 555Z" fill="#a7b699" /><path d="M149 119L354 251V488" fill="none" stroke="#f8f5da" strokeWidth="36" />
      <path d="M30 170L278 65L475 198V440L221 555L30 408ZM30 170L221 305L475 198M221 305V555" fill="none" stroke="#849880" strokeWidth="2" />
      <text x="310" y="390" fill={ink} fontSize="155" fontFamily="Georgia" transform="skewY(-20)">?</text>
    </svg>
    <div style={{ position: "absolute", top: 1248, left: 78, width: 845, borderTop: "2px solid #214735", paddingTop: 40 }}>
      <div style={{ fontFamily: serif, fontWeight: 700, fontSize: 64 }}>目前，还不能确定。</div>
      <div style={{ fontSize: 41, marginTop: 24, lineHeight: 1.55, opacity: .78 }}>包装只是待核实的可能，<br />不能直接写进商品参数。</div>
    </div>
  </Frame>;
};

export const FactsMethod: React.FC = () => {
  const frame = useCurrentFrame();
  return <Frame chapter="04 / 分开记录" dark>
    <Headline>不选一个。<br /><span style={{ color: acid }}>先留下问题。</span></Headline>
    <div style={{ position: "absolute", top: 905, left: 84, width: 840, height: 438, border: "2px dashed #b9d2a2", background: "#d5f2850a", borderRadius: 24, opacity: interpolate(frame, [35, 62], [0, 1], clamp) }}>
      <div style={{ position: "absolute", top: 36, left: 42, fontSize: 46, color: acid }}>待核实</div><div style={{ position: "absolute", top: 42, right: 36, fontSize: 36, opacity: .75 }}>保留两个来源</div>
    </div>
    <Interactive.Div name="尺寸A进入待核实区" style={{ position: "absolute", left: interpolate(frame, [36, 108], [90, 120], clamp), top: interpolate(frame, [36, 108], [570, 1048], clamp), width: 360, height: 245, background: paper, color: ink, padding: 35, rotate: `${interpolate(frame, [36, 108], [-5, -2], clamp)}deg`, boxShadow: "0 24px 40px #001b2355" }}>
      <div style={{ fontSize: 36 }}>详情图</div><div style={{ fontSize: 83, fontFamily: "Georgia", marginTop: 24 }}>11.5<span style={{ fontSize: 26, marginLeft: 10 }}>cm</span></div>
    </Interactive.Div>
    <Interactive.Div name="尺寸B进入待核实区" style={{ position: "absolute", left: interpolate(frame, [64, 132], [555, 527], clamp), top: interpolate(frame, [64, 132], [628, 1048], clamp), width: 360, height: 245, background: "#52705a", border: "1px solid #9fb39b", color: paper, padding: 35, rotate: `${interpolate(frame, [64, 132], [7, 2], clamp)}deg`, boxShadow: "0 24px 40px #001b2355" }}>
      <div style={{ fontSize: 36 }}>尺寸栏</div><div style={{ fontSize: 83, fontFamily: "Georgia", marginTop: 24 }}>20<span style={{ fontSize: 26, marginLeft: 10 }}>cm</span></div>
    </Interactive.Div>
    <div style={{ position: "absolute", top: 650, left: 89, fontSize: 49, opacity: interpolate(frame, [120, 152], [0, 1], clamp) }}>尺寸：<span style={{ color: acid }}>待核实</span><span style={{ opacity: .5, marginLeft: 30 }}>— cm</span></div>
    <div style={{ position: "absolute", top: 735, left: 89, fontSize: 39, opacity: interpolate(frame, [133, 160], [0, 1], clamp) }}>未确认之前，先留空。</div>
    <div style={{ position: "absolute", top: 1450, left: 78, fontSize: 41, color: acid }}>方法示范 · 非软件功能演示</div>
  </Frame>;
};

export const FactsAsk: React.FC = () => {
  const frame = useCurrentFrame();
  return <Frame chapter="05 / 问到依据">
    <Headline size={85}>下一步，<br />向供应方核实。</Headline>
    <div style={{ position: "absolute", width: 795, height: 760, top: 596, left: 98, background: "#fafbf3", rotate: "-3deg", boxShadow: "15px 32px 60px #13322225", padding: "55px 50px", translate: `0 ${interpolate(frame, [0, 24], [45, 0], clamp)}px` }}>
      <div style={{ fontSize: 38, color: "#526f57", marginBottom: 46 }}>建议这样问</div>
      <div style={{ fontSize: 56, lineHeight: 1.5 }}>11.5 和 20，</div>
      <div style={{ fontSize: 49, lineHeight: 1.5, opacity: interpolate(frame, [20, 36], [0, 1], clamp) }}>分别指实物还是包装？</div>
      <div style={{ height: 7, background: acid, width: interpolate(frame, [40, 64], [0, 630], clamp), margin: "26px 0 44px" }} />
      <div style={{ fontSize: 43, lineHeight: 1.6, opacity: interpolate(frame, [64, 82], [0, 1], clamp) }}>请给两组实测尺寸，</div>
      <div style={{ fontSize: 43, lineHeight: 1.6, opacity: interpolate(frame, [86, 104], [0, 1], clamp) }}>并注明各自对应对象。</div>
      <div style={{ position: "absolute", bottom: 50, fontSize: 37, color: "#526f57" }}>询问示例 · 未发送</div>
    </div>
    <div style={{ position: "absolute", top: 1450, left: 78, fontSize: 42 }}>拿到依据，再完善上架草稿。</div>
  </Frame>;
};

export const FactsClosing: React.FC = () => {
  const frame = useCurrentFrame();
  return <Frame chapter="06 / 保留判断">
    <Headline size={87}>AI 负责整理。<br /><span style={{ color: "#47674d" }}>事实，先核实。</span></Headline>
    <div style={{ position: "absolute", left: 205, top: 590, width: 595, height: 595, borderRadius: "50%", background: acid }} />
    <div style={{ position: "absolute", top: 622, left: 163, scale: .89, transformOrigin: "50% 50%", rotate: `${interpolate(frame, [0, 179], [-8, -2], clamp)}deg` }}><DrainSculpture size={665} tilt={-13} /></div>
    <div style={{ position: "absolute", top: 1220, left: 153, width: 760, background: ink, color: paper, padding: "26px 40px", fontSize: 41, rotate: "-3deg" }}>尺寸：<span style={{ color: acid }}>待核实</span><span style={{ float: "right", opacity: .5 }}>— cm</span></div>
    <div style={{ position: "absolute", top: 1410, left: 78, fontSize: 38 }}>你遇到过哪种资料冲突？</div>
  </Frame>;
};

// Independent components remain directly connected to the Studio timeline.
export const DouyinFactsV11: React.FC = () => <AbsoluteFill>
  <Sequence name="01 先别猜" durationInFrames={105}><FactsOpening /></Sequence>
  <Sequence name="02 两个来源" from={105} durationInFrames={135}><FactsSources /></Sequence>
  <Sequence name="03 未核实的可能" from={240} durationInFrames={120}><FactsQuestion /></Sequence>
  <Sequence name="04 分开记录" from={360} durationInFrames={210}><FactsMethod /></Sequence>
  <Sequence name="05 核对话术" from={570} durationInFrames={180}><FactsAsk /></Sequence>
  <Sequence name="06 保留判断" from={750} durationInFrames={150}><FactsClosing /></Sequence>
</AbsoluteFill>;

export const FactsCoverV11: React.FC = () => <AbsoluteFill style={{ background: paper, color: ink, fontFamily: sans }}>
  <div style={{ position: "absolute", top: 135, left: 78, fontSize: 30 }}>捷境 · AI 电商观察</div>
  <div style={{ position: "absolute", top: 258, left: 78, fontSize: 100, fontFamily: serif, fontWeight: 700, lineHeight: 1.3 }}>这两个尺寸，<br />AI 该听谁的？</div>
  <div style={{ position: "absolute", top: 654, left: 192, width: 670, height: 670, background: acid, borderRadius: "50%" }} />
  <div style={{ position: "absolute", top: 685, left: 160 }}><DrainSculpture /></div>
  <div style={{ position: "absolute", top: 585, left: 80, fontSize: 121, fontFamily: "Georgia" }}>11.5 <span style={{ fontSize: 42 }}>vs</span> 20</div>
  <div style={{ position: "absolute", top: 1433, left: 78, fontSize: 40 }}>别猜。先核对来源。</div>
</AbsoluteFill>;
