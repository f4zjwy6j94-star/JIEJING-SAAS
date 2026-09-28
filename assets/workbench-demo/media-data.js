'use strict';
// Prepared marketing examples, never a live merchant generation record.
window.JiejingDemoMedia = Object.freeze([
  {
    "id": "collection",
    "label": "整套陈列",
    "alt": "六件鼠尾草绿、灰米色与炭灰收纳袋重新排布的生成示例",
    "prompt": "把这套收纳袋重新排成有层次的整套陈列，保留六件组合、配色和外观。",
    "purpose": "看清组合与配色",
    "note": "整套商品示例",
    "src": "../packing-collection-v5.png"
  },
  {
    "id": "suitcase",
    "label": "行李箱场景",
    "alt": "俯拍银色行李箱，部分收纳袋装入箱内、其余置于旁侧的生成示例",
    "prompt": "从上方拍摄装箱场景，一部分收纳袋放进旅行箱，其余在旁边展开。",
    "purpose": "呈现旅行收纳用途",
    "note": "场景道具不代表随商品附送",
    "src": "../packing-suitcase-v5.png"
  },
  {
    "id": "packing",
    "label": "使用过程",
    "alt": "双手将衣物放入绿色收纳袋的近景生成示例",
    "prompt": "做一张手部收纳的近景：把折好的衣物放进绿色收纳袋，画面自然、干净。",
    "purpose": "展示单件使用方式",
    "note": "单件局部与使用场景示例",
    "src": "../packing-packing-v5.png"
  },
  {
    "id": "detail",
    "label": "材质特写",
    "alt": "炭灰色收纳袋的网布、织物与拉链微距生成示例",
    "prompt": "聚焦炭灰色收纳袋的拉链、织物与网布细节，不增加标志或新功能。",
    "purpose": "让买家看见局部细节",
    "note": "生成细节仍需与实物逐一核对",
    "src": "../packing-detail-v5.png"
  }
].map(item => Object.freeze({
  ...item,
  displaySrc: `../packing-${item.id}-v6-1448.webp`,
  thumbSrc: `../packing-${item.id}-v6-360.webp`,
  srcset: [360,720,1080,1448].map(width => `../packing-${item.id}-v6-${width}.webp ${width}w`).join(', ')
})));

// Decode off-screen first; rapid choices cannot commit an older image or caption.
window.JiejingDemoImage = Object.freeze({
  apply(element, item) {
    element.srcset = item.srcset;
    element.src = item.displaySrc;
    element.alt = item.alt;
  },
  createSwitcher(element, callbacks = {}, ImageClass = Image) {
    let revision = 0;
    return async item => {
      const request = ++revision;
      callbacks.pending?.(true);
      const next = new ImageClass();
      next.decoding = 'async';
      next.sizes = element.sizes || '100vw';
      next.srcset = item.srcset;
      next.src = item.displaySrc;
      try {
        await next.decode();
        if (request !== revision) return false;
        window.JiejingDemoImage.apply(element, item);
        callbacks.commit?.(item);
        return true;
      } catch {
        if (request === revision) callbacks.error?.();
        return false;
      } finally {
        if (request === revision) callbacks.pending?.(false);
      }
    };
  }
});
