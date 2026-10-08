import fs from "node:fs";
import path from "node:path";
// Procedural, sample-free original sound design. Identical L/R; no delayed speech.
// ESM mode is explicitly scoped by this tool directory's package.json.
const target = process.argv[2];
if (!target || !path.isAbsolute(target) || fs.existsSync(target)) throw new Error("Provide a fresh absolute WAV path.");
const sr = 48000, duration = 30, samples = new Float64Array(sr * duration);
function tone(start, hz, length, gain) {
  for (let i = 0; i < length * sr && Math.floor(start * sr) + i < samples.length; i++) {
    const t = i / sr, env = Math.min(1, t / .013) * Math.exp(-t * 4 / length) * Math.min(1, (length - t) / .08);
    samples[Math.floor(start * sr) + i] += gain * env * (Math.sin(2 * Math.PI * hz * t) + .18 * Math.sin(4 * Math.PI * hz * t) * Math.exp(-t * 5));
  }
}
const notes = [261.626, 329.628, 391.995, 493.883, 440, 329.628, 293.665, 391.995];
for (let beat = 0; beat < 57; beat++) {
  const start = .18 + beat * .6;
  if (start > 28.5) break;
  tone(start, notes[beat % notes.length], 1.3, beat % 4 === 0 ? .05 : .022);
  if (beat % 4 === 0) tone(start, beat < 25 ? 130.813 : 146.832, 2.1, .055);
  if (beat % 2 === 0) tone(start + .3, 1174.66, .055, .007);
}
for (const time of [0.3, 3.5, 8, 12, 19, 25]) { tone(time, 523.251, .22, .045); tone(time + .055, 783.991, .32, .035); }
tone(28.4, 523.251, 1.6, .045); tone(28.4, 659.255, 1.6, .032); tone(28.4, 783.991, 1.6, .025);
let peak = 0;
for (let i = 0; i < samples.length; i++) { const t = i / sr; samples[i] *= Math.min(1, t / .08, (duration - t) / .65); peak = Math.max(peak, Math.abs(samples[i])); }
const out = Buffer.alloc(44 + samples.length * 4);
out.write("RIFF"); out.writeUInt32LE(out.length - 8, 4); out.write("WAVEfmt ", 8); out.writeUInt32LE(16, 16); out.writeUInt16LE(1, 20); out.writeUInt16LE(2, 22); out.writeUInt32LE(sr, 24); out.writeUInt32LE(sr * 4, 28); out.writeUInt16LE(4, 32); out.writeUInt16LE(16, 34); out.write("data", 36); out.writeUInt32LE(samples.length * 4, 40);
for (let i = 0; i < samples.length; i++) { const v = Math.round(samples[i] / Math.max(peak, .001) * .4 * 32767); out.writeInt16LE(v, 44 + i * 4); out.writeInt16LE(v, 46 + i * 4); }
fs.writeFileSync(target, out, { flag: "wx" });
console.log(JSON.stringify({ duration, sampleRate: sr, channels: 2, channelDelaySamples: 0, source: "original-procedural-no-samples", maxPCM: .4 }));
