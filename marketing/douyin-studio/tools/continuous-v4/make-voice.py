"""Generate one complete public-safe paragraph using the already inspected voice client."""
from pathlib import Path
import asyncio
import hashlib
import json
import os
import sys

OUT = Path('/workspace/jiejing-deliverables/11.0/20261007-continuous-v4')
CLIENT = Path('/workspace/jiejing-deliverables/11.0/20261007-narrative-rework-v3/voice-probe')
assert hashlib.sha256((CLIENT / 'edge_tts-7.2.8-py3-none-any.whl').read_bytes()).hexdigest() == '361fe48ce7ef613adbe30f664e3765dd71029c6cb57427279eff8ad6df2eb211'
sys.path.insert(0, str(CLIENT))
import edge_tts  # noqa: E402


async def main():
    text = (OUT / 'narration-spoken.txt').read_text().strip()
    assert '\n' not in text
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    client = edge_tts.Communicate(text, voice='zh-CN-YunxiNeural', rate='+2%', proxy=proxy,
        connect_timeout=10, receive_timeout=30, boundary='WordBoundary')
    # The client's texts property is a generator. Inspecting it would consume the audio input.
    assert len(text.encode('utf-8')) < 1000
    await asyncio.wait_for(client.save(str(OUT / 'voice-raw.mp3'), str(OUT / 'voice-raw.jsonl')), timeout=90)
    assert (OUT / 'voice-raw.mp3').stat().st_size > 1000, 'Voice service produced no usable audio'
    report = {'exit_code': 0, 'voice': 'zh-CN-YunxiNeural', 'rate': '+2%', 'input_paragraphs': 1,
        'ssml_text_chunks': 1, 'per_scene_voice_generation': False, 'synthetic_voice': True,
        'existing_proxy_used': bool(proxy), 'private_data_sent': False, 'paid_account_used': False,
        'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'audio_bytes': (OUT / 'voice-raw.mp3').stat().st_size}
    (OUT / 'VOICE_GENERATION.safe.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
