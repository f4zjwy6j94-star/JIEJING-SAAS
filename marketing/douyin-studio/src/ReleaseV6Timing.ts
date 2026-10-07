import type {Caption} from '@remotion/captions';

export const releaseTiming = {
  durationInFrames: 750,
  fps: 30,
  beats: {brand: 100, use: 213, confirm: 432, end: 543},
  captions: [
    {text: '有了商品，上架怎么还这么累？', startMs: 0, endMs: 3300, timestampMs: null, confidence: null},
    {text: '捷境，是你的跨境电商 AI CEO。', startMs: 3380, endMs: 7100, timestampMs: null, confidence: null},
    {text: '用中文说目标，', startMs: 7200, endMs: 8480, timestampMs: null, confidence: null},
    {text: '给真实图片和参数，', startMs: 8480, endMs: 10600, timestampMs: null, confidence: null},
    {text: '它协助调研，', startMs: 10660, endMs: 12000, timestampMs: null, confidence: null},
    {text: '准备商品页和素材。', startMs: 12000, endMs: 14350, timestampMs: null, confidence: null},
    {text: '你核对，预检通过，再确认发布。', startMs: 14500, endMs: 18050, timestampMs: null, confidence: null},
    {text: '现在先支持 eBay。', startMs: 18180, endMs: 20900, timestampMs: null, confidence: null},
    {text: '先从手头的一件商品，试起来。', startMs: 20960, endMs: 24400, timestampMs: null, confidence: null},
  ] satisfies Caption[],
};
