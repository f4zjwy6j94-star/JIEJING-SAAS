import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {spawnSync} from "node:child_process";

const [root, revision = "review"] = process.argv.slice(2);
if (!["review", "website"].includes(revision)) throw new Error("Unknown revision");
if (!root || !path.isAbsolute(root) || !fs.existsSync(root)) throw new Error("Existing absolute V13 root required");
const source = path.join(root, revision === "website" ? "website-film-02/jiejing-v13-website-02-raw.mp4" : "review-film-01/jiejing-v13-new-voice-review-raw.mp4");
const voice = path.join(root, revision === "website" ? "assets/voice-design-website-02.wav" : "assets/voice-design-full-01.wav");
const output = path.join(root, revision === "website" ? "jiejing-v13-26s-website-review-02.mp4" : "jiejing-v13-26s-new-voice-review-01.mp4");
const report = path.join(root, revision === "website" ? "WEBSITE_MEDIA_QA_02.safe.json" : "REVIEW_MEDIA_QA_01.safe.json");
if (fs.existsSync(output) || fs.existsSync(report)) throw new Error("Refusing overwrite");
const hash = p => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
if (hash(voice) !== (revision === "website" ? "9240a64f9d33b2774a6b02bf92ab408762583da18fe68c1c0085eff83143ef38" : "e2bac7bd0849a33418550e8d4c6cb491776644563dc2b6cc34f41457d3d046c1")) throw new Error("Unexpected voice; never fall back to rejected voices");
const linux = p => `/mnt/${p[0].toLowerCase()}${p.slice(2).replaceAll("\\", "/")}`;
const run = (bin, args) => {
  const r = spawnSync("wsl.exe", ["-d", "Ubuntu", "--exec", bin, ...args], {encoding:"utf8", windowsHide:true, maxBuffer:8*1024*1024});
  if (r.status !== 0) throw new Error(`${bin} failed ${r.status}: ${(r.stderr??"").slice(-1600)}`);
  return r;
};
// Original uncompressed narration replaces renderer AAC; captions start at 0.2s.
// No unlicensed music, speed manipulation, or artificial stereo delay.
run("/usr/bin/ffmpeg", ["-v","error","-i",linux(source),"-i",linux(voice),"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-af","loudnorm=I=-16:TP=-1.5:LRA=7,adelay=200:all=1,apad","-t","26","-movflags","+faststart","-n",linux(output)]);
const meta = JSON.parse(run("/usr/bin/ffprobe", ["-v","error","-show_entries","format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels","-of","json",linux(output)]).stdout);
run("/usr/bin/ffmpeg", ["-v","error","-xerror","-i",linux(output),"-map","0:v:0","-map","0:a:0","-f","null","-"]);
const loud = run("/usr/bin/ffmpeg", ["-hide_banner","-i",linux(output),"-af","loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json","-f","null","-"]).stderr;
const metrics = JSON.parse(loud.slice(loud.lastIndexOf("{"), loud.lastIndexOf("}")+1));
const video = meta.streams.find(s => s.codec_name === "h264");
const audio = meta.streams.find(s => s.codec_name === "aac");
const technical = video?.width === 1080 && video?.height === 1920 && video?.nb_frames === "780" && video?.r_frame_rate === "30/1" && audio?.sample_rate === "48000" && audio?.channels === 2 && Math.abs(Number(meta.format.duration)-26)<0.05 && Number(metrics.input_tp) <= -1 && Number(metrics.input_i) >= -18 && Number(metrics.input_i) <= -14;
const result = {created_at:new Date().toISOString(), media:output, sha256:hash(output), raw_render_sha256:hash(source), voice_sha256:hash(voice), meta, full_decode_exit:0, loudness:metrics, technical_check_passed:technical, narration_delay_seconds:0.2, synthetic_narration:true, new_voice_direction_only_not_exact_clone:true, full_speed_visual_and_listening_review:"pending_owner_review", ready_to_publish:false, uploaded:false, published:false};
fs.writeFileSync(report,JSON.stringify(result,null,2)+"\n",{flag:"wx"});
console.log(JSON.stringify(result,null,2));
if (!technical) throw new Error("Technical gate not passed; inspect preserved report");
