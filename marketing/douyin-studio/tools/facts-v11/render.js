import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { selectComposition, renderStill, renderMedia } from "@remotion/renderer";

// Explicit new output directory only. No downloads, uploads or old-film overwrites.
const studio = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const output = process.argv[2];
const mode = process.argv[3] ?? "stills";
if (!output || !path.isAbsolute(output) || !["stills", "sample", "full"].includes(mode)) throw new Error("Usage: node render.js <new-absolute-output-directory> stills|sample|full");
if (fs.existsSync(output)) throw new Error("Output already exists; choose a new version directory.");
fs.mkdirSync(output, { recursive: true });
const browserExecutable = path.join(studio, "node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
if (!fs.existsSync(browserExecutable)) throw new Error("Existing local render browser is missing. No automatic install permitted.");
const emptyPublic = path.join(output, "empty-public");
fs.mkdirSync(emptyPublic);
const serveUrl = await bundle({ entryPoint: path.join(studio, "src/index.ts"), outDir: path.join(output, "bundle"), publicDir: emptyPublic, enableCaching: false, rspack: true, gitSource: null });
const composition = await selectComposition({ serveUrl, id: "DouyinFactsV11", browserExecutable });
if (mode === "stills") {
  for (const frame of [24, 75, 175, 290, 415, 480, 550, 705, 827]) {
    await renderStill({ serveUrl, composition, browserExecutable, frame, output: path.join(output, `frame-${frame}.png`), imageFormat: "png", overwrite: false });
    console.log(`still ${frame} complete`);
  }
} else {
  let last = -1;
  await renderMedia({ serveUrl, composition, browserExecutable, outputLocation: path.join(output, `${mode}-silent.mp4`), codec: "h264", crf: 17, pixelFormat: "yuv420p", colorSpace: "bt709", imageFormat: "png", concurrency: 2, overwrite: false, muted: true, frameRange: mode === "sample" ? [0, 389] : undefined, onProgress: ({ progress }) => { const step = Math.floor(progress * 10); if (step > last) { last = step; console.log(`render ${step * 10}%`); } } });
}
fs.writeFileSync(path.join(output, "RENDER.safe.json"), JSON.stringify({ mode, composition: composition.id, width: composition.width, height: composition.height, fps: composition.fps, frames: mode === "sample" ? 390 : composition.durationInFrames, publicAssets: "none", originalVectorArtwork: true, audio: "separate-original-synthesis", uploaded: false }, null, 2), { flag: "wx" });
