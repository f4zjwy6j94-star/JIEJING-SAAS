import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {bundle} from "@remotion/bundler";
import {selectComposition, renderStill, renderMedia} from "@remotion/renderer";

const studio = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const [assets, output, mode = "stills"] = process.argv.slice(2);
if (!assets || !output || !path.isAbsolute(assets) || !path.isAbsolute(output) || !["stills", "film"].includes(mode)) throw new Error("Expected absolute assets, new output, stills|film");
if (fs.existsSync(output)) throw new Error("Refusing existing output directory");
for (const name of ["noon-unboxing.png", "noon-sorting.png", "noon-detail.png", "noon-working.png", ...Array.from({length: 12}, (_, n) => `noon-voice-01/line-${String(n + 1).padStart(2, "0")}.wav`)]) {
  if (!fs.existsSync(path.join(assets, name))) throw new Error(`Missing ${name}`);
}
const browserExecutable = path.join(studio, "node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
if (!fs.existsSync(browserExecutable)) throw new Error("Existing render browser missing");
fs.mkdirSync(output, {recursive: true});
const serveUrl = await bundle({entryPoint: path.join(studio, "src/index.ts"), outDir: path.join(output, "bundle"), publicDir: assets, enableCaching: false, rspack: true, gitSource: null});
const composition = await selectComposition({serveUrl, id: "DouyinNoonV12", browserExecutable});
if (composition.durationInFrames !== 1320 || composition.fps !== 30 || composition.width !== 1080 || composition.height !== 1920) throw new Error("Unexpected noon metadata");
const reviewFrames = [18, 96, 180, 258, 345, 410, 460, 560, 633, 725, 820, 930, 1050, 1115, 1170, 1240, 1305];
if (mode === "stills") {
  for (const frame of reviewFrames) {
    await renderStill({serveUrl, composition, browserExecutable, frame, output: path.join(output, `frame-${frame}.png`), imageFormat: "png", overwrite: false});
    console.log(`frame ${frame} complete`);
  }
  const cover = await selectComposition({serveUrl, id: "NoonCover", browserExecutable});
  await renderStill({serveUrl, composition: cover, browserExecutable, frame: 0, output: path.join(output, "cover.png"), imageFormat: "png", overwrite: false});
} else {
  let last = -1;
  await renderMedia({serveUrl, composition, browserExecutable, outputLocation: path.join(output, "v12-noon-raw.mp4"), codec: "h264", audioCodec: "aac", crf: 18, pixelFormat: "yuv420p", colorSpace: "bt709", imageFormat: "png", concurrency: 2, overwrite: false, onProgress: ({progress}) => {const step = Math.floor(progress * 10); if (step > last) {last = step; console.log(`render ${step * 10}%`);}}});
}
fs.writeFileSync(path.join(output, "RENDER.safe.json"), JSON.stringify({id: composition.id, frames: 1320, fps: 30, width: 1080, height: 1920, mode, reviewFrames, fullSpeedVisualReview: false, naturalVoiceReview: false, readyToPublish: false}, null, 2), {flag: "wx"});
