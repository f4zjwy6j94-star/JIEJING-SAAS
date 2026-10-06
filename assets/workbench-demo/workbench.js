'use strict';
(() => {
  const one = selector => document.querySelector(selector);
  const all = selector => [...document.querySelectorAll(selector)];
  const state = window.JiejingDemoState.create();
  const images = window.JiejingDemoMedia;
  const routes = ['cockpit','research','listing','media','confirm','support','settings','facts','bulk','preflight'];
  let currentImage = images[0].id;
  let toastTimer;
  let replySaved = false;
  function notify(message) {
    const toast=one('#demoToast');toast.textContent=message;toast.hidden=false;
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>{toast.hidden=true;},4000);
  }
  function toggle(el,visible) {el.hidden=!visible;el.inert=!visible;}
  function chooseListingTab(key,focus=false) {
    all('[data-listing-tab]').forEach(button=>{
      const selected=button.dataset.listingTab===key;
      button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;
      if(selected&&focus)button.focus();
    });
    ['facts','draft','bulk'].forEach(name=>toggle(one('#listing-'+name),name===key));
  }
  function navigate() {
    const raw=location.hash.slice(1);
    const route=routes.includes(raw)?raw:'cockpit';
    const view=['facts','bulk','preflight'].includes(route)?'listing':route==='research'?'cockpit':route;
    all('[data-view]').forEach(section=>toggle(section,section.dataset.view===view));
    all('[data-nav]').forEach(link=>{
      if(link.dataset.nav===view)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    });
    if(view==='listing')chooseListingTab(route==='facts'?'facts':route==='bulk'?'bulk':'draft');
    if(view==='media')showMedia(currentImage);
    if(route==='research'){
      toggle(one('#sampleReport'),true);
      one('#toggleReport').setAttribute('aria-expanded','true');
      one('#toggleReport').textContent='收起调研报告示例';
      one('#sampleReport').scrollIntoView({block:'nearest'});
    }
    renderSummary();
    if(route==='preflight'){
      one('#preflightPanel').open=true;
      one('#preflightPanel').scrollIntoView({block:'nearest'});
    }
    if(raw) one('#workspace').focus({preventScroll:true});
    document.title='捷境 · '+one('[data-view="'+view+'"] h1').textContent+'演示';
  }
  function fillFields() {
    const draft=state.draft;
    ['#factsForm','#listingForm'].forEach(form=>all(form+' [name]').forEach(input=>{
      if(Object.hasOwn(draft,input.name))input.value=draft[input.name];
    }));
  }
  function mediaById(id){return images.find(image=>image.id===id);}
  function renderSummary() {
    const draft=state.draft, saved=state.saved, checks=state.checks();
    one('#titleCount').textContent=draft.title.length+' / 80';
    one('#listingPreviewTitle').textContent=draft.title.trim()||'填写标题后查看预览';
    toggle(one('#unsavedNotice'),state.dirty);
    one('#draftStatus').textContent=state.dirty?'有未保存修改':state.listingSaved?'已保存示例':'示例草稿';
    one('#contextFacts').textContent=checks[0].ok?'演示资料已填写':'待补充';
    one('#contextDraft').textContent=state.listingSaved?'已保存示例':'示例草稿';
    const cover=mediaById(state.cover);
    one('#contextCover').textContent=cover?cover.label:'尚未选用';
    one('#bulkFacts').textContent=checks[0].ok?'已填写示例':'待补充';
    one('#bulkMedia').textContent=cover?'已选封面':'待核对';
    if(cover) window.JiejingDemoImage.apply(one('#listingCover'),cover);
    else {
      one('#listingCover').removeAttribute('srcset');
      one('#listingCover').src='../travel-compression-source.webp';
      one('#listingCover').alt='尚未选择生成图，当前显示商品参考图';
    }
    one('#coverStatus').textContent=cover?'已选用「'+cover.label+'」作为本页示例封面。':'当前为参考图。到素材工坊核对并选用一张生成示例。';
    one('#confirmTitle').textContent=saved.title;
    one('#confirmPrice').textContent=saved.price?'USD '+Number(saved.price).toFixed(2)+'（示例）':'尚未填写';
    ['#preflightList','#reviewList'].forEach(selector=>{
      const list=one(selector);list.replaceChildren();
      checks.forEach(check=>{
        const item=document.createElement('li'),copy=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('p'),link=document.createElement('a');
        title.textContent=check.label;detail.textContent=check.detail;copy.append(title,detail);
        link.href='#'+check.route;link.textContent=check.ok?'已完成演示':'待完善';
        if(check.ok)link.className='is-done';
        item.append(copy,link);list.append(item);
      });
    });
    const missing=checks.filter(check=>!check.ok).length;
    one('#navMissing').textContent=missing?missing+' 项待补':'待确认';
  }
  const switchMediaImage=window.JiejingDemoImage.createSwitcher(one('#mediaImage'),{
    pending(on){
      one('#mediaImage').setAttribute('aria-busy',String(on));
      one('#appearanceReview').disabled=on;one('#rightsReview').disabled=on;one('#platformReview').disabled=on;
      const checked=state.getReview(currentImage);
      one('#useMedia').disabled=on||!(checked.appearance&&checked.rights&&checked.platform);
    },
    error(){one('#mediaFeedback').textContent='图片暂未载入，当前图片和核对状态未更改。请再点一次重试。';},
    commit(image){currentImage=image.id;renderMediaDetails(currentImage);}
  });
  function showMedia(id) {
    const image=mediaById(id);if(image)switchMediaImage(image);
  }
  function renderMediaDetails(id) {
    const image=mediaById(id);if(!image)return;
    one('#mediaLabel').textContent=image.label;one('#mediaNote').textContent=image.note;one('#mediaPrompt').textContent=image.prompt;
    all('[data-media]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.media===id)));
    const checked=state.getReview(id);
    one('#appearanceReview').checked=checked.appearance;one('#rightsReview').checked=checked.rights;one('#platformReview').checked=checked.platform;
    one('#useMedia').disabled=!(checked.appearance&&checked.rights&&checked.platform);
    one('#mediaFeedback').textContent=state.cover===id?'这张图已选为示例封面。':checked.appearance&&checked.rights&&checked.platform?'演示核对已完成，可以选用这张图。':'先完成这张图片的三项演示核对。';
  }
  function arrowNav(buttons,event,index,activate) {
    let next;
    if(['ArrowRight','ArrowDown'].includes(event.key))next=(index+1)%buttons.length;
    if(['ArrowLeft','ArrowUp'].includes(event.key))next=(index+buttons.length-1)%buttons.length;
    if(event.key==='Home')next=0;if(event.key==='End')next=buttons.length-1;
    if(next!==undefined){event.preventDefault();buttons[next].focus();if(activate)buttons[next].click();}
  }
  addEventListener('hashchange',navigate);
  all('a[href="#preflight"]').forEach(link=>{
    link.addEventListener('click',event=>{
      if(location.hash==='#preflight'){event.preventDefault();navigate();}
    });
  });
  all('[data-listing-tab]').forEach((button,i,buttons)=>{
    button.addEventListener('click',()=>{
      const key=button.dataset.listingTab;
      history.replaceState(null,'','#'+(key==='draft'?'listing':key));
      chooseListingTab(key);
    });
    button.addEventListener('keydown',event=>arrowNav(buttons,event,i,true));
  });
  ['#factsForm','#listingForm'].forEach(selector=>{
    const form=one(selector);
    form.addEventListener('input',event=>{
      if(event.target.name){state.edit(event.target.name,event.target.value);renderSummary();}
    });
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const result=state.save(selector==='#factsForm'?'facts':'listing');
      if(!result.ok){notify(result.error);return;}
      fillFields();renderSummary();
      one('#saveFeedback').textContent='已保存在本次演示。刷新页面后会恢复初始示例。';
      notify(selector==='#factsForm'?'示例资料已保存，确认中心已同步。':'示例草稿已保存，确认中心已同步。');
    });
  });
  all('[data-media]').forEach((button,i,buttons)=>{
    button.addEventListener('click',()=>showMedia(button.dataset.media));
    button.addEventListener('keydown',event=>arrowNav(buttons,event,i,false));
  });
  [['#appearanceReview','appearance'],['#rightsReview','rights'],['#platformReview','platform']].forEach(([selector,key])=>{
    one(selector).addEventListener('change',event=>{
      state.review(currentImage,key,event.target.checked);renderMediaDetails(currentImage);renderSummary();
    });
  });
  one('#useMedia').addEventListener('click',()=>{
    if(!state.selectCover(currentImage))return;
    renderMediaDetails(currentImage);renderSummary();notify('已选为示例封面。回到 Listing 可查看效果。');
  });
  one('#toggleReport').addEventListener('click',()=>{
    const open=one('#sampleReport').hidden;toggle(one('#sampleReport'),open);
    one('#toggleReport').setAttribute('aria-expanded',String(open));
    one('#toggleReport').textContent=open?'收起调研报告示例':'查看调研报告示例';
  });
  const responses={
    listing:{text:'示例标题与描述已放在选品与上架。你可以修改并保存；未知的尺寸、材质、重量和库存仍然留空。',href:'#listing',label:'编辑 Listing 草稿'},
    media:{text:'这组预设结果包含整套陈列、行李箱场景、使用过程与材质特写。请逐张核对，再选为示例封面。',href:'#media',label:'到素材工坊查看'},
    confirm:{text:'在选品与上架查看已保存资料的缺项，再到确认中心核对本次操作。本演示不连接 eBay，不会公开发布。',href:'#preflight',label:'查看发布前检查'}
  };
  one('#runSample').addEventListener('click',()=>{
    const selected=responses[one('#sampleTask').value];if(!selected)return;
    const box=one('#sampleResponses');box.replaceChildren();
    const article=document.createElement('article');article.className='chat-answer';
    const heading=document.createElement('h3');heading.textContent='AI CEO · 预设回复';
    const text=document.createElement('p');text.textContent=selected.text;
    const link=document.createElement('a');link.href=selected.href;link.className='text-button';link.textContent=selected.label;
    article.append(heading,text,link);box.append(article);article.scrollIntoView({block:'nearest'});
  });
  one('#loadBatch').addEventListener('click',()=>{toggle(one('#bulkEmpty'),false);toggle(one('#bulkLoaded'),true);});
  one('#prepareReply').addEventListener('click',()=>{
    if(!replySaved&&!one('#supportReply').value)one('#supportReply').value='Thanks for your interest. Please share the internal dimensions of your suitcase. We will compare them with the confirmed packing cube measurements before advising on fit.';
    toggle(one('#replyField'),true);toggle(one('#replyActions'),true);one('#supportReply').focus();
  });
  one('#openConversation').addEventListener('click',()=>{one('#prepareReply').focus();});
  one('#saveReply').addEventListener('click',()=>{
    if(!one('#supportReply').value.trim()){one('#replyFeedback').textContent='回复内容为空，请先填写再保存。';one('#supportReply').focus();return;}
    replySaved=true;one('#replyFeedback').textContent='示例回复已保存；未发送给任何买家。';notify('已保存本页示例回复，未发送。');
  });
  all('[data-settings]').forEach((button,i,buttons)=>{
    button.addEventListener('click',()=>{
      const key=button.dataset.settings;
      buttons.forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
      all('[data-settings-panel]').forEach(panel=>toggle(panel,panel.dataset.settingsPanel===key));
    });
    button.addEventListener('keydown',event=>arrowNav(buttons,event,i,false));
  });
  one('#resetDemo').addEventListener('click',()=>one('#resetDialog').showModal());
  one('#cancelReset').addEventListener('click',()=>one('#resetDialog').close());
  one('#confirmReset').addEventListener('click',()=>{
    state.reset();replySaved=false;fillFields();showMedia(images[0].id);renderSummary();
    one('#sampleResponses').replaceChildren();one('#sampleTask').value='listing';
    toggle(one('#sampleReport'),false);one('#toggleReport').setAttribute('aria-expanded','false');one('#toggleReport').textContent='查看调研报告示例';
    toggle(one('#bulkEmpty'),true);toggle(one('#bulkLoaded'),false);
    toggle(one('#replyField'),false);toggle(one('#replyActions'),false);one('#supportReply').value='';
    one('#replyFeedback').textContent='此演示不会联系任何真实买家。';one('#saveFeedback').textContent='';
    one('[data-settings="account"]').click();chooseListingTab('draft');
    one('#resetDialog').close();location.hash='cockpit';navigate();notify('演示已重置。');
  });
  fillFields();renderMediaDetails(currentImage);navigate();
})();
