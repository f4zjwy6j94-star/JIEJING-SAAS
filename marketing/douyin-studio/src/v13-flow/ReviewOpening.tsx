import React from "react";
import {Interactive, interpolate, useCurrentFrame} from "remotion";
import {Product, Pointer, ease, font, ink, paper} from "./Shared";

// An original illustrated workflow, not a screen recording or a timed product test.
export const ReviewOpening: React.FC<{sceneDurationFrames?: number}> = ({sceneDurationFrames = 216}) => {
  const frame = useCurrentFrame();
  const progress = frame / Math.max(1, sceneDurationFrames - 1);
  const handoff = interpolate(progress, [0.51, 0.73], [0, 1], ease);

  return <Interactive.Div name="商品到内容的开场" style={{position: "absolute", inset: 0, background: paper, color: ink, fontFamily: font, overflow: "hidden"}}>
    <div style={{position: "absolute", left: -150, top: 445, width: 1050, height: 1050, borderRadius: "50%", background: "radial-gradient(circle,#e0e6d5 0%,#e7eadc90 40%,transparent 70%)", scale: interpolate(progress, [0, 0.52], [0.92, 1.08], ease)}} />
    <Interactive.Div name="开场提问" style={{position: "absolute", left: 84, top: 174, right: 100, fontSize: 102, fontWeight: 800, letterSpacing: -4, lineHeight: 1.16, translate: `0px ${interpolate(progress, [0, 0.08], [28, 0], ease)}px`}}>
      商品图有了。<br />
      <span style={{color: "#5b793f"}}>还卡在写文案？</span>
    </Interactive.Div>

    <div style={{position: "absolute", left: 102, top: 519, width: 802, height: 660, border: "1px solid #d8decc", borderRadius: 34, background: "#fffef980", boxShadow: "0 32px 75px #28473513", opacity: 1 - handoff}}>
      <div style={{position: "absolute", left: 34, top: 27, fontSize: 31, color: "#65745a"}}>商品原图</div>
    </div>
    <Interactive.Div name="同一商品进入资料卡" style={{position: "absolute", left: interpolate(progress, [0.51, 0.73], [90, 20], ease), top: interpolate(progress, [0.51, 0.73], [455, 516], ease), width: 840, height: 810, scale: interpolate(progress, [0, 0.5, 0.73], [1.03, 1, 0.445], ease), transformOrigin: "22% 28%", rotate: interpolate(progress, [0, 0.45, 0.73], ["-4deg", "2deg", "0deg"], ease), filter: "drop-shadow(0 35px 30px #293e2625)", zIndex: 3}}>
      <Product />
    </Interactive.Div>

    <Interactive.Div name="标题待办" style={{position: "absolute", left: 114, top: 1227, borderRadius: 18, padding: "24px 32px", background: "#ffffff", border: "1px solid #d8decc", fontSize: 45, fontWeight: 650, rotate: "-5deg", opacity: interpolate(progress, [0.1, 0.16, 0.51, 0.65], [0, 1, 1, 0], ease), translate: `0px ${interpolate(progress, [0.1, 0.2], [60, 0], ease)}px`, boxShadow: "0 15px 34px #26402915"}}>标题怎么写？</Interactive.Div>
    <Interactive.Div name="卖点待办" style={{position: "absolute", right: 140, top: 1290, borderRadius: 18, padding: "24px 32px", background: "#d2ee7a", fontSize: 45, fontWeight: 650, rotate: "4deg", opacity: interpolate(progress, [0.2, 0.27, 0.51, 0.65], [0, 1, 1, 0], ease), translate: `0px ${interpolate(progress, [0.2, 0.3], [60, 0], ease)}px`, boxShadow: "0 15px 34px #26402915"}}>卖点怎么找？</Interactive.Div>
    <Interactive.Div name="描述待办" style={{position: "absolute", left: 220, top: 1370, borderRadius: 18, padding: "24px 32px", background: ink, color: paper, fontSize: 45, fontWeight: 650, rotate: "-1deg", opacity: interpolate(progress, [0.3, 0.37, 0.51, 0.65], [0, 1, 1, 0], ease), translate: `0px ${interpolate(progress, [0.3, 0.4], [55, 0], ease)}px`, boxShadow: "0 15px 34px #26402915"}}>描述怎么理？</Interactive.Div>

    <Interactive.Div name="资料交给捷境" style={{position: "absolute", left: 84, top: 526, width: 864, height: 862, borderRadius: 34, background: "#fffdf8", border: "1px solid #cbd4c0", opacity: handoff, translate: `0px ${interpolate(progress, [0.51, 0.73], [70, 0], ease)}px`, boxShadow: "0 25px 65px #28473516"}}>
      <div style={{position: "absolute", left: 34, top: 28, fontSize: 39, fontWeight: 750}}>捷境 · 商品资料</div>
      <div style={{position: "absolute", left: 34, top: 110, width: 375, height: 386, background: "#e8ecdf", borderRadius: 20}} />
      <div style={{position: "absolute", left: 455, top: 143, fontSize: 31, color: "#708067"}}>商品信息</div>
      <div style={{position: "absolute", left: 455, top: 203, fontSize: 48, fontWeight: 700}}>桌面支架</div>
      <div style={{position: "absolute", left: 455, top: 290, right: 25, fontSize: 40, lineHeight: 1.65}}>商品原图<br />已知参数<br />销售目标</div>
      <div style={{position: "absolute", left: 34, top: 555, right: 34, padding: "26px 27px", borderRadius: 18, background: "#f0f2e8", fontSize: 38, opacity: interpolate(progress, [0.74, 0.83], [0, 1], ease)}}>为 eBay 准备商品内容</div>
      <div style={{position: "absolute", left: 34, right: 34, bottom: 34, height: 102, borderRadius: 18, background: ink, color: "#fff", fontSize: 43, fontWeight: 650, display: "flex", alignItems: "center", justifyContent: "center", scale: interpolate(progress, [0.89, 0.92, 0.96], [1, 0.97, 1], ease)}}>开始准备 →</div>
    </Interactive.Div>
    {progress > 0.76 ? <Pointer x={interpolate(progress, [0.76, 0.9], [920, 753], ease)} y={interpolate(progress, [0.76, 0.9], [1470, 1310], ease)} click={progress > 0.9 && progress < 0.96} /> : null}
  </Interactive.Div>;
};
