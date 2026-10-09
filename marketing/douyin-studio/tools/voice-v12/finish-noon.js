import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {spawnSync} from "node:child_process";

const [root, version = "01"] = process.argv.slice(2);
if (!root || !path.isAbsolute(root) || !fs.existsSync(root) || !/^\d{2}$/.test(version)) throw new Error("Expected existing absolute noon root and two-digit version");
const source = path.join(root, `film-${version}/v12-noon-raw.mp4`);
const voice = path.join(root, "voice-01/narration.wav");
const output = path.join(root, `jiejing-v12-noon-44s-review-v${version}.mp4`);
const report = path.join(root, `MEDIA_QA_V${version}.safe.json`);
if (fs.existsSync(output) || fs.existsSync(report)) throw new Error("Refusing overwrite");
const linux = p => `/mnt/${p[0].toLowerCase()}${p.slice(2).replaceAll("\\", "/")}`;
const run = (bin, args) => {
  const result = spawnSync("wsl.exe", ["-d", "Ubuntu", "--exec", bin, ...args], {encoding: "utf8", windowsHide: true, maxBuffer: 8 * 1024 * 1024});
  if (result.status !== 0) throw new Error(`${bin} failed ${result.status}: ${(result.stderr ?? "").slice(-1600)}`);
  return result;
};
// All twelve unshifted mono lines were concatenated at exact frame boundaries.
// No music of uncertain rights and no inter-channel delay are introduced.
run("/usr/bin/ffmpeg", ["-v", "error", "-i", linux(source), "-i", linux(voice), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-af", "loudnorm=I=-16:TP=-1.5:LRA=9", "-t", "44", "-movflags", "+faststart", "-n", linux(output)]);
const meta = JSON.parse(run("/usr/bin/ffprobe", ["-v", "error", "-show_entries", "format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels", "-of", "json", linux(output)]).stdout);
run("/usr/bin/ffmpeg", ["-v", "error", "-xerror", "-i", linux(output), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"]);
const loud = run("/usr/bin/ffmpeg", ["-hide_banner", "-i", linux(output), "-af", "loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json", "-f", "null", "-"]).stderr;
const metrics = JSON.parse(loud.slice(loud.lastIndexOf("{"), loud.lastIndexOf("}") + 1));
const diff = run("/usr/bin/ffmpeg", ["-hide_banner", "-i", linux(output), "-vn", "-af", "pan=mono|c0=c0-c1,astats=metadata=0:reset=0", "-f", "null", "-"]).stderr;
const result = {created_at: new Date().toISOString(), media: output, sha256: crypto.createHash("sha256").update(fs.readFileSync(output)).digest("hex"), meta, full_decode_exit: 0, loudness: metrics, channel_difference_rms_db: [...diff.matchAll(/RMS level dB:\s*([^\r\n]+)/g)].map(m => m[1]), synthetic_narration: true, paid_calls: 0, full_speed_visual_and_listening_review: "pending", subjective_voice_quality: "pending", ready_to_publish: false, uploaded: false, published: false};
fs.writeFileSync(report, JSON.stringify(result, null, 2) + "\n", {flag: "wx"});
console.log(JSON.stringify(result, null, 2));
