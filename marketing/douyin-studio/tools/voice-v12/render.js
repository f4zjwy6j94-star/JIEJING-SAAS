import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { selectComposition, renderStill, renderMedia } from "@remotion/renderer";

const studio = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const [assets, output, mode = "stills"] = process.argv.slice(2);
if (!assets || !output || !path.isAbsolute(assets) || !path.isAbsolute(output) || !["stills", "sample"].includes(mode)) throw new Error("Expected absolute assets, new output, stills|sample");
if (fs.existsSync(output)) throw new Error("Refusing existing output directory");
for (const name of ["noon-unboxing.png", "noon-sorting.png", "noon-detail.png", "v12-sample-narration.wav"]) if (!fs.existsSync(path.join(assets, name))) throw new Error(`Missing ${name}`);
fs.mkdirSync(output, { recursive: true });
const browserExecutable = path.join(studio, "node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
if (!fs.existsSync(browserExecutable)) throw new Error("Existing render browser missing");
const serveUrl = await bundle({ entryPoint: path.join(studio, "src/index.ts"), outDir: path.join(output, "bundle"), publicDir: assets, enableCaching: false, rspack: true, gitSource: null });
const composition = await selectComposition({ serveUrl, id: "DouyinCinematicV12Sample", browserExecutable });
if (mode === "stills") {
  for (const frame of [24, 92, 170, 210, 265, 300, 360, 410]) {
    await renderStill({ serveUrl, composition, browserExecutable, frame, output: path.join(output, `frame-${frame}.png`), imageFormat: "png", overwrite: false });
    console.log(`frame ${frame} complete`);
  }
} else {
  let last = -1;
  await renderMedia({ serveUrl, composition, browserExecutable, outputLocation: path.join(output, "v12-sample-raw.mp4"), codec: "h264", audioCodec: "aac", crf: 18, pixelFormat: "yuv420p", colorSpace: "bt709", imageFormat: "png", concurrency: 2, overwrite: false, onProgress: ({ progress }) => { const step = Math.floor(progress * 10); if (step > last) { last = step; console.log(`render ${step * 10}%`); } } });
}
fs.writeFileSync(path.join(output, "RENDER.safe.json"), JSON.stringify({ id: composition.id, frames: 431, fps: 30, width: 1080, height: 1920, mode, localSyntheticNarration: true, naturalnessReviewed: false, readyToPublish: false }, null, 2), { flag: "wx" });
