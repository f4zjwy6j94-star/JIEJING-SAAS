"""Map authored captions to locally measured ASR times; preserve raw recognition differences."""
from pathlib import Path
import os
import difflib
import json
import math
import re

OUT=Path(os.environ.get('JIEJING_V10_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-ai-commerce-v10'))
script=(OUT/'NARRATION.txt').read_text().strip()
raw=json.loads((OUT/'VOICE_ASR.safe.json').read_text())
normalize=lambda s:re.sub(r'[^\u4e00-\u9fffA-Za-z]','',s)
target=normalize(script)
recognized=''
times=[]
for segment in raw['segments']:
    for word in segment['words']:
        chars=normalize(word['word'])
        for i,ch in enumerate(chars):
            recognized+=ch
            width=(word['end']-word['start'])/max(1,len(chars))
            times.append((word['start']+i*width,word['start']+(i+1)*width,word['probability']))
matcher=difflib.SequenceMatcher(a=target,b=recognized,autojunk=False)
aligned=[None]*len(target)
differences=[]
for tag,i,j,a,b in matcher.get_opcodes():
    if tag=='equal':
        for offset in range(j-i):aligned[i+offset]=times[a+offset]
    elif tag=='replace':
        left=times[a][0];right=times[b-1][1]
        for offset in range(j-i):aligned[i+offset]=(left+(right-left)*offset/(j-i),left+(right-left)*(offset+1)/(j-i),0)
    elif tag=='delete':
        left=times[max(0,a-1)][1];right=times[min(a,len(times)-1)][0]
        for offset in range(j-i):aligned[i+offset]=(left+(right-left)*offset/(j-i),left+(right-left)*(offset+1)/(j-i),0)
    if tag!='equal':differences.append({'tag':tag,'script':target[i:j],'asr':recognized[a:b],'script_indices':[i,j],'asr_indices':[a,b],'review':'Caption uses authored wording; homophone/recognizer differences retained, not claimed as exact human audio verification.'})
assert all(x is not None for x in aligned)
chunks=[]
for part in re.split(r'[，。？！；：、]',script):
    if not part:continue
    while len(part)>21:
        chunks.append(part[:18]);part=part[18:]
    if part:chunks.append(part)
captions=[];offset=0
for text in chunks:
    n=len(normalize(text));a=aligned[offset][0]+.3;b=aligned[offset+n-1][1]+.3
    assert b>=a
    captions.append({'start':round(a,3),'end':round(b,3),'text':text.replace('易贝','eBay')})
    offset+=n
assert offset==len(target)
for i,c in enumerate(captions):
    next_start=captions[i+1]['start'] if i+1<len(captions) else raw['duration']+.3
    c['end']=round(min(max(c['end'],c['start']+.3)+.08,next_start),3)
    assert c['end']>c['start'],c
starts=[0,7.45,11.40,14.18,25.18,30.08,37.92,43.02,47.74,53.24,60.90,72.42,77.1]
labels=['分工','捷境是什么','两种起点','无货源：调研','确认货源','有货源：提交资料','AI商品内容','图片和视频','站内修改','侵权风险初筛','确认后发布','AI执行与商家决策','开始使用']
duration=math.ceil((raw['duration']+.3+1.38)*30)/30
scenes=[{'id':f's{i+1}','label':label,'start':start,'end':starts[i+1] if i+1<len(starts) else duration} for i,(label,start) in enumerate(zip(labels,starts))]
result={'source':'measured_local_voice_asr_with_disclosed_text_alignment','duration':duration,'voice_lead_seconds':.3,'captions':captions,'scenes':scenes}
(OUT/'TIMING.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
review={'exit_code':0,'asr_raw_preserved':True,'script_characters_normalized':len(target),'asr_characters_normalized':len(recognized),'text_similarity':matcher.ratio(),'differences':differences,'exact_audio_semantic_match_claimed':False,'manual_timeline_anchors_based_on_measured_segments':True,'caption_script_identity':True}
(OUT/'ASR_ALIGNMENT_REVIEW.safe.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'exit_code':0,'duration':duration,'captions':len(captions),'differences':differences,'scenes':scenes},ensure_ascii=False))
