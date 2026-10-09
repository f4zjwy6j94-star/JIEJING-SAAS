import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";
import {bundle} from "@remotion/bundler";
import {selectComposition, renderStill, renderMedia} from "@remotion/renderer";

const studio = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const [assets, output, mode = "frames", revision = "review"] = process.argv.slice(2);
if (!["review", "website"].includes(revision)) throw new Error("Unknown revision");
const compositionId = revision === "website" ? "DouyinFlowV13Website" : "DouyinFlowV13Review";
if (!assets || !output || !path.isAbsolute(assets) || !path.isAbsolute(output) || !["frames", "film"].includes(mode)) {
  throw new Error("Expected absolute assets, fresh output, and frames|film");
}
if (fs.existsSync(output)) throw new Error("Refusing existing output; preserve earlier review files");
const timingPath = path.join(studio, revision === "website" ? "src/V13WebsiteTiming.json" : "src/V13ReviewTiming.json");
const timing = JSON.parse(fs.readFileSync(timingPath, "utf8"));
if (timing.voiceFile !== (revision === "website" ? "voice-design-website-02.wav" : "voice-design-full-01.wav")) throw new Error("Only the matching new full voice is allowed; no rejected audio fallback");
const {openingEnd, draftEnd, editEnd} = timing.scenes;
if (![timing.durationFrames, openingEnd, draftEnd, editEnd].every(Number.isInteger) || !(0 < openingEnd && openingEnd < draftEnd && draftEnd < editEnd && editEnd < timing.durationFrames)) throw new Error("Invalid scene timing");
if (timing.durationFrames < 720 || timing.durationFrames > 1050) throw new Error("Expected a deliberately paced 24–35 second review film");
if (!Array.isArray(timing.captions) || timing.captions.length === 0 || timing.captions.some((c) => typeof c.text !== "string" || !c.text.trim() || !Number.isFinite(c.startMs) || !Number.isFinite(c.endMs) || c.startMs < 0 || c.endMs <= c.startMs || c.endMs > (timing.durationFrames / 30 - 0.2) * 1000)) throw new Error("Invalid captions or duration truncates narration");
for (const name of ["v13-product.png", timing.voiceFile]) if (!fs.existsSync(path.join(assets, name))) throw new Error(`Missing ${name}`);
const hash = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
if (revision === "website" && hash(path.join(assets, timing.voiceFile)) !== timing.voiceSha256) throw new Error("Voice SHA mismatch");
const browserExecutable = path.join(studio, "node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe");
if (!fs.existsSync(browserExecutable)) throw new Error("Existing local render browser unavailable; no automatic download");
fs.mkdirSync(output, {recursive: true});
const serveUrl = await bundle({entryPoint: path.join(studio, "src/index.ts"), outDir: path.join(output, "bundle"), publicDir: assets, enableCaching: false, rspack: true, gitSource: null});
const composition = await selectComposition({serveUrl, id: compositionId, browserExecutable});
if (composition.durationInFrames !== timing.durationFrames || composition.fps !== 30 || composition.width !== 1080 || composition.height !== 1920) throw new Error("Root metadata must match the new full narration");
const frames = [...new Set([0, Math.round(openingEnd * 0.32), Math.round(openingEnd * 0.64), openingEnd - 1, openingEnd + Math.round((draftEnd - openingEnd) * 0.45), draftEnd - 1, draftEnd + Math.round((editEnd - draftEnd) * 0.32), draftEnd + Math.round((editEnd - draftEnd) * 0.65), editEnd - 1, editEnd + Math.round((timing.durationFrames - editEnd) * 0.55), timing.durationFrames - 1])];
let mediaPath = null;
if (mode === "frames") {
  for (const frame of frames) {
    await renderStill({serveUrl, composition, browserExecutable, frame, output: path.join(output, `frame-${String(frame).padStart(4, "0")}.png`), imageFormat: "png", overwrite: false});
    console.log(`frame ${frame}`);
  }
} else {
  mediaPath = path.join(output, revision === "website" ? "jiejing-v13-website-02-raw.mp4" : "jiejing-v13-new-voice-review-raw.mp4");
  let last = -1;
  await renderMedia({serveUrl, composition, browserExecutable, outputLocation: mediaPath, codec: "h264", audioCodec: "aac", crf: 18, pixelFormat: "yuv420p", colorSpace: "bt709", imageFormat: "png", concurrency: 2, overwrite: false, onProgress: ({progress}) => {
    const step = Math.floor(progress * 10);
    if (step > last) {last = step; console.log(`film ${step * 10}%`);}
  }});
}
fs.writeFileSync(path.join(output, "RENDER.safe.json"), JSON.stringify({version: `V13 ${revision} owner review`, mode, composition: compositionId, durationFrames: timing.durationFrames, fps: 30, reviewFrames: frames, voiceFile: timing.voiceFile, voiceSha256: hash(path.join(assets, timing.voiceFile)), timingSha256: hash(timingPath), productSha256: hash(path.join(assets, "v13-product.png")), mediaPath, mediaSha256: mediaPath ? hash(mediaPath) : null, contains_owner_rejected_serena_voice: false, status: "owner_full_review_pending", full_visual_review: false, natural_voice_listening_review: false, ready_to_publish: false, publication_performed: false}, null, 2), {flag: "wx"});
