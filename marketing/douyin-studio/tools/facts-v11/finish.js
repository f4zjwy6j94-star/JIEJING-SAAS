// ESM mode is explicitly scoped by this tool directory's package.json.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";

const root = process.argv[2];
if (!root || !path.isAbsolute(root) || !fs.existsSync(root)) throw new Error("Expected existing version root.");
const full = path.join(root, "full-v3/full-silent.mp4");
const wav = path.join(root, "soundtrack-v3.wav");
const output = path.join(root, "jiejing-facts-v11-30s-review.mp4");
const report = path.join(root, "MEDIA_QA.safe.json");
const verifyOnly = process.argv[3] === "--verify-existing";
if (fs.existsSync(report) || (fs.existsSync(output) && !verifyOnly)) throw new Error("Refusing overwrite.");
if (verifyOnly && !fs.existsSync(output)) throw new Error("No existing film to verify.");
const linux = p => `/mnt/${p[0].toLowerCase()}${p.slice(2).replaceAll("\\", "/")}`;
const run = (bin, args) => {
  const result = spawnSync("wsl.exe", ["-d", "Ubuntu", "--exec", bin, ...args], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024, windowsHide: true });
  if (result.status !== 0) throw new Error(`${bin} failed ${result.status}: ${(result.stderr ?? "").slice(-1500)}`);
  return result;
};
if (!verifyOnly) run("/usr/bin/ffmpeg", ["-v", "error", "-i", linux(full), "-i", linux(wav), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-af", "loudnorm=I=-18:TP=-1.5:LRA=9,afade=t=out:st=29.4:d=0.6", "-t", "30", "-movflags", "+faststart", "-n", linux(output)]);
const meta = JSON.parse(run("/usr/bin/ffprobe", ["-v", "error", "-show_entries", "format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels", "-of", "json", linux(output)]).stdout);
run("/usr/bin/ffmpeg", ["-v", "error", "-xerror", "-i", linux(output), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"]);
const loud = run("/usr/bin/ffmpeg", ["-hide_banner", "-i", linux(output), "-af", "loudnorm=I=-18:TP=-1.5:LRA=9:print_format=json", "-f", "null", "-"]).stderr;
const metrics = JSON.parse(loud.slice(loud.lastIndexOf("{"), loud.lastIndexOf("}") + 1));
const diff = run("/usr/bin/ffmpeg", ["-hide_banner", "-i", linux(output), "-vn", "-af", "pan=mono|c0=c0-c1,astats=metadata=0:reset=0", "-f", "null", "-"]).stderr;
const channelDifferenceRms = [...diff.matchAll(/RMS level dB:\s*([^\r\n]+)/g)].map(m => m[1]);
const extracts = [];
for (const time of [.8, 2.5, 5.8, 9.7, 13.8, 16, 18.3, 23.5, 27.5]) {
  const image = path.join(root, `final-${time}s.png`);
  if (fs.existsSync(image)) throw new Error(`Refusing overwrite: ${image}`);
  run("/usr/bin/ffmpeg", ["-v", "error", "-ss", String(time), "-i", linux(output), "-frames:v", "1", "-n", linux(image)]);
  extracts.push({ timeSeconds: time, path: image });
}
const hash = p => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
const result = { createdAt: new Date().toISOString(), media: output, sha256: hash(output), meta, fullDecodeExit: 0, loudness: metrics, channelDifferenceRmsDb: channelDifferenceRms, extracts, editorialFrameReview: "separate manual review required", realtimeFullPlaybackReview: "not verified", subjectiveAudioListening: "not verified", noSpeech: true, sourceAudio: "locally generated without samples", paidCalls: 0, platformUploaded: false, platformPublished: false };
fs.writeFileSync(report, JSON.stringify(result, null, 2) + "\n", { flag: "wx" });
console.log(JSON.stringify(result, null, 2));
