import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";
import {bundle} from "@remotion/bundler";
import {renderMedia, renderStill, selectComposition} from "@remotion/renderer";

const studio = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const [output, voice] = process.argv.slice(2);
if (!output || !path.isAbsolute(output) || fs.existsSync(output)) throw new Error("Fresh absolute output required; no overwrite");
if (voice && (!path.isAbsolute(voice) || !fs.statSync(voice).isFile() || path.extname(voice).toLowerCase() !== ".wav")) throw new Error("Narration candidate must be an existing absolute WAV path; rendering does not certify listening review");
const browserExecutable = path.join(studio, "node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
if (!fs.existsSync(browserExecutable)) throw new Error("Existing local render browser required; no automatic download");
fs.mkdirSync(output, {recursive: true});
const publicDir = path.join(output, "public");
fs.mkdirSync(publicDir);
if (voice) fs.copyFileSync(voice, path.join(publicDir, "v14-narration-candidate.wav"), fs.constants.COPYFILE_EXCL);
const serveUrl = await bundle({entryPoint: path.join(studio, "src/index.ts"), outDir: path.join(output, "bundle"), publicDir, enableCaching: false, rspack: true, gitSource: null});
const inputProps = voice ? {voiceFile: "v14-narration-candidate.wav"} : {};
const composition = await selectComposition({serveUrl, id: "EveningV14VisualEdit", browserExecutable, inputProps});
const hash = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const frames = [];
for (const frame of [0, 43, 120, 201, 296, 408, 461, 525, 643]) {
  const file = path.join(output, `frame-${String(frame).padStart(4, "0")}.png`);
  await renderStill({serveUrl, composition, browserExecutable, inputProps, frame, output: file, imageFormat: "png", overwrite: false});
  frames.push({frame, file, sha256: hash(file)});
  console.log(`frame ${frame} rendered`);
}
// Refuse the rejected silent-film workaround. Still frames and editable source are useful progress.
let film = null;
if (voice) {
  const file = path.join(output, "jiejing-v14-narrated-review.mp4");
  await renderMedia({serveUrl, composition, browserExecutable, inputProps, codec: "h264", audioCodec: "aac", pixelFormat: "yuv420p", colorSpace: "bt709", crf: 18, concurrency: 1, outputLocation: file, overwrite: false});
  film = {file, sha256: hash(file)};
}
fs.writeFileSync(path.join(output, "RENDER.safe.json"), JSON.stringify({created_at: new Date().toISOString(), composition: composition.id, width: composition.width, height: composition.height, fps: composition.fps, duration_seconds: composition.durationInFrames/composition.fps, frames, film, narration_file: voice || null, narration_sha256: voice ? hash(voice) : null, timing_and_full_av_review_passed: false, ready_to_publish: false, limitation: "Narration and complete timed audiovisual review are required. No silent substitute is exported."}, null, 2), {flag: "wx"});
