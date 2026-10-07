from pathlib import Path
import os
import json,time
import soundfile as sf
from scipy.signal import resample_poly
from faster_whisper import WhisperModel

OUT=Path(os.environ.get('JIEJING_V10_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-ai-commerce-v10'))
path=OUT/'voice-qwen-serena-raw.wav'
assert path.is_file()
start=time.monotonic()
model=WhisperModel('/workspace/toolchains/jiejing-qwen3-voice/asr-small',device='cpu',compute_type='int8',cpu_threads=3,num_workers=1,local_files_only=True)
audio,rate=sf.read(path,dtype='float32');assert rate==24000 and audio.ndim==1
audio=resample_poly(audio,2,3).astype('float32')
segments,info=model.transcribe(audio,language='zh',beam_size=5,word_timestamps=True,condition_on_previous_text=False,initial_prompt='捷境，AI驱动，跨境电商，Listing，商品图片，侵权初筛，易贝。',vad_filter=False)
data=[]
for s in segments:
    data.append({'start':s.start,'end':s.end,'text':s.text,'avg_logprob':s.avg_logprob,'no_speech_prob':s.no_speech_prob,'words':[{'word':w.word,'start':w.start,'end':w.end,'probability':w.probability} for w in (s.words or [])]})
result={'exit_code':0,'engine':'faster-whisper-small','language':info.language,'duration':info.duration,'segments':data,'asr_is_not_human_listening':True,'wall_seconds':time.monotonic()-start}
(OUT/'VOICE_ASR.safe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False),flush=True)
