import React from "react";
import {AbsoluteFill, Img, Interactive, staticFile} from "remotion";

export const NoonCover: React.FC = () => <AbsoluteFill style={{backgroundColor: "#1d2c20", color: "#fff8e9", fontFamily: '"Microsoft YaHei", sans-serif'}}>
  <Img name="封面商家桌面" src={staticFile("noon-unboxing.png")} style={{width: "100%", height: "100%", objectFit: "cover"}} />
  <AbsoluteFill style={{background: "linear-gradient(180deg,#172519da,transparent 72%,#17251988)"}} />
  <Interactive.Div name="封面问题" style={{position: "absolute", top: 335, left: 80, right: 120, fontSize: 92, lineHeight: 1.28, letterSpacing: -3, fontWeight: 750}}>货源图齐了，<br/><span style={{color: "#f4d196"}}>上架还卡住？</span></Interactive.Div>
  <Interactive.Div name="封面指向准备流程" style={{position: "absolute", top: 630, left: 85, fontSize: 43, letterSpacing: 3}}>从资料，到草稿。</Interactive.Div>
  <Interactive.Div name="自然品牌署名" style={{position: "absolute", left: 85, top: 1450, fontSize: 44, letterSpacing: 5}}>捷境</Interactive.Div>
</AbsoluteFill>;
