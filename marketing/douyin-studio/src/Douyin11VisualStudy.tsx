import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

const font = '"Noto Sans CJK SC", "Microsoft YaHei", sans-serif';
const ink = "#202621";
const cream = "#f1efe6";
const blue = "#3048d8";
const red = "#df502e";
const ease = Easing.bezier(0.22, 1, 0.36, 1);
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const, easing: ease };

const Label = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div style={{ fontSize: 25, fontWeight: 500, letterSpacing: 2, ...style }}>{children}</div>
);
const Brand = ({ dark = false }: { dark?: boolean }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 18, color: dark ? cream : ink }}>
    <Img src={staticFile("brand/jiejing-app-icon.svg")} style={{ width: 64, height: 64 }} />
    <span style={{ fontWeight: 800, fontSize: 42, letterSpacing: 4 }}>捷境</span>
  </div>
);
const Footer = ({ dark = false }: { dark?: boolean }) => (
  <div style={{ position: "absolute", left: 84, right: 150, bottom: 235, display: "flex", justifyContent: "space-between", color: dark ? "#9fb2bb" : "#72766f", fontSize: 23 }}>
    <span>原创示意动效 · 非产品实录</span><span>风格样片 / 待确认</span>
  </div>
);
const Shell = ({ children, color = cream, dark = false }: { children: ReactNode; color?: string; dark?: boolean }) => (
  <AbsoluteFill style={{ background: color, color: dark ? cream : ink, fontFamily: font, overflow: "hidden" }}>
    <div style={{ position: "absolute", left: 84, right: 150, top: 125, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <Brand dark={dark} /><Label style={{ fontSize: 23, opacity: 0.68 }}>当前支持 eBay</Label>
    </div>
    {children}
    <Footer dark={dark} />
  </AbsoluteFill>
);

const PhotoGlyph = () => (
  <svg viewBox="0 0 360 270" width="100%" height="100%" aria-label="抽象图片符号，不是商品照片">
    <rect width="360" height="270" rx="8" fill="#dcded1" />
    <circle cx="270" cy="69" r="30" fill="#f5f3d8" />
    <path d="M-20 250L115 90L210 220L295 138L395 290H-20Z" fill="#858d72" />
    <path d="M-30 302L130 140L260 300Z" fill="#b6c096" />
  </svg>
);

export const FactsFilm = ({ fixedFrame }: { fixedFrame?: number }) => {
  const live = useCurrentFrame();
  const f = fixedFrame ?? live;
  const phase = Math.min(3, Math.floor(f / 90));
  const local = f - phase * 90;
  const lift = interpolate(local, [0, 24], [70, 0], clamp);
  const reveal = interpolate(local, [0, 14], [0, 1], clamp);
  return (
    <Shell>
      {phase === 0 && <>
        <div style={{ position: "absolute", left: 84, top: 320, opacity: reveal, translate: `0 ${lift}px` }}>
          <Label style={{ color: red, marginBottom: 30 }}>给已有 eBay 店铺的你</Label>
          <div style={{ fontSize: 106, lineHeight: 1.16, fontWeight: 900, letterSpacing: -6 }}>图片齐了。<br />资料，<span style={{ color: blue }}>齐了吗？</span></div>
        </div>
        <div style={{ position: "absolute", left: 103, top: 886, width: 430, height: 443, background: "#fffdf6", padding: 28, boxShadow: "0 28px 75px #22251c25", rotate: `${interpolate(local, [0, 75], [-13, -8], clamp)}deg`, translate: `0 ${interpolate(local, [0, 70], [100, 0], clamp)}px` }}>
          <div style={{ height: 280 }}><PhotoGlyph /></div>
          <Label style={{ marginTop: 27 }}>商品图片 / 已提供</Label>
        </div>
        <div style={{ position: "absolute", left: 515, top: 1070, width: 363, height: 272, background: blue, color: "#fff", padding: 36, rotate: `${interpolate(local, [0, 75], [14, 7], clamp)}deg`, boxShadow: "0 28px 75px #24306430" }}>
          <Label style={{ opacity: 0.6 }}>商品参数</Label>
          <div style={{ fontSize: 57, fontWeight: 800, marginTop: 30 }}>尺寸？<br />材质？</div>
        </div>
        <div style={{ position: "absolute", top: 1435, left: 84, width: 792, height: 2, background: "#cbcdc2" }} />
        <div style={{ position: "absolute", top: 1475, left: 84, fontSize: 34 }}>先看事实，再写 Listing。</div>
      </>}
      {phase === 1 && <>
        <div style={{ position: "absolute", left: 84, top: 340, opacity: reveal, translate: `0 ${lift}px` }}>
          <Label style={{ color: blue, marginBottom: 26 }}>01 / 整理</Label>
          <div style={{ fontSize: 108, fontWeight: 900, letterSpacing: -6, lineHeight: 1.16 }}>散落的信息，<br />逐项<span style={{ color: blue }}>理清。</span></div>
        </div>
        <div style={{ position: "absolute", left: 84, top: 820, width: 790, padding: "10px 0", borderTop: `4px solid ${ink}` }}>
          <div style={{ display: "flex", alignItems: "center", height: 156, borderBottom: "2px solid #c9cbc1", translate: `${interpolate(local, [0, 20], [140, 0], clamp)}px 0`, opacity: interpolate(local, [0, 10], [0, 1], clamp) }}><span style={{ color: blue, fontSize: 27, width: 82 }}>01</span><span style={{ fontSize: 51, fontWeight: 700 }}>商品图片</span><span style={{ marginLeft: "auto", fontSize: 28, color: "#70786c" }}>保留来源</span></div>
          <div style={{ display: "flex", alignItems: "center", height: 156, borderBottom: "2px solid #c9cbc1", translate: `${interpolate(local, [8, 28], [140, 0], clamp)}px 0`, opacity: interpolate(local, [8, 18], [0, 1], clamp) }}><span style={{ color: blue, fontSize: 27, width: 82 }}>02</span><span style={{ fontSize: 51, fontWeight: 700 }}>尺寸 / 参数</span><span style={{ marginLeft: "auto", fontSize: 28, color: "#70786c" }}>对应原资料</span></div>
          <div style={{ display: "flex", alignItems: "center", height: 156, borderBottom: "2px solid #c9cbc1", translate: `${interpolate(local, [16, 36], [140, 0], clamp)}px 0`, opacity: interpolate(local, [16, 26], [0, 1], clamp) }}><span style={{ color: red, fontSize: 27, width: 82 }}>03</span><span style={{ fontSize: 51, fontWeight: 700 }}>缺失 / 冲突</span><span style={{ marginLeft: "auto", fontSize: 28, color: red }}>留待核实</span></div>
        </div>
        <div style={{ position: "absolute", left: 84, top: 1444, fontSize: 34 }}>先有依据，才有可核对的文案。</div>
      </>}
      {phase === 2 && <>
        <div style={{ position: "absolute", left: 84, top: 320, opacity: reveal, translate: `0 ${lift}px` }}>
          <Label style={{ color: red, marginBottom: 30 }}>02 / 发现冲突</Label>
          <div style={{ fontSize: 105, fontWeight: 900, lineHeight: 1.16, letterSpacing: -6 }}>资料不一致，<br /><span style={{ color: red }}>先别猜。</span></div>
        </div>
        <div style={{ position: "absolute", left: 90, top: 870, width: 780, height: 350, display: "flex", gap: 30 }}>
          <div style={{ flex: 1, borderTop: `3px solid ${ink}`, paddingTop: 26, rotate: `${interpolate(local, [0, 26], [-7, 0], clamp)}deg` }}><Label>原资料 A</Label><div style={{ fontSize: 112, fontWeight: 900, marginTop: 36 }}>硅胶</div></div>
          <div style={{ flex: 1, borderTop: `3px solid ${ink}`, paddingTop: 26, rotate: `${interpolate(local, [0, 26], [7, 0], clamp)}deg` }}><Label>原资料 B</Label><div style={{ fontSize: 128, lineHeight: 1.5, fontWeight: 900 }}>PVC</div></div>
        </div>
        <div style={{ position: "absolute", left: 94, top: 1260, width: 775, background: red, color: "#fff8ef", padding: "28px 42px", fontSize: 51, fontWeight: 800, scale: interpolate(local, [22, 42], [0.88, 1], clamp), opacity: interpolate(local, [22, 34], [0, 1], clamp) }}>待核实，交由商家确认</div>
        <div style={{ position: "absolute", left: 94, top: 1435, fontSize: 26, color: "#777a70" }}>冲突示例，不代表任何商品的已确认材质。</div>
      </>}
      {phase === 3 && <>
        <div style={{ position: "absolute", left: 70, top: 330, color: "#e4e3d8", fontSize: 730, lineHeight: 1, fontWeight: 900, letterSpacing: -95, rotate: "-8deg" }}>J</div>
        <div style={{ position: "absolute", left: 84, top: 390, opacity: reveal, translate: `0 ${lift}px` }}>
          <Label style={{ color: blue, marginBottom: 36 }}>03 / 回到经营本身</Label>
          <div style={{ fontSize: 106, lineHeight: 1.2, fontWeight: 900, letterSpacing: -6 }}>把资料理清。<br />把决定<br /><span style={{ color: blue }}>留给你。</span></div>
        </div>
        <div style={{ position: "absolute", left: 84, top: 1190, width: 800, borderTop: `3px solid ${ink}`, paddingTop: 40 }}>
          <div style={{ fontSize: 42, fontWeight: 700 }}>捷境 · 跨境电商 AI 经营工作台</div>
          <div style={{ fontSize: 30, marginTop: 25, color: "#626a60" }}>当前支持 eBay</div>
          <div style={{ display: "inline-block", fontSize: 34, marginTop: 68, color: blue, borderBottom: `3px solid ${blue}`, paddingBottom: 12 }}>了解捷境 ↗</div>
        </div>
      </>}
    </Shell>
  );
};

export const RouteConcept = () => (
  <Shell color="#10262b" dark>
    <Label style={{ position: "absolute", left: 84, top: 330, color: "#d0ec68" }}>B / 一条线，把工作串起来</Label>
    <div style={{ position: "absolute", left: 84, top: 410, fontWeight: 900, fontSize: 106, lineHeight: 1.17, letterSpacing: -5 }}>上架之前，<br /><span style={{ color: "#d0ec68" }}>每步有据。</span></div>
    <svg viewBox="0 0 1080 1920" style={{ position: "absolute", inset: 0 }}>
      <path d="M164 840V970Q164 1040 234 1040H712Q786 1040 786 1110V1210Q786 1280 712 1280H245Q170 1280 170 1355V1510" stroke="#d0ec68" fill="none" strokeWidth="14" />
      <circle cx="164" cy="840" r="28" fill="#d0ec68" /><circle cx="465" cy="1040" r="26" fill="#10262b" stroke="#d0ec68" strokeWidth="9" /><circle cx="786" cy="1170" r="28" fill="#d0ec68" /><circle cx="410" cy="1280" r="26" fill="#10262b" stroke="#d0ec68" strokeWidth="9" /><circle cx="170" cy="1510" r="28" fill="#d0ec68" />
    </svg>
    <div style={{ position: "absolute", left: 238, top: 806, fontSize: 39 }}>商品资料</div>
    <div style={{ position: "absolute", left: 384, top: 933, fontSize: 36 }}>整理事实</div>
    <div style={{ position: "absolute", left: 425, top: 1120, fontSize: 39 }}>Listing 文案</div>
    <div style={{ position: "absolute", left: 315, top: 1320, fontSize: 36 }}>商家确认</div>
    <div style={{ position: "absolute", left: 241, top: 1474, fontSize: 36 }}>进入受控发布流程</div>
  </Shell>
);

export const PauseConcept = () => (
  <Shell color="#ec583d">
    <div style={{ position: "absolute", left: 72, top: 308, fontSize: 253, fontWeight: 900, letterSpacing: -20, lineHeight: 1.04 }}>AI 也要<br />懂得<span style={{ color: cream }}>停。</span></div>
    <div style={{ position: "absolute", left: 115, top: 955, width: 620, height: 315, rotate: "-6deg", background: cream, boxShadow: "22px 27px 0 #202621", padding: "33px 48px" }}>
      <Label style={{ marginBottom: 30 }}>C / 先确认，再行动</Label>
      <div style={{ fontWeight: 800, fontSize: 61, lineHeight: 1.3 }}>遇到资料冲突，<br />先确认，再继续。</div>
    </div>
    <div style={{ position: "absolute", left: 85, top: 1430, fontSize: 36, fontWeight: 600 }}>重要决定，留给商家。</div>
  </Shell>
);

const Mini = ({ children, x, y, scale }: { children: ReactNode; x: number; y: number; scale: number }) => (
  <div style={{ position: "absolute", left: x, top: y, width: 1080, height: 1920, transform: `scale(${scale})`, transformOrigin: "top left", overflow: "hidden" }}>{children}</div>
);
export const Douyin11ConceptBoard = () => (
  <AbsoluteFill style={{ fontFamily: font, background: "#e2e3dc", color: ink }}>
    <div style={{ position: "absolute", left: 86, top: 60, fontSize: 54, fontWeight: 800 }}>捷境 / 首条视频视觉提案</div>
    <div style={{ position: "absolute", right: 90, top: 82, fontSize: 25, color: "#667062" }}>11.0 · 方向待确认 · 2026.10.06</div>
    <Mini x={85} y={190} scale={0.61}><FactsFilm fixedFrame={60} /></Mini>
    <Mini x={822} y={190} scale={0.61}><RouteConcept /></Mini>
    <Mini x={1559} y={190} scale={0.61}><PauseConcept /></Mini>
    <div style={{ position: "absolute", left: 86, top: 1420, fontSize: 39, fontWeight: 800 }}>A 资料编辑室 / 推荐</div>
    <div style={{ position: "absolute", left: 823, top: 1420, fontSize: 39, fontWeight: 800 }}>B 经营路线图</div>
    <div style={{ position: "absolute", left: 1560, top: 1420, fontSize: 39, fontWeight: 800 }}>C 先别猜</div>
    <div style={{ position: "absolute", left: 86, top: 1490, fontSize: 29, lineHeight: 1.6 }}>真实问题切入，纸张与文字重组。<br />先让卖家看懂，再建立品牌印象。</div>
    <div style={{ position: "absolute", left: 823, top: 1490, fontSize: 29, lineHeight: 1.6 }}>发光线路串联经营步骤。<br />适合之后解释完整工作流。</div>
    <div style={{ position: "absolute", left: 1560, top: 1490, fontSize: 29, lineHeight: 1.6 }}>强排版与骤停节奏。<br />适合资料冲突、敏感承诺选题。</div>
  </AbsoluteFill>
);

export const Douyin11Storyboard = () => (
  <AbsoluteFill style={{ fontFamily: font, background: "#e2e3dc", color: ink }}>
    <div style={{ position: "absolute", left: 70, top: 38, fontSize: 44, fontWeight: 800 }}>A / 12秒风格样片 · 六帧分镜</div>
    <div style={{ position: "absolute", left: 70, top: 99, fontSize: 24, color: "#65705f" }}>仅审视觉与节奏；非产品实录，无配音、无配乐，方向尚未批准。</div>
    <Mini x={70} y={160} scale={0.48}><FactsFilm fixedFrame={24} /></Mini>
    <Mini x={640} y={160} scale={0.48}><FactsFilm fixedFrame={76} /></Mini>
    <Mini x={1210} y={160} scale={0.48}><FactsFilm fixedFrame={132} /></Mini>
    <Mini x={70} y={1160} scale={0.48}><FactsFilm fixedFrame={188} /></Mini>
    <Mini x={640} y={1160} scale={0.48}><FactsFilm fixedFrame={238} /></Mini>
    <Mini x={1210} y={1160} scale={0.48}><FactsFilm fixedFrame={332} /></Mini>
    <Label style={{ position: "absolute", left: 70, top: 1100 }}>01 / 0.8s 先问具体问题</Label>
    <Label style={{ position: "absolute", left: 640, top: 1100 }}>02 / 2.5s 散落的图与参数</Label>
    <Label style={{ position: "absolute", left: 1210, top: 1100 }}>03 / 4.4s 逐项组织事实</Label>
    <Label style={{ position: "absolute", left: 70, top: 2100 }}>04 / 6.3s 显露材质冲突</Label>
    <Label style={{ position: "absolute", left: 640, top: 2100 }}>05 / 7.9s 停在待核实</Label>
    <Label style={{ position: "absolute", left: 1210, top: 2100 }}>06 / 11.1s 品牌与单一行动</Label>
  </AbsoluteFill>
);
