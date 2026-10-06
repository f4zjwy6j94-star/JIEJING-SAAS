import type { CSSProperties, ReactNode } from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Easing, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";

const paper = "#F3F1EA";
const ink = "#172322";
const blue = "#235BDD";
const lime = "#D7EAA0";
const font = '"Noto Sans CJK SC", sans-serif';
const ease = Easing.bezier(0.22, 1, 0.36, 1);
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const, easing: ease };
const asset = (name: string) => staticFile(`complete-v1/${name}`);
const small: CSSProperties = { fontSize: 28, fontWeight: 500, letterSpacing: 2 };

function Arrow({size = 44, color = "currentColor"}: {size?: number; color?: string}) {
  return <svg width={size} height={size} viewBox="0 0 40 40" fill="none"><path d="M7 20H32M22 9L33 20L22 31" stroke={color} strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function Mark({dark = false}: {dark?: boolean}) {
  return <div style={{position: "absolute", top: 104, left: 78, right: 104, display: "flex", alignItems: "center", color: dark ? paper : ink}}>
    <Img src={asset("brand.svg")} style={{width: 53, height: 53, borderRadius: 13, background: "white"}} />
    <span style={{fontSize: 37, fontWeight: 800, marginLeft: 15, letterSpacing: 1}}>捷境</span>
    <span style={{marginLeft: "auto", fontSize: 24, letterSpacing: 2, opacity: .6}}>私人审看版</span>
  </div>;
}

function Stage({children, dark = false}: {children: ReactNode; dark?: boolean}) {
  return <AbsoluteFill style={{background: dark ? ink : paper, color: dark ? paper : ink, fontFamily: font, overflow: "hidden"}}>
    <div style={{position: "absolute", left: 54, right: 54, top: 187, bottom: 172, borderLeft: `1px solid ${dark ? "#ffffff12" : "#17232210"}`, borderRight: `1px solid ${dark ? "#ffffff12" : "#17232210"}`, pointerEvents: "none"}} />
    {children}<Mark dark={dark} />
  </AbsoluteFill>;
}

function Eyebrow({children, color = blue, style}: {children: ReactNode; color?: string; style?: CSSProperties}) {
  return <div style={{...small, color, ...style}}>{children}</div>;
}

function ProductPhoto({style}: {style?: CSSProperties}) {
  return <div style={{position: "absolute", overflow: "hidden", background: "#7f7d76", ...style}}>
    <Img src={asset("product-original.jpg")} style={{position: "absolute", width: "165%", height: "165%", objectFit: "cover", left: "-42%", top: "-43%"}} />
  </div>;
}

export function CompleteHero({fixedFrame}: {fixedFrame?: number}) {
  const frame = useCurrentFrame();
  const f = fixedFrame ?? frame;
  return <Stage>
    <ProductPhoto style={{left: 216, top: 745, width: 932, height: 1050, borderRadius: 8, rotate: `${interpolate(f, [0, 114], [8, 2.5], clamp)}deg`, scale: interpolate(f, [0, 114], [1.09, 1], clamp), boxShadow: "0 32px 90px #17232240"}} />
    <div style={{position: "absolute", left: 82, top: 275, zIndex: 2}}>
      <Eyebrow style={{marginBottom: 30}}>给已有 eBay 店铺的你</Eyebrow>
      <div style={{fontSize: 83, fontWeight: 700, lineHeight: 1.25, letterSpacing: -3, translate: `0 ${interpolate(f, [0, 17], [48, 0], clamp)}px`, opacity: interpolate(f, [0, 10], [0, 1], clamp)}}>图片齐了。</div>
      <div style={{fontSize: 142, fontWeight: 900, lineHeight: 1.12, letterSpacing: -7, marginTop: 16, translate: `0 ${interpolate(f, [8, 28], [70, 0], clamp)}px`, opacity: interpolate(f, [8, 22], [0, 1], clamp)}}>上架，<br /><span style={{color: blue}}>卡在哪？</span></div>
    </div>
    <div style={{position: "absolute", left: 79, top: 1240, width: 475, background: "#fffdf7", padding: "32px 35px", rotate: "-5deg", boxShadow: "0 20px 50px #101a2430", translate: `${interpolate(f, [28, 54], [-620, 0], clamp)}px 0`}}>
      <Eyebrow color="#776b5a">商品规格</Eyebrow><div style={{fontSize: 49, fontWeight: 700, marginTop: 12}}>还有待确认项 <span style={{color: blue}}>?</span></div>
    </div>
    <div style={{position: "absolute", left: 81, top: 1490, fontSize: 23, color: "#484f48"}}>原始商品图 · 仅作示例</div>
  </Stage>;
}

function ScatteredFacts() {
  const f = useCurrentFrame();
  return <Stage dark>
    <div style={{position: "absolute", left: 83, top: 278}}>
      <Eyebrow color={lime}>01 / 先找到卡点</Eyebrow>
      <div style={{fontSize: 91, fontWeight: 800, lineHeight: 1.24, marginTop: 25, letterSpacing: -4}}>散在几处的资料，<br /><span style={{color: lime}}>先对到一起。</span></div>
    </div>
    <div style={{position: "absolute", left: 120, top: 700, width: 715, height: 675, background: "#fffdf7", color: ink, padding: 55, rotate: `${interpolate(f, [0, 50], [-12, -4], clamp)}deg`, translate: `0 ${interpolate(f, [0, 25], [700, 0], clamp)}px`, boxShadow: "0 28px 70px #0006"}}>
      <div style={{...small, color: "#79786d", marginBottom: 42}}>PRODUCT / 商品资料</div>
      <div style={{fontSize: 61, fontWeight: 800, marginBottom: 32}}>咖啡量勺</div>
      <div style={{display: "flex", justifyContent: "space-between", borderTop: "1px solid #c7c8bd", padding: "29px 0", fontSize: 43}}><span>尺寸</span><span style={{color: "#958d79"}}>待核对</span></div>
      <div style={{display: "flex", justifyContent: "space-between", borderTop: "1px solid #c7c8bd", padding: "29px 0", fontSize: 43}}><span>材质</span><span style={{color: "#958d79"}}>待核对</span></div>
      <div style={{display: "flex", justifyContent: "space-between", borderTop: "1px solid #c7c8bd", padding: "29px 0", fontSize: 43}}><span>包装</span><span style={{color: "#958d79"}}>待核对</span></div>
    </div>
    <ProductPhoto style={{left: 855, top: 1275, width: 330, height: 340, rotate: "8deg", border: "14px solid #fffdf7", boxShadow: "0 25px 70px #0006", translate: `${interpolate(f, [15, 42], [550, 0], clamp)}px 0`}} />
    <div style={{position: "absolute", left: 83, top: 1517, fontSize: 23, color: "#b5c1b2"}}>资料关系示意 · 未确认事实保持待核对</div>
  </Stage>;
}

function Pointer({x,y,press}: {x: number;y: number;press: number}) {
  return <div style={{position: "absolute", left: x, top: y, pointerEvents: "none"}}>
    <div style={{position: "absolute", width: 68, height: 68, left: -34, top: -34, border: `3px solid ${blue}`, borderRadius: "50%", opacity: press, scale: 1 + (1-press)*.4}} />
    <svg viewBox="0 0 36 46" width="32" height="42" style={{filter: "drop-shadow(0 3px 4px #1115)"}}><path d="M3 2L3 36L12 28L20 42L27 38L19 25L31 24Z" fill="white" stroke={ink} strokeWidth="2.3" strokeLinejoin="round" /></svg>
  </div>;
}

function ActualOperation() {
  const f = useCurrentFrame();
  const second = f >= 135;
  const titleF = second ? f-135 : f;
  const sx = 342;
  const sy = 444;
  const scale = 1.89;
  const time=f/30;
  const x=interpolate(time,[0,.9,1.123,3.15,3.405,6.0,6.207,10],[465,465,469.39,469.39,453.7,453.7,611,611],clamp);
  const y=interpolate(time,[0,.9,1.123,3.15,3.405,6.0,6.207,10],[540,540,587.22,587.22,849.81,849.81,758.25,758.25],clamp);
  const press=Math.max(...[1.185,3.857,6.258].map(t=>interpolate(time,[t,t+.07,t+.43],[0,1,0],clamp)));
  return <Stage>
    <div style={{position: "absolute", left: 83, top: 280}}>
      <Eyebrow>{second ? "03 / 逐项核对" : "02 / 整理到捷境"}</Eyebrow>
      <div style={{fontSize: second ? 91 : 99, fontWeight: 800, letterSpacing: -5, lineHeight: 1.18, marginTop: 29, translate: `0 ${interpolate(titleF,[0,15],[26,0],clamp)}px`, opacity: interpolate(titleF,[0,9],[0,1],clamp)}}>{second ? <>草稿，<br /><span style={{color:blue}}>可以逐项核对。</span></> : <>先把资料，<br /><span style={{color:blue}}>放到一处。</span></>}</div>
    </div>
    <div style={{position: "absolute", left: 80, top: 659, width: 899, borderRadius: 24, boxShadow: "0 30px 85px #23333220", overflow: "hidden", background: "white", border: "1px solid #d5d9d0"}}>
      <div style={{height: 65, padding: "0 25px", display: "flex", alignItems: "center", background: "#E8ECE7", borderBottom: "1px solid #cdd4cb", gap: 10}}>
        <div style={{width: 12, height: 12, borderRadius: "50%", background: "#8ba19a"}} /><div style={{width: 12, height: 12, borderRadius: "50%", background: "#b2c1ad"}} />
        <span style={{fontSize: 23, marginLeft: 12, color: "#4f625a"}}>捷境 · 选品与上架</span><span style={{marginLeft: "auto", fontSize: 21, color: "#4f625a"}}>真实界面 / 示例资料</span>
      </div>
      <div style={{height: 827, position: "relative", overflow: "hidden"}}>
        <OffthreadVideo src={asset("operation.mp4")} muted style={{position: "absolute", width: 1280*scale, height: 1000*scale, maxWidth: "none", left: -sx*scale, top: -sy*scale}} />
        <Pointer x={(x-sx)*scale} y={(y-sy)*scale} press={press} />
      </div>
    </div>
    <div style={{position:"absolute",left:83,top:1570,fontSize:22,color:"#66776a"}}>输入 → 保存 → 草稿编辑 · 操作过程实录</div>
  </Stage>;
}

function MissingFacts() {
  const f=useCurrentFrame();
  return <Stage>
    <div style={{position:"absolute",left:83,top:278}}>
      <Eyebrow>04 / 把未知留在明处</Eyebrow>
      <div style={{fontSize:109,fontWeight:900,lineHeight:1.18,letterSpacing:-5,marginTop:25}}>不确定，<br /><span style={{color:blue}}>先补资料。</span></div>
    </div>
    <div style={{position:"absolute",left:84,top:820,width:880}}>
      <div style={{display:"flex",alignItems:"center",height:180,borderTop:`3px solid ${ink}`,translate:`${interpolate(f,[0,23],[200,0],clamp)}px 0`,opacity:interpolate(f,[0,16],[0,1],clamp)}}><span style={{fontSize:28,color:blue,width:92}}>01</span><span style={{fontSize:59,fontWeight:700}}>尺寸</span><span style={{marginLeft:"auto",fontSize:33,padding:"14px 25px",border:"2px dashed #b7b6a9",color:"#7c7b6d"}}>待核对</span></div>
      <div style={{display:"flex",alignItems:"center",height:180,borderTop:"2px solid #c9cebf",translate:`${interpolate(f,[8,31],[200,0],clamp)}px 0`,opacity:interpolate(f,[8,24],[0,1],clamp)}}><span style={{fontSize:28,color:blue,width:92}}>02</span><span style={{fontSize:59,fontWeight:700}}>材质</span><span style={{marginLeft:"auto",fontSize:33,padding:"14px 25px",border:"2px dashed #b7b6a9",color:"#7c7b6d"}}>待核对</span></div>
      <div style={{display:"flex",alignItems:"center",height:180,borderTop:"2px solid #c9cebf",borderBottom:`3px solid ${ink}`,translate:`${interpolate(f,[16,39],[200,0],clamp)}px 0`,opacity:interpolate(f,[16,32],[0,1],clamp)}}><span style={{fontSize:28,color:blue,width:92}}>03</span><span style={{fontSize:59,fontWeight:700}}>包装</span><span style={{marginLeft:"auto",fontSize:33,padding:"14px 25px",border:"2px dashed #b7b6a9",color:"#7c7b6d"}}>待核对</span></div>
    </div>
    <div style={{position:"absolute",left:85,top:1493,fontSize:24,color:"#748071"}}>资料核对示意</div>
  </Stage>;
}

function Confirmation() {
  const f=useCurrentFrame();
  const sweep=interpolate(f,[15,91],[0,1],clamp);
  return <Stage dark>
    <div style={{position:"absolute",left:82,top:280}}>
      <Eyebrow color={lime}>05 / 关键动作，留给你</Eyebrow>
      <div style={{fontSize:112,fontWeight:900,letterSpacing:-5,lineHeight:1.19,marginTop:28}}>每一步，<br /><span style={{color:lime}}>你有决定权。</span></div>
    </div>
    <svg width="900" height="410" viewBox="0 0 900 410" style={{position:"absolute",left:85,top:850}}>
      <path d="M60 90H840" stroke="#516052" strokeWidth="4" />
      <path d="M60 90H840" stroke={lime} strokeWidth="6" strokeDasharray="780" strokeDashoffset={780*(1-sweep)} />
      <circle cx="60" cy="90" r="24" fill={lime} /><circle cx="440" cy="90" r="24" fill={ink} stroke={lime} strokeWidth="5" /><circle cx="820" cy="90" r="24" fill={ink} stroke={lime} strokeWidth="5" />
      <text x="0" y="193" fill={paper} fontSize="39" fontFamily={font}>资料核对</text><text x="357" y="193" fill={paper} fontSize="39" fontFamily={font}>发布预检</text><text x="710" y="193" fill={lime} fontSize="39" fontFamily={font}>商家确认</text>
      <text x="0" y="263" fill="#a3b3a0" fontSize="24" fontFamily={font}>流程示意，不代表已通过预检或刊登</text>
    </svg>
    <div style={{position:"absolute",left:85,top:1280,width:888,height:137,border:`2px solid ${lime}`,borderRadius:6,display:"flex",justifyContent:"space-between",alignItems:"center",padding:"0 36px",opacity:interpolate(f,[40,66],[0,1],clamp),translate:`0 ${interpolate(f,[40,70],[45,0],clamp)}px`}}><span style={{fontSize:54,fontWeight:700}}>由你确认，再继续</span><Arrow color={lime} size={50}/></div>
  </Stage>;
}

function BrandScene() {
  const f=useCurrentFrame();
  return <Stage>
    <div style={{position:"absolute",left:750,top:310,width:420,height:1240,background:"#DFE6D7",rotate:"18deg"}} />
    <div style={{position:"absolute",left:83,top:370,fontSize:30,color:blue,letterSpacing:3}}>从商品资料，走向经营行动。</div>
    <div style={{position:"absolute",left:83,top:565,display:"flex",alignItems:"center",gap:34,translate:`0 ${interpolate(f,[0,26],[70,0],clamp)}px`,opacity:interpolate(f,[0,18],[0,1],clamp)}}><Img src={asset("brand.svg")} style={{width:156,height:156,borderRadius:36,background:"white",boxShadow:"0 18px 60px #17232218"}}/><span style={{fontSize:143,fontWeight:900,letterSpacing:-7}}>捷境</span></div>
    <div style={{position:"absolute",left:87,top:835,fontSize:81,fontWeight:700,lineHeight:1.5,letterSpacing:-3}}>跨境电商<br /><span style={{fontSize:148,fontWeight:900,color:blue,letterSpacing:-7}}>AI CEO</span></div>
    <div style={{position:"absolute",left:88,top:1305,width:865,paddingTop:34,borderTop:`2px solid ${ink}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}><span style={{fontSize:39}}>当前支持 eBay</span><Arrow size={50}/></div>
  </Stage>;
}

function Closing() {
  const f=useCurrentFrame();
  return <Stage dark>
    <div style={{position:"absolute",width:660,height:660,border:"1px solid #d7eaa024",borderRadius:"50%",right:-280,top:500,scale:interpolate(f,[0,126],[.8,1.15],clamp)}} />
    <div style={{position:"absolute",left:83,top:310}}>
      <Eyebrow color={lime}>给已有 eBay 店铺的你</Eyebrow>
      <div style={{fontSize:99,lineHeight:1.3,fontWeight:800,letterSpacing:-4,marginTop:50}}>下一步，</div>
      <div style={{fontSize:133,lineHeight:1.26,fontWeight:900,letterSpacing:-7,color:lime,translate:`0 ${interpolate(f,[5,26],[55,0],clamp)}px`,opacity:interpolate(f,[5,19],[0,1],clamp)}}>了解捷境。</div>
      <div style={{fontSize:38,lineHeight:1.65,color:"#bbc7ba",marginTop:45}}>看看你的商品资料，<br />怎样进入下一步。</div>
    </div>
    <div style={{position:"absolute",left:86,top:1180,width:876,height:150,background:lime,color:ink,padding:"0 42px",display:"flex",alignItems:"center",justifyContent:"space-between",borderRadius:10}}><span style={{fontSize:59,fontWeight:800}}>到主页了解捷境</span><Arrow size={65}/></div>
    <div style={{position:"absolute",left:88,top:1390,fontSize:28,color:"#bbc7ba"}}>跨境电商 AI CEO SaaS · 当前支持 eBay</div>
    <div style={{position:"absolute",left:88,top:1490,fontSize:22,color:"#93a08f"}}>示例资料与流程演示 · AI 合成配音 · 未公开发布</div>
  </Stage>;
}

const captions = [
  {from:6,to:105,text:"图片齐了，上架怎么还卡着？"},
  {from:120,to:237,text:"尺寸、材质、包装，\n散在不同的资料里。"},
  {from:252,to:363,text:"先把已确认的资料，整理到捷境。"},
  {from:387,to:503,text:"核对商品信息，再准备刊登草稿。"},
  {from:552,to:661,text:"缺少的参数，先补资料，别靠猜。"},
  {from:678,to:784,text:"预检之后，关键动作由你确认。"},
  {from:807,to:944,text:"捷境，跨境电商 AI 经营工作台。"},
  {from:958,to:1067,text:"当前支持 eBay。到主页了解捷境。"},
];

function Captions() {
  const f=useCurrentFrame();
  const cap=captions.find(x=>f>=x.from&&f<x.to);
  return <><div style={{position:"absolute",left:80,right:104,top:1605,minHeight:106,display:"flex",justifyContent:"center",alignItems:"center",fontFamily:font,fontSize:38,lineHeight:1.55,fontWeight:500,textAlign:"center",whiteSpace:"pre-line",color:paper,zIndex:20}}>{cap&&<span style={{background:"#172322ee",padding:"13px 24px",borderRadius:9,boxShadow:"0 5px 24px #0001",opacity:interpolate(f,[cap.from,cap.from+4],[0,1],clamp)}}>{cap.text}</span>}</div><div style={{position:"absolute",left:80,right:104,bottom:98,height:3,background:"#87927d25",zIndex:30}}><div style={{height:3,width:`${f/1077*100}%`,background:blue}} /></div></>;
}

export function Douyin11CompleteV1() {
  return <AbsoluteFill>
    <Sequence durationInFrames={114} name="01 真实商品与开头"><CompleteHero/></Sequence>
    <Sequence from={114} durationInFrames={132} name="02 分散资料"><ScatteredFacts/></Sequence>
    <Sequence from={246} durationInFrames={300} name="03 真实保存和草稿编辑"><ActualOperation/></Sequence>
    <Sequence from={546} durationInFrames={126} name="04 缺失事实待核对"><MissingFacts/></Sequence>
    <Sequence from={672} durationInFrames={129} name="05 商家确认边界"><Confirmation/></Sequence>
    <Sequence from={801} durationInFrames={151} name="06 品牌"><BrandScene/></Sequence>
    <Sequence from={952} durationInFrames={126} name="07 了解入口"><Closing/></Sequence>
    <Audio src={asset("soundtrack.wav")} volume={1}/>
    <Captions/>
  </AbsoluteFill>;
}

export function Douyin11CompleteCover() { return <CompleteHero fixedFrame={70}/>; }
