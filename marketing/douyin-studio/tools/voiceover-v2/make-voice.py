from pathlib import Path
import json, wave, hashlib, numpy as np, sherpa_onnx

out=Path('/workspace/jiejing-deliverables/11.0/20261006-voiceover-v2')
assets=out/'assets'/'explainer-v2';assets.mkdir(parents=True,exist_ok=True)
p=Path('/workspace/toolchains/jiejing-video-voice/kokoro-multi-lang-v1_1')
k=sherpa_onnx.OfflineTtsKokoroModelConfig(model=str(p/'model.onnx'),voices=str(p/'voices.bin'),tokens=str(p/'tokens.txt'),data_dir=str(p/'espeak-ng-data'),lexicon=str(p/'lexicon-zh.txt')+','+str(p/'lexicon-us-en.txt'),lang='zh')
config=sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(kokoro=k,num_threads=2,provider='cpu'),rule_fsts=','.join(str(p/x) for x in ['date-zh.fst','number-zh.fst','phone-zh.fst']),max_num_sentences=1,silence_scale=0.42)
assert config.validate()
tts=sherpa_onnx.OfflineTts(config)
lines=[
 ('开着eBay店，什么事都得自己盯？','开着易贝店，什么事都得自己盯？'),
 ('捷境，是跨境卖家的AI经营工作台。','捷境，是跨境卖家的，人工智能经营工作台。'),
 ('目前先支持eBay。','目前先支持易贝。'),
 ('第一次用，打开官网，登录或注册。','第一次用，打开官网，登录或注册。'),
 ('再按情况选择：免费体验、有店铺，或多店铺。','再按情况选择，免费体验，有店铺，或多店铺。'),
 ('进入工作台，先说清目标。','进入工作台，先说清目标。'),
 ('比如：帮我准备这款咖啡量勺的商品页。','比如，帮我准备这款咖啡量勺的商品页。'),
 ('提供真实图片和参数，让调研、文案和素材有依据。','提供真实图片和参数，让调研，文案和素材，有依据。'),
 ('草稿出来后，核对标题、规格和描述。','草稿出来后，核对标题，规格和描述。'),
 ('完成预检，再由你确认是否发布。','完成预检，再由你确认，是否发布。'),
 ('客服、订单和复盘，也能继续协助。','客服，订单和复盘，也能继续协助。'),
 ('到捷境官网，从一个具体任务开始。','到捷境官网，从一个具体任务开始。'),
]
rate=24000;chunks=[];timeline=[];cursor=0
for idx,(caption,spoken) in enumerate(lines):
 a=tts.generate(spoken,sid=3,speed=1.00);x=np.asarray(a.samples,dtype=np.float64)
 # Trim only near-silent edges, retaining a small natural margin.
 block=240;energy=np.array([np.sqrt(np.mean(x[i:i+block]**2)) for i in range(0,len(x),block)])
 nz=np.where(energy>0.002)[0]
 if len(nz):x=x[max(0,nz[0]*block-1200):min(len(x),(nz[-1]+1)*block+2400)]
 duration=len(x)/rate
 scene=max(2.15,duration+0.55)
 frames=int(np.ceil(scene*30));n=int(frames/30*rate)
 padded=np.zeros(n);start=int(.2*rate);padded[start:start+len(x)]=x
 chunks.append(padded)
 timeline.append({'index':idx,'from_frame':cursor,'duration_frames':frames,'voice_start_frame':cursor+6,'voice_end_frame':cursor+6+int(duration*30),'text':caption,'tts_text':spoken,'audio_seconds':duration,'speaker_id':3})
 cursor+=frames
 print(json.dumps(timeline[-1],ensure_ascii=False),flush=True)
y=np.concatenate(chunks)
peak=float(np.max(np.abs(y)));y=y*(0.68/max(peak,.01))
with wave.open(str(assets/'voice.wav'),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes((np.clip(y,-1,1)*32767).astype('<i2').tobytes())
(out/'voice-timeline.json').write_text(json.dumps({'fps':30,'duration_frames':cursor,'sample_rate':rate,'segments':timeline},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'duration_frames':cursor,'duration_seconds':cursor/30,'voice_sha256':hashlib.sha256((assets/'voice.wav').read_bytes()).hexdigest(),'speaker':'kokoro-v1.1-zh preset zf_001 / sid3','external_api_calls':False},ensure_ascii=False),flush=True)
