from pathlib import Path
import time,json,hashlib,os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel

ROOT=Path('/workspace/toolchains/jiejing-qwen3-voice/model')
OUT=Path(os.environ.get('JIEJING_V9_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-product-rework-v9'))
torch.set_num_threads(3)
torch.set_num_interop_threads(1)
torch.manual_seed(20261009)
assert not (OUT/'voice-qwen-serena-raw.wav').exists(), 'Preserve existing voice output'
start=time.monotonic()
print('LOADING_CPU_MODEL',flush=True)
model=Qwen3TTSModel.from_pretrained(str(ROOT),device_map='cpu',dtype=torch.float32,attn_implementation='sdpa',local_files_only=True)
speakers=model.get_supported_speakers();assert 'serena' in [s.lower() for s in speakers]
print(json.dumps({'model_loaded_seconds':time.monotonic()-start,'speaker':'Serena','device':'cpu','dtype':'float32'}),flush=True)
text=(OUT/'NARRATION.txt').read_text().strip()
with torch.inference_mode():
    wavs,sr=model.generate_custom_voice(text=text,language='Chinese',speaker='Serena',do_sample=True,temperature=.8,top_p=.95,max_new_tokens=1000)
assert len(wavs)==1 and len(wavs[0])>sr
target=OUT/'voice-qwen-serena-raw.wav';sf.write(target,wavs[0],sr,subtype='PCM_16')
receipt={'exit_code':0,'model':'Qwen3-TTS-12Hz-0.6B-CustomVoice','revision':'85e237c12c027371202489a0ec509ded67b5e4b5','speaker':'Serena','sample_rate':sr,'seconds':len(wavs[0])/sr,'generation_wall_seconds':time.monotonic()-start,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'synthetic':True,'reference_audio_used':False,'selected_CosyVoice_demo_cloned':False,'network_generation':False,'paid_API':False,'full_paragraph_in_one_generation':True,'owner_acceptance':False,'status':'New plain-language paragraph, existing free preset; human-like naturalness not certified'}
(OUT/'QWEN_LOCAL_GENERATION.safe.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
