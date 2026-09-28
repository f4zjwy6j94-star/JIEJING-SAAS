'use strict';
// Public visual examples only. Authentication and account entry are handled by index.html.
// No model generation, payment or platform writes in this module.
(() => {
  const one = selector => document.querySelector(selector);
  const all = selector => [...document.querySelectorAll(selector)];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const fine = matchMedia('(hover: hover) and (pointer: fine)');
  const storageKey = 'jiejing.homepage.motion';
  let explicitPreference = false;
  let motion = !reduced.matches;
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === 'full' || saved === 'reduced') {
      explicitPreference = true;
      motion = saved === 'full';
    }
  } catch {}
  const toggle = one('#motionToggle');
  const glow = one('#cursorGlow');
  let syncReveals = () => {};
  let pointerFrame = 0, pointerX = 0, pointerY = 0;
  function clearLight() {
    cancelAnimationFrame(pointerFrame);
    pointerFrame = 0;
    glow.classList.remove('is-active');
    glow.dataset.state = 'idle';
  }
  function setMotion(on, persist = false) {
    motion = on;
    if (persist) explicitPreference = true;
    document.body.dataset.motionPreference = explicitPreference ? (on ? 'full' : 'reduced') : 'system';
    document.body.classList.toggle('motion-enabled', on);
    toggle.setAttribute('aria-pressed', String(on));
    toggle.textContent = on ? '动效：开启' : '动效：关闭';
    if (!on) {
      clearLight();
      all('.is-entering,.is-revealing').forEach(node => node.classList.remove('is-entering','is-revealing'));
      all('.scroll-reveal').forEach(node => { node.dataset.revealState = 'done'; });
      all('.image-changing').forEach(node => node.classList.remove('image-changing'));
    }
    if (persist) {
      explicitPreference = true;
      try { localStorage.setItem(storageKey, on ? 'full' : 'reduced'); } catch {}
    }
    syncReveals();
  }
  toggle.addEventListener('click', () => setMotion(!motion, true));
  reduced.addEventListener('change', event => {
    if (!explicitPreference) setMotion(!event.matches);
    syncReveals();
  });
  fine.addEventListener('change', clearLight);
  document.addEventListener('pointermove', event => {
    if (!motion || !fine.matches || event.pointerType === 'touch' || document.hidden) return;
    pointerX = event.clientX; pointerY = event.clientY;
    if (pointerFrame) return;
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      if (!motion || document.hidden || !fine.matches) return;
      glow.style.transform = 'translate3d(' + (pointerX - 190) + 'px,' + (pointerY - 190) + 'px,0)';
      glow.classList.add('is-active');
      glow.dataset.state = 'active';
    });
  }, {passive:true});
  document.documentElement.addEventListener('pointerleave', clearLight);
  document.addEventListener('focusin', clearLight);
  document.addEventListener('keydown', clearLight);
  document.addEventListener('visibilitychange', () => {if (document.hidden) clearLight();});
  window.addEventListener('blur', clearLight);
  setMotion(motion);

  const nodes = all('[data-home-ai-ceo-node]');
  const lines = all('[data-home-ai-ceo-line]');
  let selectedNode = 'market';
  function selectNode(node, announce = false) {
    const key = node.dataset.homeAiCeoNode;
    if (key !== selectedNode) {
      nodes.forEach(item => item.setAttribute('aria-pressed', String(item === node)));
      lines.forEach(line => {
        const selected = line.dataset.homeAiCeoLine === key;
        line.classList.toggle('is-active',selected);
        line.classList.toggle('is-revealing', selected && motion);
      });
      selectedNode = key;
      one('#ceoResultTitle').textContent = node.querySelector('strong').textContent;
      one('#ceoResult').textContent = node.dataset.homeAiCeoResultCopy;
    }
    if (announce) one('#ceoAnnouncement').textContent = node.dataset.homeAiCeoResultCopy;
  }
  function arrowNavigation(buttons, event, index) {
    let next;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index+1)%buttons.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index+buttons.length-1)%buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length-1;
    if (next !== undefined) { event.preventDefault(); buttons[next].focus(); }
  }
  nodes.forEach((node,index) => {
    node.addEventListener('pointerenter', event => {if (event.pointerType !== 'touch') selectNode(node);});
    node.addEventListener('click', () => selectNode(node,true));
    node.addEventListener('focus', () => selectNode(node));
    node.addEventListener('keydown',event=>arrowNavigation(nodes,event,index));
  });
  lines.forEach(line=>line.addEventListener('animationend',()=>line.classList.remove('is-revealing')));

  // Editable illustration only: no account persistence or provider call.
  const previewTitle = one('#previewListingTitle');
  const previewDescription = one('#previewListingDescription');
  const previewStatus = one('#previewListingStatus');
  one('#resetListingPreview').addEventListener('click', () => {
    previewTitle.value = previewTitle.defaultValue;
    previewDescription.value = previewDescription.defaultValue;
    previewStatus.textContent = '已重新填入示例。内容仅用于页面演示，不保存到账号或 eBay。';
  });
  [previewTitle, previewDescription].forEach(field => field.addEventListener('input', () => {
    previewStatus.textContent = '正在编辑示例；不会保存到账号或 eBay。';
  }));

  // Reference-grounded prepared assets. This selection never generates or charges.
  const studioChoices = all('[data-studio-image]');
  const switchStudioImage = window.JiejingDemoImage.createSwitcher(one('#studioImage'), {
    pending(on) { one('#studioImage').setAttribute('aria-busy',String(on)); },
    error() { one('#studioLoadStatus').textContent = '图片暂未载入，已保留当前画面。请再点一次重试。'; },
    commit(image) {
    one('#studioLoadStatus').textContent = '';
    studioChoices.forEach(item => item.setAttribute('aria-pressed',String(item.dataset.studioImage === image.id)));
    one('#studioLabel').textContent = image.label;
    one('#studioPurpose').textContent = image.purpose;
    one('#studioPrompt').textContent = image.prompt;
    one('#studioImageNote').textContent = image.note;
    one('#studioAnnouncement').textContent = '正在查看：' + image.label + '，AI 生成示例。';
    }
  });
  function selectStudioImage(button) {
    const image = window.JiejingDemoMedia.find(item => item.id === button.dataset.studioImage);
    if (image) switchStudioImage(image);
  }
  studioChoices.forEach((button,index) => {
    button.addEventListener('click',()=>selectStudioImage(button));
    button.addEventListener('keydown',event=>arrowNavigation(studioChoices,event,index));
  });

  const steps = all('[data-home-workflow-step]');
  const panels = all('[data-home-workflow-panel]');
  function revealSelectedStep(button, animate = false) {
    const bar=button.parentElement;
    if (bar.scrollWidth <= bar.clientWidth) return;
    const target=button.getBoundingClientRect(), bounds=bar.getBoundingClientRect();
    if (target.left >= bounds.left && target.right <= bounds.left+bar.clientWidth) return;
    const left=bar.scrollLeft+target.left-bounds.left-(bar.clientWidth-target.width)/2;
    bar.scrollTo({left:Math.max(0,left),behavior:animate && motion?'smooth':'instant'});
  }
  function selectStep(key, animate = true) {
    if (!steps.some(button=>button.dataset.homeWorkflowStep===key)) return;
    steps.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.homeWorkflowStep===key)));
    panels.forEach(panel=>{
      const selected=panel.dataset.homeWorkflowPanel===key;
      panel.hidden=!selected;
      panel.inert=!selected;
      panel.classList.toggle('is-entering',selected && animate && motion);
    });
    const button=steps.find(button=>button.dataset.homeWorkflowStep===key);
    revealSelectedStep(button,animate);
    one('[data-home-workflow-live]').textContent='正在查看：'+button.querySelector('strong').textContent;
  }
  steps.forEach((button,index)=>{
    button.setAttribute('aria-controls','workflow-'+button.dataset.homeWorkflowStep);
    button.addEventListener('click',()=>selectStep(button.dataset.homeWorkflowStep));
    button.addEventListener('keydown',event=>arrowNavigation(steps,event,index));
  });
  panels.forEach(panel=>{
    panel.id='workflow-'+panel.dataset.homeWorkflowPanel;
    panel.addEventListener('animationend',()=>panel.classList.remove('is-entering'));
  });
  selectStep(location.hash === '#imageDemo' ? 'media' : 'goal',false);
  let stepResizeFrame=0;
  addEventListener('resize',()=>{
    cancelAnimationFrame(stepResizeFrame);
    stepResizeFrame=requestAnimationFrame(()=>{
      revealSelectedStep(steps.find(button=>button.getAttribute('aria-pressed')==='true'));
    });
  },{passive:true});
  // Reveal before scrolling on both initial load and same-document anchor changes.
  function openMediaAnchor() {
    selectStep('media',false);
    const anchor=one('#imageDemo'), section=anchor.closest('.scroll-reveal');
    if (section) { section.dataset.revealState='done'; section.dataset.revealSeen='true'; }
    requestAnimationFrame(()=>anchor.scrollIntoView({block:'start',behavior:'instant'}));
  }
  if (location.hash === '#imageDemo') openMediaAnchor();
  addEventListener('hashchange',()=>{ if(location.hash === '#imageDemo') openMediaAnchor(); });
  all('[data-home-workflow-jump]').forEach(link=>link.addEventListener('click',event=>{
    event.preventDefault();
    selectStep(link.dataset.homeWorkflowJump);
    one('#workflow').scrollIntoView({behavior:motion?'smooth':'instant',block:'start'});
    steps.find(button=>button.dataset.homeWorkflowStep===link.dataset.homeWorkflowJump).focus({preventScroll:true});
  }));

  // Native scroll timeline handles the small progress indicator; no scroll layout reads.
  addEventListener('scroll',clearLight,{passive:true});
  // Content is visible without JS. Hide only off-screen fragments after setup.
  // One appearance per load, no scroll locking; reduced motion exposes all content.
  if ('IntersectionObserver' in window) {
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
      if (!entry.isIntersecting) return;
      entry.target.dataset.revealState = motion ? 'visible' : 'done';
      entry.target.dataset.revealSeen = 'true';
      observer.unobserve(entry.target);
    }),{threshold:.04,rootMargin:'0px 0px -36px 0px'});
    const revealTargets = all('.jj-home-heading,.home-proof-grid,.home-capability-grid article,.workflow-disclosure,.home-workflow-shell,.home-source-paths,.home-boundary-strip,.home-plan-grid,.home-faq-grid,.home-final-action');
    const staggerItems = all('.home-capability-grid article');
    const initiallyVisible = revealTargets.map(section=>section.getBoundingClientRect().top < innerHeight);
    revealTargets.forEach((section,index)=>{
      section.classList.add('scroll-reveal');
      const order = staggerItems.indexOf(section);
      if (order !== -1) section.style.setProperty('--reveal-delay', (order % 3) * 60 + 'ms');
      section.dataset.revealSeen = String(initiallyVisible[index]);
      section.dataset.revealState = 'done';
      section.addEventListener('animationend',event=>{
        if (event.target === section) section.dataset.revealState = 'done';
      });
    });
    syncReveals = () => {
      const below = revealTargets.map(section=>section.getBoundingClientRect().top >= innerHeight);
      revealTargets.forEach((section,index) => {
      const belowViewport = below[index];
      const pending = motion && section.dataset.revealSeen !== 'true' && belowViewport;
      if (!belowViewport) section.dataset.revealSeen = 'true';
      section.dataset.revealState = pending ? 'pending' : 'done';
      if (pending) observer.observe(section); else observer.unobserve(section);
      });
    };
    syncReveals();
    // Keyboard focus and direct anchors must never land inside invisible content.
    document.addEventListener('focusin',event=>{
      const section=event.target.closest('.scroll-reveal');
      if (section) { section.dataset.revealState='done'; section.dataset.revealSeen='true'; observer.unobserve(section); }
    });
    function revealAnchor() {
      const anchor=document.getElementById(location.hash.slice(1));
      if (!anchor) return;
      [anchor,...anchor.querySelectorAll('.scroll-reveal')].forEach(section=>{
        if (section.dataset.revealState === 'pending') { section.dataset.revealState='done'; section.dataset.revealSeen='true'; observer.unobserve(section); }
      });
    }
    addEventListener('hashchange',revealAnchor);
    revealAnchor();
  }
})();
