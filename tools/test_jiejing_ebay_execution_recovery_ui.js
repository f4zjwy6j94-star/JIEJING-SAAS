"use strict";
const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createHash}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
function extract(name) {
  const start=source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert(start>=0,`${name} exists`);
  const tail=source.slice(start), end=tail.search(/\n(?:async )?function /);
  return end<0?tail:tail.slice(0,end);
}
function fixture(status=401, payload={error:'session_access_revoked'}) {
  const calls=[], c={calls,refreshes:0,terminated:0,saasAccountSessionEpoch:1,
    state:{saasApiBase:'http://127.0.0.1:1',saasManualLogout:false},
    assertSaasAccountSessionCurrent:()=>{},recordSaasServerClock:()=>{},shouldAttachSaasBearerToken:()=>false,
    isSaasPublicMvpMode:()=>true,publicRuntimeText:value=>String(value),saasModelBlockedReasonText:value=>String(value),
    handleSaasUnrecoverableSession:()=>{c.terminated++},
    refreshSaasBrowserSession:async()=>{c.refreshes++;return true},
    fetch:async(url,options)=>{calls.push({url,method:options.method||'GET'});
      const code=c.refreshes?200:status;
      return {status:code,ok:code===200,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify(payload),json:async()=>({ok:true})};},
  };
  vm.createContext(c);
  vm.runInContext(['saasFetch','saasRequestCanRetryAfterSessionRefresh','saasBackendErrorMessage'].map(extract).join('\n'),c);
  return c;
}
test('exact execute POST401 never refreshes or replays',async()=>{
  const c=fixture();
  await assert.rejects(c.saasFetch('/confirmations/exact-old/execute',{method:'POST',body:'{}'}),error=>error.status===401);
  assert.equal(c.calls.length,1);assert.equal(c.refreshes,0);assert.equal(c.terminated,1);
  assert.equal(c.calls[0].method,'POST');
});
test('existing safe GET401 normal refresh control remains intact',async()=>{
  const c=fixture();await c.saasFetch('/confirmations');
  assert.equal(c.calls.length,2);assert.equal(c.refreshes,1);assert.equal(c.terminated,0);
});
for(const status of [403,409]) test(`JSON${status} shows safe Chinese zero-write next step`,async()=>{
  const c=fixture(status,{error:'execution_request_authority_changed',execution_recovery:{status:'execution_authority_blocked',
    zero_write_proven:true,next_action:'prepare_reapproval',automatic_retry_allowed:false,secret_exposed:false}});
  await assert.rejects(c.saasFetch('/confirmations/exact-old/execute',{method:'POST'}),error=>
    error.message.includes('未发送')&&error.message.includes('重新准备')&&!error.message.includes('execution_request_authority_changed'));
  assert.equal(c.calls.length,1);assert.equal(c.refreshes,0);
});

function recoveryFixture() {
  const c=fixture(200);
  c.store={store_id:'store-A'};
  c.state.saasCompany={company_id:'company-A'};
  c.state.saasIdentity={company_id:'company-A',user_id:'merchant-A'}; // Submitted-outcome scope host only.
  c.state.saasListingComposerDraft={model_generated:true};
  c.state.saasConfirmations=[{company_id:'company-A',store_id:'store-A',confirmation_id:'old',status:'needs_revision',action_type:'publish_listing',
    item:{listing_project_identity:{key:'project-A'},publish_payload:{listing:{sku:'SKU-A'}}},
    execution_recovery:{company_id:'company-A',store_id:'store-A',confirmation_id:'old',action_type:'publish_listing',
      status:'execution_authority_blocked',zero_write_proven:true,next_action:'prepare_reapproval',automatic_retry_allowed:false,secret_exposed:false}}];
  c.actions=[];c.toasts=[];
  Object.assign(c, {activeSaasStore:()=>c.store,escapeHtml:value=>String(value),requireSaasProtectedSessionForAction:()=>true,
    saasListingDraftAuthoritativeSku:()=> 'SKU-A',saasCurrentListingProjectIdentity:()=>({key:'project-A'}),
    saasRecentProductWorkflowTasks:()=>[],setView:view=>c.actions.push(['view',view]),renderSaasBackendPanel:()=>{},renderSaasConfirmPanel:()=>{},renderConnect:()=>{},
    showActionToast:text=>c.toasts.push(text),refreshSaasState:async()=>{},
    readSaasPublishIntakeForm:()=>({listing:{sku:'SKU-A',title:'Current product',category_id:'123',price:{value:'20'}},listing_project_identity:{key:'project-A'}}),
    window:{setTimeout:()=>{}},document:{querySelector:()=>null},
    recoverSaasPublishState:async id=>{c.actions.push(['readonly',id]);return true},
    reconcileSaasInventoryLocation:async id=>{c.actions.push(['readonly-location',id]);return true},
  });
  vm.runInContext(['saasEbayRecoveryCard','saasEbayRecoveryContext','saasEbayStoreRequestGuard','syncSaasSettingsOwnedLoadingControls','isSaasEbayRecoveryContextCurrent',
    'saasReviseConfirmationAttemptKey','saasReviseConfirmationButtonLabel','saasReviseConfirmationBlocksApproval', // Exact real revise-attempt dependencies only; all original assertions unchanged.
    'saasEbaySubmittedOutcome','rememberSaasEbaySubmittedOutcome','resolveSaasEbaySubmittedOutcomes','renderSaasEbaySubmittedOutcome','checkSaasEbaySubmittedOutcome', // Submitted-outcome dependencies only.
    'rememberSaasEbayExecutionRecovery','renderSaasEbayExecutionRecovery','saasEbayReapprovalId','handleSaasEbayExecutionRecovery',
    'createSaasPublishConfirmationFromIntakeForm'].map(extract).join('\n'),c);
  return c;
}
test('zero-write recovery returns exact product and prepares only a linked pending',async()=>{
  const c=recoveryFixture();
  c.fetch=async(url,options)=>{c.calls.push({url,method:options.method,body:JSON.parse(options.body)});
    return {ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({confirmation:{company_id:'company-A',store_id:'store-A',
      confirmation_id:'new-pending',action_type:'publish_listing',status:'pending',item:{replaces_confirmation_id:'old'}}})};};
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','prepare'),true);
  assert.equal(c.calls.length,0);
  assert.equal(await c.createSaasPublishConfirmationFromIntakeForm(),true);
  assert.equal(c.calls.length,1);assert.match(c.calls[0].url,/\/stores\/store-A\/publish-confirmation$/);
  assert.equal(c.calls[0].body.replaces_confirmation_id,'old');
  assert.equal(c.state.saasConfirmations[0].status,'pending');
  assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});
test('partial unknown offers only exact read-only reconciliation',async()=>{
  const c=recoveryFixture(),card=c.state.saasConfirmations[0];
  Object.assign(card.execution_recovery,{status:'execution_reconciliation_required',zero_write_proven:false,next_action:'reconcile_read_only'});
  const html=c.renderSaasEbayExecutionRecovery(card);
  assert.match(html,/只读核对/);assert.doesNotMatch(html,/reprepare-ebay-execution|approve-confirmation|\/execute/);
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','prepare'),false);
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','reconcile'),true);
  assert.deepEqual(c.actions,[['readonly','old']]);assert.equal(c.calls.length,0);
});
test('expired never-admitted request offers explicit retirement, not an already-cancelled claim',()=>{
  const c=recoveryFixture(),card=c.state.saasConfirmations[0];
  card.status='external_execution_processing_manual_reconcile';
  card.execution_recovery.status='execution_prewrite_recovery_available';
  const html=c.renderSaasEbayExecutionRecovery(card);
  assert.match(html,/重新准备时将取消旧请求/);assert.match(html,/仍需单独确认/);
  assert.doesNotMatch(html,/旧确认单不会再次执行/);assert.equal(c.calls.length,0);
});
test('store switch rejects old recovery action and late summary',async()=>{
  const c=recoveryFixture(),card=c.state.saasConfirmations[0],context=c.saasEbayRecoveryContext(card);
  c.store={store_id:'store-B'};
  assert.equal(c.rememberSaasEbayExecutionRecovery(card.execution_recovery,context),false);
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','prepare'),false);
  assert.equal(c.renderSaasEbayExecutionRecovery(card),'');assert.equal(c.calls.length,0);assert.equal(c.actions.length,0);
});
test('account epoch change rejects cached recovery action context',()=>{
  const c=recoveryFixture(),card=c.state.saasConfirmations[0],context=c.saasEbayRecoveryContext(card);
  c.saasAccountSessionEpoch++;
  assert.equal(c.rememberSaasEbayExecutionRecovery(card.execution_recovery,context),false);
});
test('re-preparation refuses changed SKU before any request',async()=>{
  const c=recoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  c.readSaasPublishIntakeForm=()=>({listing:{sku:'OTHER',title:'Other',category_id:'123',price:{value:'20'}},listing_project_identity:{key:'project-A'}});
  assert.equal(await c.createSaasPublishConfirmationFromIntakeForm(),false);assert.equal(c.calls.length,0);
});
test('completed receipt has no reapproval or reconciliation action',()=>{
  const c=recoveryFixture(),card=c.state.saasConfirmations[0];
  Object.assign(card.execution_recovery,{status:'execution_completed',zero_write_proven:false,next_action:'view_receipt'});
  const html=c.renderSaasEbayExecutionRecovery(card);
  assert.match(html,/已完成/);assert.doesNotMatch(html,/data-saas-action/);
});
test('linked replacement opens only the exact same-store new record',async()=>{
  const c=recoveryFixture(),old=c.state.saasConfirmations[0];
  Object.assign(old.execution_recovery,{next_action:'view_replacement',replacement_confirmation_id:'new'});
  c.state.saasConfirmations.push({company_id:'company-A',store_id:'store-A',confirmation_id:'new',status:'pending',item:{replaces_confirmation_id:'old'}});
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','replacement'),true);assert.equal(c.calls.length,0);
  c.state.saasConfirmations[1].store_id='store-B';
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','replacement'),false);
});
test('delayed preparation response after store switch cannot apply old state',async()=>{
  const c=recoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  let release; c.fetch=async()=>new Promise(resolve=>{release=()=>resolve({ok:true,status:201,headers:{get:()=> 'application/json'},
    json:async()=>({confirmation:{confirmation_id:'late-old',status:'pending'}})});});
  const pending=c.createSaasPublishConfirmationFromIntakeForm();
  assert.equal(typeof release,'function');c.store={store_id:'store-B'};c.state.saasError='';c.actions=[];
  release();assert.equal(await pending,false);
  assert.equal(c.state.saasError,'');assert.equal(c.actions.length,0);
  assert(!c.state.saasConfirmations.some(card=>card.confirmation_id==='late-old'));
});

for(const transition of ['store','account']) for(const entry of ['prepare','cleanup','readonly'])
test(`delayed ${entry} response after ${transition} change preserves new context`,async()=>{
  const c=recoveryFixture();
  vm.runInContext(['createSaasTestListingCleanupPlan','recoverSaasPublishState'].map(extract).join('\n'),c);
  let release;
  c.fetch=async(url,options)=>{c.calls.push({url,method:options.method});return new Promise(resolve=>{
    release=()=>resolve({ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({created:true,
      confirmation:{confirmation_id:'late-pending',status:'pending'},cleanup_confirmation:{confirmation_id:'late-cleanup',status:'pending'},
      publish_recovery:{status:'late-recovery'}})});
  });};
  const pending=entry==='prepare'?c.createSaasPublishConfirmationFromIntakeForm():
    entry==='cleanup'?c.createSaasTestListingCleanupPlan('old'):c.recoverSaasPublishState('old');
  assert.equal(typeof release,'function');assert.equal(c.calls.length,1);
  if(transition==='store') c.store={store_id:'store-B'}; else c.saasAccountSessionEpoch++;
  c.state.saasError='new-context-error';c.state.saasLoading=true;c.toasts=[];c.actions=[];
  let renders=0;c.renderSaasBackendPanel=()=>{renders++};
  release();await pending;
  assert.equal(c.state.saasError,'new-context-error');assert.equal(c.state.saasLoading,true);
  assert.equal(renders,0);assert.equal(c.toasts.length,0);assert.equal(c.actions.length,0);
  assert.equal(c.state.saasLastPublishRecovery,undefined);
  assert(!c.state.saasConfirmations.some(card=>/^late-/.test(card.confirmation_id)));
});

for(const transition of ['store','account']) test(`cleanup refresh completing after ${transition} change is silent`,async()=>{
  const c=recoveryFixture();vm.runInContext(extract('createSaasTestListingCleanupPlan'),c);
  c.fetch=async()=>({ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({created:true})});
  let release;const atRefresh=new Promise(resolve=>{
    c.refreshSaasState=()=>new Promise(done=>{release=done;resolve()});
  });
  const pending=c.createSaasTestListingCleanupPlan('old');await atRefresh;
  if(transition==='store') c.store={store_id:'store-B'};else c.saasAccountSessionEpoch++;
  c.toasts=[];c.state.saasLoading=true;let renders=0;c.renderSaasBackendPanel=()=>{renders++};
  release();await pending;assert.equal(c.toasts.length,0);assert.equal(c.state.saasLoading,true);assert.equal(renders,0);
});

test('cleanup normal same-context preparation still exposes a pending confirmation',async()=>{
  const c=recoveryFixture();vm.runInContext(extract('createSaasTestListingCleanupPlan'),c);
  c.fetch=async(url,options)=>{c.calls.push({url,method:options.method});return {ok:true,status:201,
    headers:{get:()=> 'application/json'},json:async()=>({created:true,cleanup_confirmation:{confirmation_id:'cleanup-pending',status:'pending'}})};};
  await c.createSaasTestListingCleanupPlan('old');
  assert.equal(c.calls.length,1);assert.match(c.calls[0].url,/\/confirmations\/old\/publish-cleanup-plan$/);
  assert.equal(c.state.saasConfirmations[0].status,'pending');assert.equal(c.state.saasLoading,false);
  assert(c.toasts.some(message=>message.includes('清理确认单')));
});

function switchAwayAndBack(c) {
  const cards=JSON.parse(JSON.stringify(c.state.saasConfirmations));
  const draft=c.state.saasListingComposerDraft;
  for(const name of ['invalidateSaasSettingsActionContext','stopSaasAiCeoCrossDeviceSync',
    'stopSaasPendingNewListingProjectReconciliation','setSaasAiCeoTaskContextState','resetSaasProductFeedbackViewState',
    'resetSaasListingProjectTransientState','syncSaasProjectRoute']) c[name]=()=>{};
  vm.runInContext(extract('resetSaasActiveProjectForStoreSwitch'),c);
  c.store={store_id:'store-B'};c.resetSaasActiveProjectForStoreSwitch();
  c.store={store_id:'store-A'};c.resetSaasActiveProjectForStoreSwitch();
  c.state.saasConfirmations=cards;c.state.saasListingComposerDraft=draft;
}

for(const outcome of ['success','error']) for(const entry of ['prepare','cleanup','readonly'])
test(`A-B-A discards late ${entry} ${outcome} without navigation or duplicate execute`,async()=>{
  const c=recoveryFixture();
  vm.runInContext(['createSaasTestListingCleanupPlan','recoverSaasPublishState'].map(extract).join('\n'),c);
  let release;c.fetch=async(url,options)=>{c.calls.push({url,method:options.method});return new Promise(resolve=>{
    release=()=>resolve({ok:outcome==='success',status:outcome==='success'?201:409,headers:{get:()=> 'application/json'},
      text:async()=>JSON.stringify({error:'late-old-error'}),json:async()=>({created:true,
        confirmation:{confirmation_id:'late-ABA',status:'pending'},cleanup_confirmation:{confirmation_id:'late-ABA',status:'pending'},
        publish_recovery:{status:'late-ABA'}})});
  });};
  const pending=entry==='prepare'?c.createSaasPublishConfirmationFromIntakeForm():
    entry==='cleanup'?c.createSaasTestListingCleanupPlan('old'):c.recoverSaasPublishState('old');
  assert.equal(typeof release,'function');switchAwayAndBack(c);
  c.state.saasError='current-A';c.state.saasLoading=true;c.toasts=[];c.actions=[];
  let renders=0;c.renderSaasBackendPanel=()=>{renders++};
  release();await pending;
  assert.equal(c.state.saasError,'current-A');assert.equal(c.state.saasLoading,true);
  assert.equal(renders,0);assert.equal(c.toasts.length,0);assert.equal(c.actions.length,0);
  assert.equal(c.state.saasLastPublishRecovery,undefined);
  assert(!c.state.saasConfirmations.some(card=>card.confirmation_id==='late-ABA'));
  assert.equal(c.calls.length,1);assert(!c.calls.some(call=>/\/execute$/.test(call.url)));
});

test('A-B-A invalidates old reapproval context even after exact old card reload',async()=>{
  const c=recoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  const oldContext=c.state.saasEbayReapprovalContext,summary=c.state.saasConfirmations[0].execution_recovery;
  switchAwayAndBack(c);
  assert.equal(c.state.saasEbayReapprovalContext,null);
  assert.equal(c.rememberSaasEbayExecutionRecovery(summary,oldContext),false);
  assert.equal(c.saasEbayReapprovalId('publish_listing',{listing:{sku:'SKU-A'},listing_project_identity:{key:'project-A'}}),'');
  assert.equal(c.calls.length,0);
});

test('A-B-A during cleanup refresh cannot revive old toast or loading state',async()=>{
  const c=recoveryFixture();vm.runInContext(extract('createSaasTestListingCleanupPlan'),c);
  c.fetch=async()=>({ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({created:true})});
  let release;const atRefresh=new Promise(resolve=>{c.refreshSaasState=()=>new Promise(done=>{release=done;resolve()});});
  const pending=c.createSaasTestListingCleanupPlan('old');await atRefresh;switchAwayAndBack(c);
  c.toasts=[];c.actions=[];c.state.saasLoading=true;let renders=0;c.renderSaasBackendPanel=()=>{renders++};
  release();await pending;
  assert.equal(c.toasts.length,0);assert.equal(c.actions.length,0);assert.equal(c.state.saasLoading,true);assert.equal(renders,0);
});

function inventoryRecoveryFixture() {
  const c=recoveryFixture();c.store.platform='ebay';c.created=[];
  const old=c.state.saasConfirmations[0];c.oldInventory=old;
  old.action_type='create_ebay_inventory_location';old.item={merchant_location_key:'warehouse-a'};
  old.execution_recovery.action_type=old.action_type;
  c.input={merchant_location_key:'warehouse-a',name:'Warehouse A',location_types:['WAREHOUSE'],
    address:{city:'Austin',state_or_province:'TX',country:'US'}};
  Object.assign(c,{saasPendingPublishIntakeFormValues:null,saasVerifiedInventoryLocationConfirmations:new WeakSet(),
    readSaasInventoryLocationInput:()=>JSON.parse(JSON.stringify(c.input)),snapshotSaasPublishIntakeFormValues:()=>({}),
    saasSha256Hex:async value=>createHash('sha256').update(value).digest('hex')});
  vm.runInContext(['saasCanonicalJsonValue','verifySaasInventoryLocationConfirmations',
    'isSaasInventoryLocationSensitiveConfirmation','isSaasExactInventoryLocationConfirmation',
    'isSaasUniqueCurrentInventoryLocationConfirmation','createSaasInventoryLocationConfirmation'].map(extract).join('\n'),c);
  c.fetch=async(url,options)=>{
    const body=JSON.parse(options.body);c.calls.push({url,method:options.method,body});
    const id=`location-pending-${c.calls.length}`;
    const location={merchantLocationKey:body.merchant_location_key,name:body.name,locationTypes:body.location_types,
      location:{address:{city:body.address.city,stateOrProvince:body.address.state_or_province,country:body.address.country}}};
    const item={company_id:'company-A',store_id:'store-A',merchant_location_key:body.merchant_location_key,
      source:'merchant_ebay_inventory_location_setup',requested_step:'inventory_location_confirmation_gate',
      country:body.address.country,location_payload:location,
      location_payload_sha256:await c.saasSha256Hex(JSON.stringify(c.saasCanonicalJsonValue(location))),
      high_risk:true,writes_to_ebay_after_approval:true,public_publish_enabled:false,public_listing_created:false,secret_exposed:false};
    if(body.replaces_confirmation_id) item.replaces_confirmation_id=body.replaces_confirmation_id;
    c.created.push({company_id:'company-A',store_id:'store-A',confirmation_id:id,status:'pending',
      action_type:'create_ebay_inventory_location',runtime_run_id:'merchant_ebay_inventory_location_setup',item});
    return {ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({inventory_location_confirmation:{
      company_id:'company-A',store_id:'store-A',confirmation_id:id,status:'pending',action_type:'create_ebay_inventory_location',
      source:item.source,requested_step:item.requested_step,merchant_location_key:body.merchant_location_key,
      country:body.address.country,location_write_started:false,public_listing_created:false,secret_exposed:false}})};
  };
  c.refreshSaasState=async()=>{
    const replacement=c.created.find(card=>card.item.replaces_confirmation_id===old.confirmation_id);
    if(replacement) Object.assign(old.execution_recovery,{next_action:'view_replacement',replacement_confirmation_id:replacement.confirmation_id});
    c.state.saasConfirmations=[old,...c.created];
    c.saasVerifiedInventoryLocationConfirmations=await c.verifySaasInventoryLocationConfirmations(c.state.saasConfirmations);
  };
  return c;
}

test('inventory replacement success releases context for later ordinary same-store preparation',async()=>{
  const c=inventoryRecoveryFixture();
  assert.equal(await c.handleSaasEbayExecutionRecovery('old','prepare'),true);assert.equal(c.calls.length,0);
  assert.equal(await c.createSaasInventoryLocationConfirmation(),true);
  assert.equal(c.calls.length,1);assert.equal(c.calls[0].body.replaces_confirmation_id,'old');
  assert.equal(c.oldInventory.execution_recovery.next_action,'view_replacement');
  assert.equal(c.created[0].status,'pending');
  // Simulate the later server projection of that independently completed new card.
  // This UI test itself must never emit approval or execution requests.
  c.created[0].status='executed';c.input.merchant_location_key='warehouse-b';c.input.name='Warehouse B';
  assert.equal(await c.createSaasInventoryLocationConfirmation(),true,'ordinary preparation must not reuse the old recovery context');
  assert.equal(c.state.saasEbayReapprovalContext,null);assert.equal(c.calls.length,2);
  assert.equal(c.calls[1].body.replaces_confirmation_id,undefined);
  assert.equal(c.calls[1].body.merchant_location_key,'warehouse-b');
  assert(c.calls.every(call=>call.method==='POST'&&/\/ebay-inventory-location\/confirmation$/.test(call.url)));
  assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});

test('ordinary inventory preparation without recovery context still creates one verified pending',async()=>{
  const c=inventoryRecoveryFixture();
  assert.equal(await c.createSaasInventoryLocationConfirmation(),true);
  assert.equal(c.calls.length,1);assert.equal(c.calls[0].body.replaces_confirmation_id,undefined);
  assert.equal(c.created[0].status,'pending');assert.equal(c.state.saasLoading,false);
  assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});

test('failed inventory preparation retains its usable exact recovery context',async()=>{
  const c=inventoryRecoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  const context=c.state.saasEbayReapprovalContext;
  c.fetch=async(url,options)=>{c.calls.push({url,method:options.method,body:JSON.parse(options.body)});
    return {ok:false,status:409,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'prepare_failed'})};};
  assert.equal(await c.createSaasInventoryLocationConfirmation(),false);
  assert.equal(c.state.saasEbayReapprovalContext,context);assert.equal(c.calls.length,1);
  assert.equal(c.saasEbayReapprovalId('create_ebay_inventory_location',c.input),'old');
  assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});

test('inventory recovery refuses a different location before sending',async()=>{
  const c=inventoryRecoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  const context=c.state.saasEbayReapprovalContext;c.input.merchant_location_key='other-warehouse';
  assert.equal(await c.createSaasInventoryLocationConfirmation(),false);
  assert.equal(c.calls.length,0);assert.equal(c.state.saasEbayReapprovalContext,context);
});

for(const transition of ['account','store','ABA']) for(const outcome of ['success','error'])
test(`late inventory ${outcome} after ${transition} preserves a newer recovery context`,async()=>{
  const c=inventoryRecoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  const send=c.fetch;let release;
  const atResponse=new Promise(ready=>{c.fetch=async(...args)=>{
    const response=await send(...args);
    return new Promise(resolve=>{release=()=>resolve(outcome==='success'?response:{ok:false,status:409,
      headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'late_old_error'})});ready();});
  };});
  const pending=c.createSaasInventoryLocationConfirmation();await atResponse;
  if(transition==='account') c.saasAccountSessionEpoch++;
  else if(transition==='store') c.store={store_id:'store-B',platform:'ebay'};
  else {switchAwayAndBack(c);c.store.platform='ebay';}
  const newer={...c.oldInventory,confirmation_id:'newer-recovery',store_id:c.store.store_id,
    item:{merchant_location_key:'newer-warehouse'}};
  c.state.saasConfirmations=[newer];const context=c.saasEbayRecoveryContext(newer);
  c.state.saasEbayReapprovalContext=context;c.state.saasError='new-context';c.state.saasLoading=true;
  c.actions=[];c.toasts=[];let renders=0;c.renderSaasBackendPanel=()=>{renders++};
  release();assert.equal(await pending,false);
  assert.equal(c.state.saasEbayReapprovalContext,context);assert.equal(c.state.saasError,'new-context');
  assert.equal(c.state.saasLoading,true);assert.equal(c.state.saasConfirmations[0],newer);
  assert.equal(c.actions.length,0);assert.equal(c.toasts.length,0);assert.equal(renders,0);assert.equal(c.calls.length,1);
  assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});

test('inventory success does not clear another action recovery context selected during refresh',async()=>{
  const c=inventoryRecoveryFixture();await c.handleSaasEbayExecutionRecovery('old','prepare');
  const refresh=c.refreshSaasState;let context;
  c.refreshSaasState=async()=>{
    await refresh();const newer={...c.oldInventory,confirmation_id:'other-action',action_type:'publish_listing',
      item:{publish_payload:{listing:{sku:'OTHER-SKU'}}}};
    c.state.saasConfirmations.push(newer);context=c.saasEbayRecoveryContext(newer);c.state.saasEbayReapprovalContext=context;
  };
  assert.equal(await c.createSaasInventoryLocationConfirmation(),true);
  assert.equal(c.state.saasEbayReapprovalContext,context);assert.equal(c.calls.length,1);
  assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});

async function displayRecoveryFixture(kind='inventory',status='needs_revision',nextAction='prepare_reapproval') {
  const c=inventoryRecoveryFixture();
  // Reach a real verified inventory pending first; the display scenario then
  // supplies the later durable server projection, never a fake pending recovery.
  assert.equal(await c.createSaasInventoryLocationConfirmation(),true);
  const card=c.created[0];card.confirmation_id=`${kind}-old`;card.status=status;card.title='Same product action';
  if(kind!=='inventory') {
    const payload={listing:{sku:'SKU-A',title:'Current product'},listing_project_identity:{key:'project-A'}};
    card.action_type=kind==='draft'?'save_ebay_listing_draft':'publish_listing';
    card.item={company_id:'company-A',store_id:'store-A',publish_payload:payload,
      listing_project_identity:{key:'project-A'},high_risk:true,writes_to_ebay_after_approval:true,
      real_platform_writes_enabled:false,frontend_gets_token:false,runtime_gets_token:false,secret_exposed:false};
    if(kind==='draft') Object.assign(card.item,{source:'merchant_ebay_draft_save_intake',draft_save_capability_requested:true,
      public_publish_enabled:false,creates_public_listing:false,requires_publish_offer_call:false});
    else if(kind==='controlled') {
      const draft={offer_id:'offer-A',sku:'SKU-A',source_execution_id:'saved-draft-execution'};
      payload.existing_ebay_draft=draft;
      Object.assign(card.item,{source:'merchant_existing_ebay_draft_publish_intake',controlled_existing_draft_publish:true,
        existing_ebay_draft:draft,source_execution_id:draft.source_execution_id,source_confirmation_id:'saved-draft-confirmation',
        public_publish_enabled:true,creates_public_listing:true,requires_publish_offer_call:true});
    }
    card.item.publish_payload_sha256=await c.saasSha256Hex(JSON.stringify(c.saasCanonicalJsonValue(payload)));
    if(['legacy','cleanup'].includes(kind)) {
      card.item.source='merchant_publish_confirmation_intake';
      delete card.item.writes_to_ebay_after_approval;delete card.item.publish_payload_sha256;
    }
    if(kind==='cleanup') {
      c.cleanupSource={...JSON.parse(JSON.stringify(card)),confirmation_id:'source-publish',title:'Source publish',status:'executed'};
      card.action_type='cleanup_test_listing';card.item={source:'publish_recovery_cleanup_plan',source_publish_confirmation_id:'source-publish',
        action_type:'cleanup_test_listing',sku:'SKU-A',listing_id:'listing-A',offer_id:'offer-A',operation_count:3,
        writes_to_ebay:true,secret_exposed:false,access_token_returned_to_frontend:false,access_token_returned_to_runtime:false,
        raw_response_stored:false,cleanup_plan:{status:'plan_only',confirmation_required:true,secret_exposed:false,operations:[
          {operation:'end_listing',listing_id:'listing-A',writes_to_ebay:true},
          {operation:'delete_offer',offer_id:'offer-A',writes_to_ebay:true},
          {operation:'delete_inventory_item',sku:'SKU-A',writes_to_ebay:true}]}};
    }
  }
  card.execution_recovery={company_id:'company-A',store_id:'store-A',confirmation_id:card.confirmation_id,
    action_type:card.action_type,status:nextAction==='reconcile_read_only'?'execution_reconciliation_required':
      nextAction==='view_receipt'?'execution_completed':'execution_authority_blocked',
    zero_write_proven:['prepare_reapproval','view_replacement'].includes(nextAction),next_action:nextAction,
    automatic_retry_allowed:false,secret_exposed:false};
  c.state.saasConfirmations=c.cleanupSource?[c.cleanupSource,card]:[card];c.displayCard=card;c.calls=[];c.panel={innerHTML:''};
  Object.assign(c,{saasVerifiedUnpublishedDraftSaveConfirmations:new WeakSet(),saasVerifiedControlledPublishConfirmations:new WeakSet(),
    document:{querySelector:selector=>selector==='#saasConfirmPanel'?c.panel:selector==='#confirmGrid'?{}:null},
    saasLatestProductWorkflowTask:()=>null,saasCurrentUnpublishedDraftReceipt:()=>({offerId:'offer-A',sku:'SKU-A',executionId:'saved-draft-execution'}),
    saasNormalizeListingProjectIdentity:value=>value?.key?{...value,source_report_id:value.source_report_id||'',candidate_id:value.candidate_id||''}:null,
    saasTimestampMillis:value=>Date.parse(value||0)||0,saasProductLabelForConfirmation:()=> 'Product A',saasWorkflowProductLabel:()=>'',
    saasWorkbenchConfirmationTitle:row=>`${row.title||'Action'} ${row.confirmation_id}`,saasWorkbenchConfirmationReason:row=>row.reason||'',
    saasModelValueProductLabel:()=>'',saasListingPublicationCapabilityView:()=>({label:'Synthetic capability'}),
    renderSaasModuleAiGoalStrip:()=>'',saasWorkbenchActionLabel:value=>value,saasTitleWithProduct:value=>value,
    isSaasDomesticBillingRefundConfirmation:()=>false,saasWorkbenchDefaultActionLabel:()=> '默认暂停',saasTimestampLabel:()=>'',
    saasWorkbenchApprovalBriefMarkup:()=>'',saasControlledExistingDraftPublishDetailMarkup:()=>'',
    saasWorkbenchConfirmationSource:()=> 'Synthetic backend',renderSaasConfirmationMerchantBrief:()=>'',
    saasConfirmationAfterApprovalText:()=> '批准后仍需另行执行',saasConfirmationApproveButtonLabel:()=> '批准本次',
    isSaasUniqueCurrentReadOnlyOAuthConfirmation:()=>false,isSaasUniqueCurrentUnpublishedDraftOAuthConfirmation:()=>false,
    saasConfirmationActionAttributes:row=>`data-saas-confirmation="${row.confirmation_id}"`,bindSaasExactReadOnlyOAuthConfirmationButtons:()=>{},
  });
  const names=['isSaasExactReadOnlyOAuthConfirmation','isSaasExactUnpublishedDraftOAuthConfirmation',
    'isSaasReadOnlyOAuthSensitiveConfirmation','isSaasExactReadOnlySyncConfirmation','isSaasReadOnlySyncSensitiveConfirmation',
    'isSaasExactUnpublishedDraftSaveConfirmation','isSaasUnpublishedDraftSaveSensitiveConfirmation',
    'verifySaasUnpublishedDraftSaveConfirmations','isSaasControlledExistingDraftPublishConfirmation',
    'saasControlledExistingDraftPublishReceipt','isSaasUniqueCurrentControlledExistingDraftPublishConfirmation',
    'isSaasExactManualReconcileControlledExistingDraftPublishConfirmation','saasActiveListingConfirmationScope',
    'saasConfirmationMatchesActiveListingContext','saasConfirmationCanonicalKey','dedupeSaasConfirmations',
    'saasConfirmationsForDisplay','saasDecisionCenterVisibleConfirmations','saasDecisionCenterHeadline',
    'saasConfirmationCardProductLabel','renderSaasConfirmationReplyPreview','saasWorkbenchStatusLabel','saasWorkbenchStatusTone',
    'renderSaasConfirmPanel'];
  if(source.includes('function isSaasEbayExecutionRecoveryDisplayCard(')) names.push('isSaasEbayExecutionRecoveryDisplayCard');
  vm.runInContext(names.map(extract).join('\n'),c);
  c.verifyCards=async()=>{
    const draft=await c.verifySaasUnpublishedDraftSaveConfirmations(c.state.saasConfirmations);
    const locations=await c.verifySaasInventoryLocationConfirmations(c.state.saasConfirmations);
    c.saasVerifiedUnpublishedDraftSaveConfirmations=draft.draftSave;
    c.saasVerifiedControlledPublishConfirmations=draft.controlledPublish;
    c.saasVerifiedInventoryLocationConfirmations=locations;
  };
  await c.verifyCards();return c;
}

function renderDisplay(c) {
  const display=c.saasConfirmationsForDisplay(c.state.saasConfirmations);
  const visible=c.saasDecisionCenterVisibleConfirmations(display,c.state.saasConfirmations);
  c.renderSaasConfirmPanel();return {display,visible,html:c.panel.innerHTML};
}

for(const phase of ['waiting','expired','admitted']) test(`actual persisted draft prewrite status displays ${phase} recovery`,async()=>{
  const c=await displayRecoveryFixture('draft','external_execution_claimed_prewrite');
  const recovery=c.displayCard.execution_recovery;
  Object.assign(recovery,phase==='waiting'?{status:'execution_in_progress',zero_write_proven:true,next_action:'wait_for_current_attempt'}:
    phase==='expired'?{status:'execution_prewrite_recovery_available',zero_write_proven:true,next_action:'prepare_reapproval'}:
      {status:'execution_reconciliation_required',zero_write_proven:false,next_action:'reconcile_read_only',provider_result_unknown:true});
  const result=renderDisplay(c);
  assert(result.display.includes(c.displayCard));assert(result.visible.includes(c.displayCard));
  assert.match(result.html,/执行请求已接收/);assert.doesNotMatch(result.html,/external_execution_claimed_prewrite/);
  if(phase==='waiting') {assert.match(result.html,/原请求仍在处理/);assert.doesNotMatch(result.html,/reprepare-ebay-execution|approve-confirmation|reconcile-ebay-execution/);}
  else if(phase==='expired') {assert.match(result.html,/reprepare-ebay-execution/);assert.match(result.html,/仍需单独确认/);}
  else {assert.match(result.html,/reconcile-ebay-execution/);assert.doesNotMatch(result.html,/reprepare-ebay-execution|approve-confirmation/);}
  assert.equal(c.calls.length,0);
});

for(const kind of ['inventory','draft','controlled','legacy','cleanup']) {
  test(`${kind} genuinely blocked approved recovery is visible but ordinary approved is unchanged`,async()=>{
    const c=await displayRecoveryFixture(kind,'approved');
    assert.equal(c.isSaasEbayExecutionRecoveryDisplayCard(c.displayCard),false);
    assert.equal(c.renderSaasEbayExecutionRecovery(c.displayCard),'');
    c.displayCard.execution_recovery.reason_code='approval_authority_changed_reapproval_required';
    const result=renderDisplay(c);
    assert(result.visible.includes(c.displayCard));assert.match(result.html,/reprepare-ebay-execution/);
    assert.equal(result.display.filter(card=>card.confirmation_id===c.displayCard.confirmation_id).length,1);
    assert.equal(result.visible.filter(card=>card.confirmation_id===c.displayCard.confirmation_id).length,1);
    assert.equal((result.html.match(/data-saas-action="reprepare-ebay-execution"/g)||[]).length,1);
    assert.doesNotMatch(result.html,/data-saas-action="approve-confirmation"|data-saas-action="execute/);
    assert.equal(c.calls.length,0);
  });
}

for(const kind of ['inventory','draft','controlled','legacy','cleanup']) {
  test(`${kind} normal pending still reaches the real filter-visible-panel pipeline`,async()=>{
    const c=await displayRecoveryFixture(kind,'pending');delete c.displayCard.execution_recovery;
    const result=renderDisplay(c);
    assert(result.display.includes(c.displayCard));assert(result.visible.includes(c.displayCard));
    assert.match(result.html,/data-saas-action="approve-confirmation"/);assert.doesNotMatch(result.html,/reprepare-ebay-execution/);
    assert.equal(c.calls.length,0);
  });
  test(`${kind} zero-write recovery is actually visible without approval or execution`,async()=>{
    const c=await displayRecoveryFixture(kind),result=renderDisplay(c);
    assert(result.display.includes(c.displayCard),'exact recovery must survive the display filter');
    assert(result.visible.includes(c.displayCard));assert.match(result.html,/data-saas-action="reprepare-ebay-execution"/);
    assert.match(result.html,/待重新准备/);assert.match(result.html,/未执行或未完成<\/span>\s*<strong>1<\/strong>/);
    assert.doesNotMatch(result.html,/data-saas-action="(?:approve-confirmation|execute[^\"]*)"/);assert.equal(c.calls.length,0);
  });
  test(`${kind} unknown recovery has one visible read-only action and no retry`,async()=>{
    const c=await displayRecoveryFixture(kind,'external_execution_processing_manual_reconcile','reconcile_read_only');
    const result=renderDisplay(c);assert(result.visible.includes(c.displayCard));
    assert.equal((result.html.match(/data-saas-action="(?:reconcile-ebay-execution|recover-publish)"/g)||[]).length,1);
    assert.match(result.html,/待核对/);assert.match(result.html,/未执行或未完成<\/span>\s*<strong>1<\/strong>/);
    assert.doesNotMatch(result.html,/reprepare-ebay-execution|data-saas-action="approve-confirmation"/);assert.equal(c.calls.length,0);
  });
  test(`${kind} completed recovery exposes only its original receipt`,async()=>{
    const c=await displayRecoveryFixture(kind,'executed','view_receipt'),result=renderDisplay(c);
    assert(result.visible.includes(c.displayCard));assert.match(result.html,/本次已完成，请查看原回执/);
    assert.doesNotMatch(result.html,/reprepare-ebay-execution|reconcile-ebay-execution|recover-publish|approve-confirmation/);
    assert.equal(c.calls.length,0);
  });
  test(`${kind} same-product old histories survive beside their one new pending ID`,async()=>{
    const c=await displayRecoveryFixture(kind),old=c.displayCard;
    old.execution_recovery.next_action='view_replacement';old.execution_recovery.replacement_confirmation_id='new-pending';
    const other=JSON.parse(JSON.stringify(old));other.confirmation_id='second-history';
    other.execution_recovery.confirmation_id=other.confirmation_id;
    old.execution_recovery.replacement_confirmation_id=other.confirmation_id;
    other.item.replaces_confirmation_id=old.confirmation_id;
    const pending=JSON.parse(JSON.stringify(old));pending.confirmation_id='new-pending';pending.status='pending';
    pending.item.replaces_confirmation_id=other.confirmation_id;delete pending.execution_recovery;
    c.state.saasConfirmations=[...(c.cleanupSource?[c.cleanupSource]:[]),old,other,pending];await c.verifyCards();const result=renderDisplay(c);
    assert.deepEqual(Array.from(result.visible,row=>row.confirmation_id).sort(),[old.confirmation_id,'second-history','new-pending'].sort());
    assert.equal((result.html.match(/data-saas-action="view-ebay-replacement"/g)||[]).length,2);
    assert.equal((result.html.match(/data-saas-action="approve-confirmation"/g)||[]).length,1);
    assert.equal(c.state.saasConfirmations.length,c.cleanupSource?4:3);assert.equal(c.calls.length,0);
  });
  test(`${kind} malformed or foreign recovery cannot enter the dedicated display path`,async()=>{
    for(const corrupt of [
      c=>{delete c.displayCard.execution_recovery;},
      c=>{c.displayCard.execution_recovery.confirmation_id='wrong';},
      c=>{c.displayCard.execution_recovery.action_type='refund';},
      c=>{c.displayCard.execution_recovery.store_id='store-B';},
      c=>{c.displayCard.execution_recovery.company_id='company-B';},
      c=>{c.displayCard.execution_recovery.automatic_retry_allowed=true;},
      c=>{c.displayCard.execution_recovery.secret_exposed=true;},
      c=>{c.displayCard.store_id='store-B';},
      c=>{c.displayCard.company_id='company-B';},
      c=>{c.state.saasConfirmations.push(JSON.parse(JSON.stringify(c.displayCard)));},
      c=>{if(kind==='inventory') c.displayCard.item.location_payload.location.address.city='';
        else if(kind==='cleanup') c.displayCard.item.cleanup_plan.operations[2].sku='OTHER';
        else c.displayCard.item.publish_payload.listing.sku='OTHER';},
      c=>{if(kind==='inventory') c.displayCard.item.location_payload_sha256='0'.repeat(64);
        else if(kind==='cleanup') c.displayCard.item.source_publish_confirmation_id='wrong-source';
        else if(kind==='legacy') c.displayCard.item.publish_payload.listing.title='';
        else c.displayCard.item.publish_payload_sha256='0'.repeat(64);},
    ]) {
      const c=await displayRecoveryFixture(kind);corrupt(c);await c.verifyCards();const result=renderDisplay(c);
      if(!['legacy','cleanup'].includes(kind)) assert.equal(result.display.length,0);
      else assert.equal(c.isSaasEbayExecutionRecoveryDisplayCard(c.displayCard,c.state.saasConfirmations),false);
      assert.doesNotMatch(result.html,/reprepare-ebay-execution|reconcile-ebay-execution|approve-confirmation/);
      assert.equal(c.calls.length,0);
    }
  });
}

test('legacy controlled manual-reconcile fallback remains visible without a new recovery summary',async()=>{
  const c=await displayRecoveryFixture('controlled','external_execution_processing_manual_reconcile','reconcile_read_only');
  delete c.displayCard.execution_recovery;const result=renderDisplay(c);
  assert(result.visible.includes(c.displayCard));assert.match(result.html,/data-saas-action="recover-publish"/);
  assert.doesNotMatch(result.html,/reprepare-ebay-execution|approve-confirmation/);assert.equal(c.calls.length,0);
});

for(const kind of ['inventory','controlled']) test(`${kind} recovery display never relaxes duplicate active approval eligibility`,async()=>{
  const c=await displayRecoveryFixture(kind,'pending');delete c.displayCard.execution_recovery;
  const second=JSON.parse(JSON.stringify(c.displayCard));second.confirmation_id='second-active';
  c.state.saasConfirmations.push(second);await c.verifyCards();const result=renderDisplay(c);
  assert.equal(result.display.length,0);assert.doesNotMatch(result.html,/approve-confirmation/);assert.equal(c.calls.length,0);
});

for(const kind of ['inventory','draft','controlled','legacy','cleanup'])
test(`${kind} long exact history cannot hide its pending or linked ninth replacement`,async()=>{
  const c=await displayRecoveryFixture(kind),template=c.displayCard,history=[];
  for(let index=0;index<10;index++) {
    const card=JSON.parse(JSON.stringify(template));card.confirmation_id=`${kind}-history-${index}`;
    Object.assign(card.execution_recovery,{confirmation_id:card.confirmation_id,next_action:'view_replacement',
      replacement_confirmation_id:index===9?'latest-pending':`${kind}-history-${index+1}`});
    if(index) card.item.replaces_confirmation_id=history[index-1].confirmation_id;
    history.push(card);
  }
  const pending=JSON.parse(JSON.stringify(template));pending.confirmation_id='latest-pending';pending.status='pending';
  pending.item.replaces_confirmation_id=history[9].confirmation_id;delete pending.execution_recovery;
  c.state.saasConfirmations=[...(c.cleanupSource?[c.cleanupSource]:[]),...history,pending];await c.verifyCards();
  const result=renderDisplay(c);
  assert.equal(result.visible[0],pending,'current pending must precede read-only history');
  assert.equal(result.visible.length,11,'all exact fetched history remains reachable');
  assert.equal((result.html.match(/data-saas-action="approve-confirmation"/g)||[]).length,1);
  assert.equal((result.html.match(/data-saas-action="view-ebay-replacement"/g)||[]).length,10);
  assert.equal(await c.handleSaasEbayExecutionRecovery(history[8].confirmation_id,'replacement'),true);
  const linked=renderDisplay(c);assert(linked.visible.includes(history[9]));assert(linked.html.includes(history[9].confirmation_id));
  assert.equal(c.calls.length,0);assert.equal(c.state.saasConfirmations.length,c.cleanupSource?12:11);
});

for(const kind of ['inventory','draft','controlled','legacy','cleanup'])
for(const status of ['pending','approved','executed'])
test(`${kind} exact linked ${status} remains visible beside an unrelated current pending`,async()=>{
  const c=await displayRecoveryFixture(kind),old=c.displayCard;
  const replacement=JSON.parse(JSON.stringify(old));replacement.confirmation_id='exact-replacement';replacement.status=status;
  replacement.item.replaces_confirmation_id=old.confirmation_id;
  if(status==='executed') Object.assign(replacement.execution_recovery,{confirmation_id:replacement.confirmation_id,
    status:'execution_completed',zero_write_proven:false,next_action:'view_receipt'});
  else delete replacement.execution_recovery;
  Object.assign(old.execution_recovery,{next_action:'view_replacement',replacement_confirmation_id:replacement.confirmation_id});
  const pending={company_id:'company-A',store_id:'store-A',confirmation_id:'unrelated-pending',action_type:'change_price',
    title:'Other current action',status:'pending',item:{listing_project_identity:{key:'project-A'},sku:'SKU-A'}};
  const unrelated={...pending,confirmation_id:'unrelated-approved',title:'Unrelated history',status:'approved'};
  c.state.saasConfirmations=[...(c.cleanupSource?[c.cleanupSource]:[]),old,replacement,pending,unrelated];await c.verifyCards();
  assert.equal(await c.handleSaasEbayExecutionRecovery(old.confirmation_id,'replacement'),true);
  const result=renderDisplay(c);
  assert(result.visible.includes(pending));assert(result.visible.includes(old));
  assert.equal(result.visible.filter(card=>card.confirmation_id===replacement.confirmation_id).length,1);
  assert(result.html.includes(`Same product action ${replacement.confirmation_id}`));
  assert(!result.visible.includes(unrelated),'Exact linkage must not expose unrelated approved history');
  assert.equal(c.calls.length,0);
});

function installActualRefreshPublication(c,phase) {
  const refresh=extract('refreshSaasState');
  const begin=phase==='core'?'    const coreLiveConfirmations = ':'    // Extended endpoints reuse the core batch.';
  const finish=phase==='core'?'    state.saasServiceHealth = coreServiceHealth':'    state.saasMerchantMemory = merchantMemory';
  assert.equal(refresh.split(begin).length,2,'publication start anchor must be unique');
  assert.equal(refresh.split(finish).length,2,'publication end anchor must be unique');
  const start=refresh.indexOf(begin),end=refresh.indexOf(finish);
  assert(start>=0&&end>start,'complete real refresh publication block exists');
  // Execute the production block, including every await and final context guard.
  // Only network inputs and the real surrounding batch ownership are injected.
  // Extended publication starts after its core array was already published; no
  // qualification or completion result is supplied by this host.
  vm.runInContext(`async function applyActualRefresh(cards,isCurrentRefresh) {
    const coreConfirmations={confirmations:cards},confirmations=coreConfirmations;
    const submittedAtReadStart=[...(state.saasEbaySubmittedOutcomes||[])];
    let confirmationStateAtReadStart=state.saasConfirmations,confirmationStateApplied=false;
    ${phase==='extended'?`const coreLiveConfirmations=coreConfirmations.confirmations;
      state.saasConfirmations=coreLiveConfirmations;confirmationStateApplied=true;`:''}
    ${refresh.slice(start,end)}
  }`,c);
}

for(const phase of ['core','extended']) for(const transition of ['same-context','account','store','ABA'])
for(const scenario of ['draft-pending','draft-recovery','inventory-pending','inventory-recovery','controlled-recovery'])
test(`${phase} ${transition} delayed digest cannot overwrite current ${scenario} qualification`,async()=>{
  const [kind,mode]=scenario.split('-');
  const c=await displayRecoveryFixture(kind,mode==='pending'?'pending':'needs_revision');
  if(mode==='pending') delete c.displayCard.execution_recovery;
  installActualRefreshPublication(c,phase);
  const old=c.displayCard,newer=JSON.parse(JSON.stringify(old));newer.confirmation_id='new-current';
  if(newer.execution_recovery) newer.execution_recovery.confirmation_id=newer.confirmation_id;
  const digest=c.saasSha256Hex;let release,entered;let hold=true;
  const atDigest=new Promise(resolve=>{entered=resolve;});
  c.saasSha256Hex=async value=>{
    if(hold) {hold=false;await new Promise(resolve=>{release=resolve;entered();});}
    return digest(value);
  };
  let generation=1;const oldGeneration=generation,oldGuard=c.saasEbayStoreRequestGuard('store-A');
  const obsolete=c.applyActualRefresh([old],()=>generation===oldGeneration&&oldGuard());await atDigest;
  generation++;
  if(transition==='account') c.saasAccountSessionEpoch++;
  else if(transition==='store') {
    c.store={store_id:'store-B',platform:'ebay'};newer.store_id='store-B';newer.item.store_id='store-B';
    if(newer.execution_recovery) newer.execution_recovery.store_id='store-B';
  } else if(transition==='ABA') {switchAwayAndBack(c);c.store.platform='ebay';}
  const currentGeneration=generation,currentGuard=c.saasEbayStoreRequestGuard(c.store.store_id);
  await c.applyActualRefresh([newer],()=>generation===currentGeneration&&currentGuard());
  assert.equal(c.state.saasConfirmations[0],newer);
  assert(c.saasConfirmationsForDisplay(c.state.saasConfirmations).includes(newer),'current normal publication is qualified');
  release();await obsolete;
  assert.equal(c.state.saasConfirmations[0],newer,'old refresh cannot replace current cards');
  assert(c.saasConfirmationsForDisplay(c.state.saasConfirmations).includes(newer),'old digest must not erase current qualification');
  const collection=kind==='draft'?c.saasVerifiedUnpublishedDraftSaveConfirmations:
    kind==='controlled'?c.saasVerifiedControlledPublishConfirmations:c.saasVerifiedInventoryLocationConfirmations;
  assert(collection.has(newer));assert.equal(collection.has(old),false);assert.equal(c.calls.length,0);
});

function publishRecoveryFixture(mode) {
  const c=recoveryFixture(),old=c.state.saasConfirmations[0];c.oldPublish=old;c.timers=[];c.scrolls=0;
  c.setView=view=>{c.state.view=view;c.actions.push(['view',view]);};
  c.window.setTimeout=callback=>{c.timers.push(callback);};
  c.document.querySelector=()=>({scrollIntoView:()=>{c.scrolls++;}});
  if(mode==='draft') {old.action_type='save_ebay_listing_draft';old.execution_recovery.action_type=old.action_type;}
  if(mode==='controlled') {
    old.item.existing_ebay_draft={offer_id:'offer-A',sku:'SKU-A',source_execution_id:'execution-A'};
    c.saasCurrentUnpublishedDraftReceipt=()=>({offerId:'offer-A',sku:'SKU-A',executionId:'execution-A'});
    vm.runInContext(extract('createSaasExistingDraftPublishConfirmation'),c);
  }
  c.fetch=async(url,options)=>{
    const body=JSON.parse(options.body);c.calls.push({url,method:options.method,body});
    const confirmation={company_id:'company-A',store_id:'store-A',confirmation_id:'new-pending',status:'pending',
      action_type:old.action_type,item:{replaces_confirmation_id:body.replaces_confirmation_id}};
    if(mode==='controlled') Object.assign(confirmation.item,{source:'merchant_existing_ebay_draft_publish_intake',
      controlled_existing_draft_publish:true,creates_public_listing:true,requires_publish_offer_call:true,
      existing_ebay_draft:{...old.item.existing_ebay_draft,offer_status:'UNPUBLISHED',public_listing_created:false}});
    return {ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({confirmation,
      real_platform_writes_enabled:false,controlled_existing_draft_publish_enabled:true,secret_exposed:false})};
  };
  c.prepare=()=>mode==='controlled'?c.createSaasExistingDraftPublishConfirmation({dataset:{saasOfferId:'offer-A',
    saasSku:'SKU-A',saasExecutionId:'execution-A'}}):c.createSaasPublishConfirmationFromIntakeForm(mode==='draft'?'ebay-draft':'publish');
  return c;
}

for(const mode of ['legacy','draft','controlled']) {
  test(`${mode} successful preparation consumes only its own recovery context`,async()=>{
    const c=publishRecoveryFixture(mode);assert.equal(await c.handleSaasEbayExecutionRecovery('old','prepare'),true);
    assert.equal(await c.prepare(),true);assert.equal(c.state.saasEbayReapprovalContext,null);
    assert.equal(c.calls.length,1);assert.equal(c.calls[0].body.replaces_confirmation_id,'old');
    assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
  });
  for(const selection of ['another-object','same-id-new-selection'])
  test(`${mode} delayed refresh preserves ${selection} instead of clearing it`,async()=>{
    const c=publishRecoveryFixture(mode);await c.handleSaasEbayExecutionRecovery('old','prepare');
    const consumed=c.state.saasEbayReapprovalContext;let release;
    const atRefresh=new Promise(ready=>{c.refreshSaasState=()=>new Promise(resolve=>{release=resolve;ready();});});
    const request=c.prepare();await atRefresh;
    let id='old';
    if(selection==='another-object') {
      id='newer-location';const newer={company_id:'company-A',store_id:'store-A',confirmation_id:id,
        action_type:'create_ebay_inventory_location',status:'needs_revision',item:{merchant_location_key:'newer-warehouse'},
        execution_recovery:{...c.oldPublish.execution_recovery,confirmation_id:id,action_type:'create_ebay_inventory_location'}};
      c.state.saasConfirmations.push(newer);
    }
    assert.equal(await c.handleSaasEbayExecutionRecovery(id,'prepare'),true);
    const selected=c.state.saasEbayReapprovalContext;assert.notEqual(selected,consumed);
    release();assert.equal(await request,true);assert.equal(c.state.saasEbayReapprovalContext,selected);
    assert.equal(c.calls.length,1);assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
  });
  test(`${mode} failed preparation preserves the original usable recovery selection`,async()=>{
    const c=publishRecoveryFixture(mode);await c.handleSaasEbayExecutionRecovery('old','prepare');
    const selected=c.state.saasEbayReapprovalContext;
    c.fetch=async(url,options)=>{c.calls.push({url,method:options.method});return {ok:false,status:409,
      headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'prepare_failed'})};};
    assert.equal(await c.prepare(),false);assert.equal(c.state.saasEbayReapprovalContext,selected);
    assert.equal(c.calls.length,1);assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
  });
  for(const transition of ['account','store','ABA'])
  test(`${mode} refresh after ${transition} change cannot navigate or clear newer selection`,async()=>{
    const c=publishRecoveryFixture(mode);await c.handleSaasEbayExecutionRecovery('old','prepare');let release;
    const atRefresh=new Promise(ready=>{c.refreshSaasState=()=>new Promise(resolve=>{release=resolve;ready();});});
    const request=c.prepare();await atRefresh;
    if(transition==='account') c.saasAccountSessionEpoch++;
    else if(transition==='store') c.store={store_id:'store-B'};
    else switchAwayAndBack(c);
    const selected={...c.saasEbayRecoveryContext(c.oldPublish),confirmationId:'newer'};
    c.state.saasEbayReapprovalContext=selected;c.state.saasLoading=true;c.state.saasError='current';c.actions=[];c.toasts=[];
    release();assert.equal(await request,false);assert.equal(c.state.saasEbayReapprovalContext,selected);
    assert.equal(c.actions.length,0);assert.equal(c.toasts.length,0);assert.equal(c.state.saasLoading,true);
    assert.equal(c.state.saasError,'current');assert.equal(c.timers.length,0);assert.equal(c.calls.length,1);
  });
}

for(const mode of ['legacy','draft']) for(const transition of ['current','account','store','ABA','view'])
test(`${mode} delayed scroll checks ${transition} context at callback time`,async()=>{
  const c=publishRecoveryFixture(mode);await c.handleSaasEbayExecutionRecovery('old','prepare');
  assert.equal(await c.prepare(),true);assert.equal(c.timers.length,1);
  if(transition==='account') c.saasAccountSessionEpoch++;
  else if(transition==='store') c.store={store_id:'store-B'};
  else if(transition==='ABA') switchAwayAndBack(c);
  else if(transition==='view') c.setView('confirm');
  c.timers[0]();assert.equal(c.scrolls,transition==='current'?1:0);assert.equal(c.calls.length,1);
});

function preflightRendererFixture(checks,ready=true,hasConfirmation=true) {
  const c={state:{saasLastPublishReadiness:{checks,ready_for_platform_adapter:ready},
    saasPreflightResults:[{status:'ready',real_execution_allowed:true}]},
    confirmation:hasConfirmation?{confirmation_id:'exact-confirmation',status:'pending',item:{writes_to_ebay_after_approval:true}}:null,
    escapeHtml:value=>String(value),publicRuntimeText:value=>String(value),
    saasMerchantWorkbenchContext:()=>({latestPacket:{packet_id:'safe-packet'}}),saasCurrentPublishConfirmationEvidence:()=>({}),
    saasAccountHealthSnapshot:()=>({status:'healthy',can_execute_real_writes:true}),saasAccountHealthTone:()=> 'green'};
  c.saasLatestPublishConfirmation=()=>c.confirmation;
  c.saasListingPublishCheckContext=()=>({confirmation:c.confirmation,latestPreflight:c.state.saasPreflightResults[0]});
  vm.createContext(c);
  vm.runInContext(['saasBackendPublishCheckTone','saasBackendPublishCheckSource','saasBackendPublishFixAction',
    'saasBackendPublishEvidenceTrust','saasBackendPublishRepairRoute','renderSaasBackendPreflightResolutionBoard',
    'saasBackendPublishImpact','saasBackendPublishDecisionGate','saasBackendPreflightDetailValue','saasBackendPreflightDetailRows',
    'saasMerchantVisiblePublishCode','saasMerchantVisibleEvidenceLabel','saasMerchantVisibleActionLabel',
    'renderSaasBackendPublishPreflightPanel','renderSaasPublishConfirmationEvidencePanel',
    'saasPublishTrafficLightReport','saasPublishTrafficLightTone','renderSaasPublishTrafficLightReport',
    'renderSaasPublishCommandSummaryPanel'].map(extract).join('\n'),c);
  c.renderAll=()=>c.renderSaasBackendPublishPreflightPanel(c.state.saasLastPublishReadiness)+
    c.renderSaasPublishConfirmationEvidencePanel(c.state.saasLastPublishReadiness)+
    c.renderSaasPublishTrafficLightReport(c.state.saasLastPublishReadiness)+c.renderSaasPublishCommandSummaryPanel();
  return c;
}

test('actual preflight renderers preserve blocking, repair-only routes and secret-safe evidence',()=>{
  const checks=[{key:'field_completeness',label:'Missing fields',status:'blocked',blocking:true,
    source_records:[{source_type:'merchant_input',source_id:'safe-id',raw_secret_visible:false,secret_exposed:false,
      frontend_gets_token:false,access_token:'SYNTHETIC_DO_NOT_RENDER'}],details:{client_secret:'SYNTHETIC_DO_NOT_RENDER'}},
    {key:'business_policies',status:'waiting',blocking:false},{key:'category_match',status:'passed',blocking:false}];
  const c=preflightRendererFixture(checks),html=c.renderAll();
  assert.equal(c.saasBackendPublishDecisionGate(checks[0],c.state.saasLastPublishReadiness).status,'blocked_before_confirmation');
  assert.equal(c.saasBackendPublishRepairRoute(checks[0],c.state.saasLastPublishReadiness).safetyLabel,'no_direct_write');
  assert.equal(c.saasBackendPublishEvidenceTrust(checks[0]).label,'trusted_source_records');
  assert.match(html,/必须先修复/);assert.match(html,/确认要求/);assert.match(html,/确认方式/);assert.match(html,/修复入口/);
  assert.match(html,/红项阻断真实发布/);assert.match(html,/仍需确认或修复/);assert.match(html,/确认单与系统体检/);
  for(const color of ['red','amber','green']) assert.match(html,new RegExp(`data-preflight-resolution-bucket="${color}"[^]*?<strong>1</strong>`));
  assert.doesNotMatch(html,/SYNTHETIC_DO_NOT_RENDER|data-saas-action="(?:execute[^\"]*|approve-confirmation)"/);
  assert.equal(c.saasPublishTrafficLightReport(c.state.saasLastPublishReadiness).real_write_allowed_without_confirmation,false);
});

test('actual green preflight remains human-confirmed and missing confirmation disables its routes',()=>{
  const check={key:'category_match',status:'passed',blocking:false},c=preflightRendererFixture([check]);
  let html=c.renderAll();assert.match(html,/仍需人工确认/);assert.match(html,/绿灯，可进入确认中心/);
  assert.match(html,/体检通过后仍需确认中心放行/);assert.match(html,/不会触发 OAuth、不会扣费、不会直接写入 eBay/);
  assert.equal(c.saasBackendPublishDecisionGate(check,c.state.saasLastPublishReadiness).status,'confirmation_required_no_direct_write');
  assert.equal(c.saasBackendPublishRepairRoute(check,c.state.saasLastPublishReadiness).confirmRoute,'decision_center_required');
  assert.equal(c.saasPublishTrafficLightReport(c.state.saasLastPublishReadiness).requires_confirmation_center,true);
  c.state.saasLastPublishReadiness.ready_for_platform_adapter=false;
  assert.match(c.renderAll(),/等待完整预检/);c.confirmation=null;
  // Use a blocked field's actual repair action, not a second green open-confirm shortcut.
  c.state.saasLastPublishReadiness.checks=[{key:'field_completeness',status:'blocked',blocking:true}];
  html=c.renderAll();assert.equal((html.match(/data-saas-action="open-confirm" disabled/g)||[]).length,3);
  assert.doesNotMatch(html,/data-saas-action="(?:execute[^\"]*|approve-confirmation)"/);
});

test('unsafe source metadata is explicitly review-only and sensitive values stay out of real renderers',()=>{
  const check={key:'field_completeness',status:'waiting',blocking:false,source_records:[{source_type:'merchant_input',
    raw_secret_visible:true,frontend_gets_token:true,secret_exposed:true,refresh_token:'SYNTHETIC_PRIVATE_VALUE'}]};
  const c=preflightRendererFixture([check],false),html=c.renderAll();
  assert.equal(c.saasBackendPublishEvidenceTrust(check).label,'review_source_records');
  assert.equal(c.saasBackendPublishEvidenceTrust(check).safeCount,0);
  assert.match(html,/证据来源需要复核/);assert.match(html,/黄项需要人工复核/);
  assert.doesNotMatch(html,/SYNTHETIC_PRIVATE_VALUE|data-saas-action="execute/);
});

test('legacy manual reconciliation retains priority without suppressing a current pending',async()=>{
  const c=await displayRecoveryFixture('controlled','external_execution_processing_manual_reconcile','reconcile_read_only');
  const manual=c.displayCard;delete manual.execution_recovery;
  const pending=JSON.parse(JSON.stringify(manual));pending.confirmation_id='current-controlled-pending';pending.status='pending';
  c.state.saasConfirmations=[pending,manual];await c.verifyCards();const result=renderDisplay(c);
  assert.equal(result.visible[0],manual);assert.equal(result.visible[1],pending);assert.equal(result.visible.length,2);
  assert.equal((result.html.match(/data-saas-action="recover-publish"/g)||[]).length,1);
  assert.equal((result.html.match(/data-saas-action="approve-confirmation"/g)||[]).length,1);
  assert.doesNotMatch(result.html,/reprepare-ebay-execution|data-saas-action="execute/);assert.equal(c.calls.length,0);
});

function installActualViewNavigation(c) {
  Object.assign(c,{normalizeSaasProtectedView:value=>value,safeQueryParam:()=>'',normalizeSaasListingMode:()=> 'single',
    syncSaasProjectRoute:()=>{},views:[],sanitizeSaasInactiveMerchantViews:()=>{},pageTitle:{},updateTopbarAction:()=>{},
    renderSaasProtectedStateLoadingView:()=>true,updateOverlay:()=>{},renderWorkflowFeedbackWidget:()=>{}});
  const querySelector=c.document.querySelector;
  c.document={...c.document,body:{dataset:{}},documentElement:{dataset:{}},querySelectorAll:()=>[],
    querySelector:selector=>selector.startsWith('#view-')?null:querySelector?.(selector)};
  vm.runInContext(extract('setView'),c);
}

function interactionFixture(mode) {
  const c=mode==='inventory'?inventoryRecoveryFixture():publishRecoveryFixture(['legacy','draft','controlled'].includes(mode)?mode:'legacy');
  if(mode==='inventory') c.prepare=()=>c.createSaasInventoryLocationConfirmation();
  if(mode==='cleanup'||mode==='readonly') {
    vm.runInContext(['createSaasTestListingCleanupPlan','recoverSaasPublishState'].map(extract).join('\n'),c);
    c.prepare=()=>mode==='cleanup'?c.createSaasTestListingCleanupPlan('old'):c.recoverSaasPublishState('old');
    c.fetch=async(url,options)=>{c.calls.push({url,method:options.method});return {ok:true,status:201,
      headers:{get:()=> 'application/json'},json:async()=>({created:true,publish_recovery:{marker:'old'},
        publish_readiness:{marker:'old'},cleanup_confirmation:{confirmation_id:'old-created',status:'pending'}})};};
  }
  c.state.view='product';c.timers=c.timers||[];c.scrolls=0;
  installActualViewNavigation(c);
  return c;
}

for(const mode of ['legacy','draft','controlled','inventory','cleanup','readonly'])
for(const phase of ['post','refresh']) for(const outcome of ['success','error'])
for(const selection of ['same-id-new-object','different-project','ordinary-new-project'])
for(const navigation of ['unchanged-view','view-ABA'])
test(`${mode} old ${phase} ${outcome} cannot mutate ${selection} interaction after ${navigation}`,async()=>{
  const c=interactionFixture(mode);
  if(selection!=='ordinary-new-project') await c.handleSaasEbayExecutionRecovery('old','prepare');
  let entered,release;const held=new Promise(resolve=>{entered=resolve;});
  const originalFetch=c.fetch,originalRefresh=c.refreshSaasState;
  if(phase==='post') c.fetch=async(...args)=>{
    const response=await originalFetch(...args);await new Promise(resolve=>{release=resolve;entered();});
    return outcome==='success'?response:{ok:false,status:409,headers:{get:()=> 'application/json'},
      text:async()=>JSON.stringify({error:'obsolete-prepare-failed'})};
  };
  else c.refreshSaasState=async options=>{
    await new Promise(resolve=>{release=resolve;entered();});
    if(outcome==='error') throw new Error('obsolete-refresh-failed');
    if(!options?.saasRequestIsCurrent || options.saasRequestIsCurrent()) await originalRefresh(options);
  };
  const pending=c.prepare();await held;
  if(selection==='same-id-new-object') c.state.saasEbayReapprovalContext={...c.state.saasEbayReapprovalContext};
  else {
    c.saasCurrentListingProjectIdentity=()=>({key:'project-Y'});
    c.state.saasMerchantProjectStatusRequestGeneration=(c.state.saasMerchantProjectStatusRequestGeneration||0)+1;
    c.state.saasEbayReapprovalContext=null;
  }
  if(navigation==='view-ABA') {c.setView('activity');c.setView('product');}
  // A newer UI request owns the sentinel loading state; selection alone does not.
  c.saasEbayStoreRequestGuard('store-A',{interaction:true}).beginLoading?.();
  const current={context:c.state.saasEbayReapprovalContext,readiness:{marker:'new'},evidence:{marker:'new'},
    preflight:[{marker:'new'}],recovery:{marker:'new'},cards:[...c.state.saasConfirmations]};
  Object.assign(c.state,{saasLastPublishReadiness:current.readiness,saasLastPublishConfirmationEvidence:current.evidence,
    saasPreflightResults:current.preflight,saasLastPublishRecovery:current.recovery,saasError:'new',saasLoading:true,
    confirmFilter:'new',saasConfirmations:current.cards});
  c.actions=[];c.toasts=[];let renders=0;c.renderSaasBackendPanel=()=>{renders++;};c.renderSaasConfirmPanel=()=>{renders++;};
  release();await pending;
  assert.equal(c.state.saasEbayReapprovalContext,current.context);assert.equal(c.state.view,'product');
  assert.equal(c.state.saasLastPublishReadiness,current.readiness);assert.equal(c.state.saasLastPublishConfirmationEvidence,current.evidence);
  assert.equal(c.state.saasPreflightResults,current.preflight);assert.equal(c.state.saasLastPublishRecovery,current.recovery);
  assert.equal(c.state.saasConfirmations,current.cards);assert.equal(c.state.saasError,'new');assert.equal(c.state.confirmFilter,'new');
  assert.equal(c.state.saasLoading,true);assert.equal(renders,0);assert.equal(c.toasts.length,0);
  assert.equal(c.calls.length,1);assert(!c.calls.some(call=>/decision|execute/.test(call.url)));
});

for(const mode of ['legacy','draft']) test(`${mode} actual product-view ABA invalidates delayed scroll`,async()=>{
  const c=interactionFixture(mode);await c.handleSaasEbayExecutionRecovery('old','prepare');
  c.document.querySelector=()=>({dataset:{},scrollIntoView:()=>{c.scrolls++;}});
  assert.equal(await c.prepare(),true);assert.equal(c.timers.length,1);
  c.setView('activity');c.setView('product');c.timers[0]();assert.equal(c.scrolls,0);
});

for(const outcome of ['success','error']) test(`actual refresh ${outcome} respects an obsolete parent interaction`,async()=>{
  const c=interactionFixture('legacy');let current=true,release;
  Object.assign(c,{saasStateRefreshGeneration:0,hasSaasProtectedSessionCandidate:()=>false,saasAccountStorageAliases:()=>[],
    normalizeSaasCeoCommand:value=>value,normalizeSaasAiCeoLatestTurn:value=>value,shouldKeepSaasAiCeoThreadTurn:()=>true,
    resetSaasProtectedWorkbenchState:()=>{c.state.saasLastPublishReadiness='obsolete-reset';},
    isSaasUnrecoverableSessionError:()=>false,syncAppStartVisibleShellGuard:()=>{},syncSaasPublicMvpMode:()=>{},
    renderGlobalLoopWorkbench:()=>{},renderStoreContext:()=>{},activeSaasRefreshView:()=> 'product'});
  c.fetch=async()=>new Promise(resolve=>{release=()=>resolve({ok:outcome==='success',status:outcome==='success'?200:500,
    headers:{get:()=> 'application/json'},json:async()=>({marker:'old'}),text:async()=>JSON.stringify({error:'old'})});});
  // The first function includes following constants; the VM owns their scope.
  vm.runInContext(extract('refreshSaasState'),c);
  const pending=c.refreshSaasState({silent:true,saasRequestIsCurrent:()=>current});
  current=false;c.state.saasLoading=true;c.state.saasError='current';c.state.saasServiceHealth={marker:'new'};
  const health=c.state.saasServiceHealth;c.toasts=[];let renders=0;c.renderSaasBackendPanel=()=>{renders++;};
  release();await pending;
  assert.equal(c.state.saasServiceHealth,health);assert.equal(c.state.saasError,'current');
  assert.equal(c.state.saasLoading,true);assert.equal(renders,0);assert.equal(c.toasts.length,0);
});

async function inventoryExecutionFixture(mode) {
  const c=await displayRecoveryFixture('inventory',mode==='execute'?'approved':'external_execution_processing_manual_reconcile');
  const card=c.displayCard;card.decided_at=new Date().toISOString();card.decided_by='merchant-A';c.state.view='product';
  c.state.saasEbayReapprovalContext=c.saasEbayRecoveryContext(card);
  c.field={value:''};c.persisted=[];c.checks=0;
  Object.assign(c,{saasServerNowMs:()=>Date.now(),saasInventoryLocationExecutionAttemptKeys:new Set(),
    saasInventoryLocationReconciliationAttemptKeys:new Set(),
    persistSaasPublishIntakeDraft:()=>c.persisted.push(c.saasCurrentListingProjectIdentity().key),
    runSaasPreTestFormCheck:()=>{c.checks++;}});
  c.document.querySelector=selector=>selector.includes('merchant_location_key')?c.field:null;
  installActualViewNavigation(c);
  vm.runInContext(['isSaasFreshApprovedInventoryLocationConfirmation','saasExactApprovedInventoryLocationConfirmation',
    'executeSaasApprovedInventoryLocation','reconcileSaasInventoryLocation'].map(extract).join('\n'),c);
  c.invoke=()=>mode==='execute'?c.executeSaasApprovedInventoryLocation():c.reconcileSaasInventoryLocation(card.confirmation_id);
  c.refreshSaasState=async options=>{if(!options?.saasRequestIsCurrent||options.saasRequestIsCurrent()) c.state.saasConfirmations=[{obsolete:true}];};
  c.fetch=async(url,options)=>{
    c.calls.push({url,method:options.method});return {ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>({
      [mode==='execute'?'inventory_location_execution':'inventory_location_reconciliation']:{
        status:'inventory_location_created',action_type:card.action_type,company_id:card.company_id,store_id:card.store_id,
        confirmation_id:card.confirmation_id,merchant_location_key:card.item.merchant_location_key,location_write_completed:true,
        public_listing_created:false,secret_exposed:false,reconciled_from_provider_read:true,writes_to_ebay:false}})};
  };
  return c;
}

for(const mode of ['execute','reconcile']) {
  test(`inventory ${mode} actual exact approved normal control fills once`,async()=>{
    const c=await inventoryExecutionFixture(mode);assert.equal(await c.invoke(),true);
    assert.equal(c.calls.length,1);assert.equal(c.field.value,'warehouse-a');assert.equal(c.persisted.length,1);
    assert.equal(c.checks,1);assert.equal(c.state.saasLoading,false);
    await c.invoke();assert.equal(c.calls.length,1,'An accepted attempt must not be retried');
  });
  for(const phase of ['post','refresh']) for(const outcome of ['success','error'])
  for(const selection of ['same-id-new-object','new-project','view-ABA'])
  test(`inventory ${mode} old ${phase} ${outcome} cannot fill or persist ${selection}`,async()=>{
    const c=await inventoryExecutionFixture(mode);let entered,release;
    const held=new Promise(resolve=>{entered=resolve;}),send=c.fetch,refresh=c.refreshSaasState;
    const errorResponse=()=>({ok:false,status:409,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'old-failure'})});
    if(phase==='post') c.fetch=async(...args)=>{const response=await send(...args);
      await new Promise(resolve=>{release=resolve;entered();});return outcome==='success'?response:errorResponse();};
    else {
      c.fetch=async(...args)=>{await send(...args);return errorResponse();};
      c.refreshSaasState=async options=>{await new Promise(resolve=>{release=resolve;entered();});
        if(outcome==='error') throw new Error('old-refresh');await refresh(options);};
    }
    const pending=c.invoke();await held;
    if(selection==='same-id-new-object') c.state.saasEbayReapprovalContext={...c.state.saasEbayReapprovalContext};
    else if(selection==='new-project') {
      c.saasCurrentListingProjectIdentity=()=>({key:'project-Y'});c.state.saasMerchantProjectStatusRequestGeneration=1;
    } else {c.setView('activity');c.setView('product');}
    c.saasEbayStoreRequestGuard('store-A',{interaction:true}).beginLoading?.();
    const cards=[...c.state.saasConfirmations],values={merchant_location_key:'CURRENT'};
    c.saasPendingPublishIntakeFormValues=values;c.field.value='CURRENT';c.state.saasConfirmations=cards;
    c.state.saasError='current';c.state.saasLoading=true;c.toasts=[];c.actions=[];let renders=0;
    c.renderSaasBackendPanel=()=>{renders++;};
    release();await pending;
    assert.equal(c.field.value,'CURRENT');assert.equal(c.saasPendingPublishIntakeFormValues,values);
    assert.equal(c.persisted.length,0);assert.equal(c.checks,0);assert.equal(c.state.saasConfirmations,cards);
    assert.equal(c.state.saasError,'current');assert.equal(c.state.saasLoading,true);assert.equal(c.state.view,'product');
    assert.equal(c.toasts.length,0);assert.equal(renders,0);assert.equal(c.calls.length,1);
    const attempts=mode==='execute'?c.saasInventoryLocationExecutionAttemptKeys:c.saasInventoryLocationReconciliationAttemptKeys;
    assert.equal(attempts.size,1,'UI obsolescence must retain the original attempt key');
  });
}

function installActualRecentProjectNavigation(c) {
  const reports={
    X:{key:'project-A',sku:'SKU-A',product:'Product X',model_generated:true},
    Y:{key:'project-Y',sku:'SKU-Y',product:'Product Y',model_generated:true}};
  Object.assign(c,{invalidateSaasListingAiGenerationContext:()=>{},resetSaasListingPublishEvidenceForNewProject:()=>{},
    resetSaasBulkWorkspaceForListingProject:()=>{},stashSaasCurrentListingProjectDraft:()=>{},setSaasAiCeoTaskContextState:()=>{},
    saasRecentProductWorkflowTasks:()=>['X','Y'].map(task_id=>({task_id,store_id:'store-A'})),
    saasRecentProductTaskReports:task=>[reports[task.task_id]],saasRecentProductTaskReport:task=>reports[task.task_id],
    saasListingDraftFromReport:report=>report,saasListingDraftHasConcreteProduct:draft=>Boolean(draft?.sku),
    restoreSaasListingComposerDraftFromBackendReports:()=>{},detachedSaasListingProjectDraft:()=>null,
    saasTimestampMillis:()=>0,saasReportSummary:()=>'',commitSaasActiveListingProjectContext:()=>{},saasWorkflowProductLabel:()=>'',
    saasListingProjectIdentityFromReport:report=>({key:report.key})});
  c.state.saasListingComposerDraft=reports.X;
  c.saasCurrentListingProjectIdentity=(draft=c.state.saasListingComposerDraft)=>({key:draft.key});
  c.saasListingDraftAuthoritativeSku=()=>c.state.saasListingComposerDraft.sku;
  vm.runInContext(['resetSaasListingProjectTransientState','openSaasRecentProductTask'].map(extract).join('\n'),c);
  return reports;
}

test('actual recent-project open clears recovery selection and returning does not revive it',async()=>{
  const c=interactionFixture('legacy'),reports=installActualRecentProjectNavigation(c);
  const history=JSON.stringify(c.state.saasConfirmations);
  await c.handleSaasEbayExecutionRecovery('old','prepare');assert(c.state.saasEbayReapprovalContext);
  assert.equal(c.openSaasRecentProductTask('Y'),true);assert.equal(c.state.saasEbayReapprovalContext,null);
  assert.equal(c.saasEbayReapprovalId('publish_listing',{listing:{sku:'SKU-Y'},listing_project_identity:{key:'project-Y'}}),'');
  assert.equal(c.openSaasRecentProductTask('X'),true);assert.equal(c.state.saasEbayReapprovalContext,null);
  assert.equal(JSON.stringify(c.state.saasConfirmations),history);assert.equal(c.calls.length,0);
  c.openSaasRecentProductTask('Y');assert.equal(await c.handleSaasEbayExecutionRecovery('old','prepare'),true);
  assert.equal(c.state.saasListingComposerDraft,reports.X);assert.equal(c.state.saasEbayReapprovalContext.confirmationId,'old');
});

async function approvalInteractionFixture(kind) {
  const c=await displayRecoveryFixture(kind,'pending');delete c.displayCard.execution_recovery;
  c.state.view='confirm';c.refreshes=0;c.renders=0;c.toasts=[];
  Object.assign(c,{isSaasUniqueCurrentReadOnlySyncConfirmation:()=>false,saasServerNowMs:()=>Date.now(),
    renderSaasBackendPanel:()=>{c.renders++;}});
  installActualViewNavigation(c);
  vm.runInContext(['approveFirstSaasConfirmation','saasExactApprovedInventoryLocationConfirmation',
    'isSaasFreshApprovedInventoryLocationConfirmation'].map(extract).join('\n'),c);
  c.fetch=async(url,options)=>{
    const stage=url.split('/').at(-1);c.calls.push({url,method:options.method,stage});
    const payload=stage==='preflight'?{preflight:{status:'ready_for_platform_adapter'},publish_readiness:{marker:'old'}}:
      stage==='execute'?{execution:{status:'completed'}}:{};
    return {ok:true,status:201,headers:{get:()=> 'application/json'},json:async()=>payload};
  };
  c.refreshSaasState=async options=>{
    c.refreshes++;
    if(options?.saasRequestIsCurrent&&!options.saasRequestIsCurrent()) return;
    c.displayCard.status='approved';c.displayCard.decided_at=new Date().toISOString();c.displayCard.decided_by='merchant-A';
    c.state.saasConfirmations=[...(c.cleanupSource?[c.cleanupSource]:[]),c.displayCard];
    c.state.saasLastPublishReadiness={marker:'old-refreshed'};await c.verifyCards();
  };
  c.invoke=()=>c.approveFirstSaasConfirmation(c.displayCard.confirmation_id);
  return c;
}

for(const kind of ['legacy','draft','controlled','cleanup','inventory']) {
  test(`${kind} exact approval normal interaction keeps its original explicit flow`,async()=>{
    const c=await approvalInteractionFixture(kind);await c.invoke();
    assert.deepEqual(c.calls.map(call=>call.stage),kind==='inventory'?['decision']:['decision','preflight','execute']);
    assert.equal(c.refreshes,1);assert.equal(c.toasts.length,1);assert.doesNotMatch(c.toasts[0],/失败/);
    if(kind==='inventory') assert.match(c.toasts[0],/再点一次/);
  });
  const phases=kind==='inventory'?['decision','refresh']:['decision','preflight','execute','refresh','blocked-refresh'];
  for(const phase of phases) for(const outcome of ['success','error'])
  for(const transition of ['new-project','same-id-new-selection','view-ABA'])
  test(`${kind} old approval ${phase} ${outcome} cannot continue or publish after ${transition}`,async()=>{
    const c=await approvalInteractionFixture(kind);let entered,release;
    const held=new Promise(resolve=>{entered=resolve;}),send=c.fetch,refresh=c.refreshSaasState;
    const failure=()=>({ok:false,status:409,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'old-failure'})});
    if(phase.endsWith('refresh')) {
      if(phase==='blocked-refresh') c.fetch=async(...args)=>{
        const response=await send(...args);
        return args[0].endsWith('/preflight')?{...response,json:async()=>({preflight:{status:'blocked',missing_fields:['old-fact']}})}:response;
      };
      c.refreshSaasState=async options=>{
        await new Promise(resolve=>{release=resolve;entered();});
        if(outcome==='error') throw new Error('old-refresh-failed');await refresh(options);
      };
    } else c.fetch=async(...args)=>{
      const response=await send(...args);
      if(!args[0].endsWith('/'+phase)) return response;
      await new Promise(resolve=>{release=resolve;entered();});return outcome==='success'?response:failure();
    };
    const pending=c.invoke();await held;const sent=c.calls.length;
    if(transition==='new-project') {c.saasCurrentListingProjectIdentity=()=>({key:'project-Y'});c.state.saasMerchantProjectStatusRequestGeneration=1;}
    else if(transition==='same-id-new-selection') c.state.saasEbayReapprovalContext=c.saasEbayRecoveryContext(c.displayCard);
    else {c.setView('product');c.setView('confirm');}
    c.saasEbayStoreRequestGuard('store-A',{interaction:true}).beginLoading?.();
    const current={cards:[...c.state.saasConfirmations],readiness:{marker:'current'},preflight:[{marker:'current'}]};
    Object.assign(c.state,{saasConfirmations:current.cards,saasLastPublishReadiness:current.readiness,
      saasPreflightResults:current.preflight,saasError:'current',saasLoading:true});
    c.toasts=[];c.renders=0;
    release();await pending;
    assert.equal(c.calls.length,sent,'A stale decision/preflight must not send its next request');
    assert.equal(c.calls.filter(call=>call.stage==='execute').length,phase==='execute'||phase==='refresh'&&kind!=='inventory'?1:0);
    assert.equal(c.state.saasConfirmations,current.cards);assert.equal(c.state.saasLastPublishReadiness,current.readiness);
    assert.equal(c.state.saasPreflightResults,current.preflight);assert.equal(c.state.saasError,'current');
    assert.equal(c.state.saasLoading,true);assert.equal(c.toasts.length,0);assert.equal(c.renders,0);
  });
}

for(const mode of ['legacy','draft','controlled','inventory','cleanup','readonly','inventory-execute','inventory-reconcile'])
for(const outcome of ['success','error'])
for(const transition of ['view-ABA','project-reset','same-id-new-selection'])
test(`${mode} obsolete ${outcome} releases only its own loading after ${transition} without new work`,async()=>{
  const c=mode.startsWith('inventory-')?await inventoryExecutionFixture(mode.slice(10)):interactionFixture(mode);
  const invoke=c.invoke||c.prepare;
  if(transition==='project-reset') installActualRecentProjectNavigation(c);
  let entered,release;const held=new Promise(resolve=>{entered=resolve;}),send=c.fetch;
  c.fetch=async(...args)=>{const response=await send(...args);await new Promise(resolve=>{release=resolve;entered();});
    return outcome==='success'?response:{ok:false,status:409,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'old'})};};
  const pending=invoke();await held;assert.equal(c.state.saasLoading,true);
  if(transition==='view-ABA') {c.setView('connect');c.setView('product');}
  else if(transition==='project-reset') assert.equal(c.openSaasRecentProductTask('Y'),true);
  else c.state.saasEbayReapprovalContext=c.saasEbayRecoveryContext(c.state.saasConfirmations.at(-1));
  const cards=c.state.saasConfirmations,context=c.state.saasEbayReapprovalContext;
  c.state.saasError='current';c.toasts=[];
  release();await pending;
  assert.equal(c.state.saasLoading,false);assert.equal(c.state.saasConfirmations,cards);
  assert.equal(c.state.saasEbayReapprovalContext,context);assert.equal(c.state.saasError,'current');
  assert.equal(c.toasts.length,0);assert.equal(c.calls.length,1);
});

for(const owner of ['ebay-request','refresh','settings','ai-generation']) for(const outcome of ['success','error'])
test(`obsolete loading never releases newer ${owner} on ${outcome}`,async()=>{
  for(const mode of ['legacy','draft','controlled','inventory','cleanup','readonly','inventory-execute','inventory-reconcile']) {
    const c=mode.startsWith('inventory-')?await inventoryExecutionFixture(mode.slice(10)):interactionFixture(mode);
    Object.assign(c,{saasStateRefreshGeneration:0,saasSettingsActionRequest:null,saasListingAiGenerationRequest:null});
    let entered,release;const held=new Promise(resolve=>{entered=resolve;}),send=c.fetch;
    c.fetch=async(...args)=>{const response=await send(...args);await new Promise(resolve=>{release=resolve;entered();});
      return outcome==='success'?response:{ok:false,status:409,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'old'})};};
    const pending=(c.invoke||c.prepare)();await held;c.setView('connect');c.setView('product');
    if(owner==='ebay-request') c.saasEbayStoreRequestGuard('store-A',{interaction:true}).beginLoading?.();
    else if(owner==='refresh') c.saasStateRefreshGeneration++;
    else if(owner==='settings') c.saasSettingsActionRequest={epoch:1,refreshGeneration:0};
    else c.saasListingAiGenerationRequest={contextKey:'project-A',epoch:1,refreshGeneration:0};
    c.state.saasLoading=true;c.toasts=[];let renders=0;c.renderSaasBackendPanel=()=>{renders++;};
    release();await pending;
    assert.equal(c.state.saasLoading,true,`${mode} cannot release ${owner}`);
    assert.equal(c.toasts.length,0);assert.equal(renders,0);assert.equal(c.calls.length,1);
  }
});

for(const outcome of ['success','error']) test(`actual parent refresh retires its obsolete ${outcome} loading without navigation`,async()=>{
  const c=interactionFixture('legacy');let release;
  Object.assign(c,{saasStateRefreshGeneration:0,hasSaasProtectedSessionCandidate:()=>false,saasAccountStorageAliases:()=>[],
    normalizeSaasCeoCommand:value=>value,normalizeSaasAiCeoLatestTurn:value=>value,shouldKeepSaasAiCeoThreadTurn:()=>true,
    resetSaasProtectedWorkbenchState:()=>{c.state.saasLastPublishReadiness='obsolete-reset';},
    isSaasUnrecoverableSessionError:()=>false,syncAppStartVisibleShellGuard:()=>{},syncSaasPublicMvpMode:()=>{},
    renderGlobalLoopWorkbench:()=>{},renderStoreContext:()=>{},activeSaasRefreshView:()=> 'product'});
  c.fetch=async()=>new Promise(resolve=>{release=()=>resolve({ok:outcome==='success',status:outcome==='success'?200:500,
    headers:{get:()=> 'application/json'},json:async()=>({marker:'old'}),text:async()=>JSON.stringify({error:'old'})});});
  vm.runInContext(extract('refreshSaasState'),c);
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});
  const pending=c.refreshSaasState({silent:true,saasRequestIsCurrent:guard});
  c.setView('connect');c.state.saasError='current';c.toasts=[];
  release();await pending;
  assert.equal(c.state.saasLoading,false);assert.equal(c.state.view,'connect');assert.equal(c.state.saasError,'current');
  assert.equal(c.toasts.length,0);assert.notEqual(c.state.saasLastPublishReadiness,'obsolete-reset');
});

async function protectedRefreshFixture() {
  const c=await displayRecoveryFixture('legacy','pending');delete c.displayCard.execution_recovery;
  c.state.view='product';c.toasts=[];c.renderedLoading=[];installActualViewNavigation(c);
  Object.assign(c,{saasStateRefreshGeneration:0,saasSettingsActionEpoch:0,saasSettingsActionRequest:null,
    saasListingAiGenerationEpoch:0,saasListingAiGenerationRequest:null,saasListingAiGenerationInFlight:new Map(),
    hasSaasProtectedSessionCandidate:()=>true,hasSaasProtectedBackendState:()=>true,
    saasAccountStorageAliases:()=>['merchant-A'],ensureSaasDemoStoreAndConnection:async()=>c.store,
    normalizeSaasCeoCommand:value=>value,normalizeSaasAiCeoLatestTurn:value=>value,
    shouldKeepSaasAiCeoThreadTurn:()=>true,retainSaasAiCeoRecentThread:value=>value,
    saasAiCeoHistoryRequestContext:()=>({}),isCurrentSaasAiCeoHistoryRequest:()=>true,
    hydrateSaasProtectedStateFromCache:()=>false,fetchSaasMerchantBillingUsage:async()=>({}),
    merchantSafeSaasBillingPlan:value=>value,merchantSafeSaasOAuthRequests:value=>value||[],
    consumeSaasStartupRequestedView:()=> 'product',activeSaasRefreshView:()=> 'product',
    saasListingCloudRecord:()=>null,saasMerchantProjectRouteId:()=>'',
    reconcileSaasPendingNewListingProjectRequestFromReports:()=>false,
    hydrateSaasCeoCommandFromBackend:async()=>null,refreshSaasMerchantProjectStatus:async()=>{},
    isSaasUnrecoverableSessionError:()=>false,isProtectedSaasAppRoute:()=>false,
    saasListingAiGenerationContextKey:()=> 'project-A',
    renderSaasBackendPanel:()=>c.renderedLoading.push({ready:c.state.saasProtectedStateReady,loading:c.state.saasLoading}),
  });
  for(const name of ['loadSaasAiCeoThread','loadSaasSourceRecords','loadSaasMerchantFeedback',
    'sanitizeSaasDetachedListingProjectDraftsSnapshot']) c[name]=()=>[];
  for(const name of ['newestSaasCeoCommand','backendSaasCeoCommandFromPayload','loadSaasLastCeoCommand',
    'syncSaasAiCeoLatestTurnFromThread']) c[name]=()=>null;
  // Only unrelated hydration/storage/render plumbing is synthetic. The complete
  // refresh, its real setView and both digest verifiers run unchanged below.
  for(const name of ['syncSaasPublicMvpMode','renderStoreContext','renderGlobalLoopWorkbench',
    'renderSaasCockpitRealWorkbench','assertSaasLiveIdentityScope','syncSaasOnboardingCompletionFromBackend',
    'updateSaasAiCeoHistoryPagination','syncSaasAiCeoCloudDomState','persistSaasLastCeoCommand',
    'recordSaasCeoCommandSourceRecord','persistSaasAiCeoThread','scheduleSaasAiCeoThreadBackendSync',
    'markSaasProductFeedbackLiveIdentity','saveSaasProtectedStateSnapshot','prepareSaasProductFeedbackScopeAfterIdentity',
    'saveSaasSessionToStorage','markSaasMediaJobsAsCurrentSessionBackendEvidence',
    'pruneSaasDetachedListingProjectDraftsAgainstBackend','restoreSaasListingComposerDraftFromBackendReports',
    'restoreSaasFreshListingCloudProjection','restoreSaasExpiredListingGeneration','startSaasAiCeoCrossDeviceSync',
    'applySaasReportsToActivities','applySaasDataPacketsToActivities',
    'resumeSaasUncertainNewListingProjectRequestAfterRefresh','syncAppStartVisibleShellGuard']) c[name]=()=>{};
  c.document.documentElement.classList={remove:()=>{}};
  c.fetch=async(url,options)=>{
    c.calls.push({url,method:options.method||'GET'});
    const route=url.slice(c.state.saasApiBase.length);
    const payload=route==='/me'?{company:{company_id:'company-A'},user:{user_id:'merchant-A'},
      identity:{company_id:'company-A',user_id:'merchant-A'}}:
      route==='/stores'?{stores:[c.store]}:
      route==='/confirmations?limit=40'?{confirmations:[c.displayCard]}:{};
    return {ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>payload};
  };
  c.optionalSaasFetchFast=async(route,fallback)=>({...fallback,...await c.saasFetch(route)});
  vm.runInContext(['refreshSaasState','saasSettingsActionScope','isCurrentSaasSettingsAction',
    'beginSaasSettingsAction'].map(extract).join('\n'),c);
  c.startNewOwner=owner=>{
    if(owner==='settings') {
      const request=c.beginSaasSettingsAction();assert(request,'Real settings admission must be available after core refresh');
      c.state.saasLoading=true;return request;
    }
    // Execute the real AI ownership block, without invoking any model/backend.
    const generation=extract('generateSaasListingDraftFromCurrentProject');
    const start=generation.indexOf('  const generationRequest = {');
    const end=generation.indexOf('  state.saasListingAiGenerationStatus = "running";',start);
    assert(start>0&&end>start);
    return vm.runInContext(`(()=>{const draft=state.saasListingComposerDraft;${generation.slice(start,end)}return generationRequest;})()`,c);
  };
  return c;
}

for(const phase of ['core','extended']) for(const owner of phase==='core'?['ai']:['ai','settings'])
for(const outcome of ['success','error'])
test(`actual guarded parent refresh ${phase} ${outcome} retains newer ${owner} loading in the same interaction`,async()=>{
  const c=await protectedRefreshFixture();let enterCore,releaseCore,enterExtended,releaseExtended;
  const coreHeld=new Promise(resolve=>{enterCore=resolve;}),extendedHeld=new Promise(resolve=>{enterExtended=resolve;});
  const send=c.fetch;
  c.fetch=async(...args)=>{
    const response=await send(...args),route=args[0].slice(c.state.saasApiBase.length);
    if(route==='/me') await new Promise(resolve=>{releaseCore=resolve;enterCore();});
    if(route==='/reports?limit=24') {
      await new Promise(resolve=>{releaseExtended=resolve;enterExtended();});
      if(outcome==='error') return {ok:false,status:500,headers:{get:()=> 'application/json'},
        text:async()=>JSON.stringify({error:'synthetic_extended_failure'})};
    }
    return response;
  };
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});
  const pending=c.refreshSaasState({silent:true,saasRequestIsCurrent:guard});await coreHeld;
  let newer=phase==='core'?c.startNewOwner(owner):null;
  releaseCore();await extendedHeld;
  const coreLoading=c.state.saasLoading;
  if(phase==='extended') {assert.equal(coreLoading,false,'Core retires its own loading before new work');newer=c.startNewOwner(owner);}
  assert.equal(guard(),true,'This regression must not rely on interaction obsolescence');
  releaseExtended();await pending;
  if(phase==='core') assert.equal(coreLoading,true,'Core completion cannot release the AI owner');
  assert.equal(c.state.saasLoading,true,'Extended/finally completion cannot release the newer owner');
  assert.equal(owner==='ai'?c.saasListingAiGenerationRequest:c.saasSettingsActionRequest,newer);
  assert.equal(guard(),true);assert.equal(c.state.view,'product');assert.equal(c.toasts.length,0);
  assert.equal(c.calls.filter(call=>call.url.endsWith('/reports?limit=24')).length,1);
  if(outcome==='error') assert.match(c.state.saasError,/synthetic_extended_failure/);
  else assert.equal(c.state.saasError,'','Full refresh must reach the real successful completion');
});

for(const guarded of [false,true]) for(const outcome of ['success','error'])
test(`actual ${guarded?'guarded':'ordinary'} protected refresh ${outcome} with no newer owner retires loading`,async()=>{
  const c=await protectedRefreshFixture(),send=c.fetch;
  if(outcome==='error') c.fetch=async(...args)=>args[0].endsWith('/reports?limit=24')?
    {ok:false,status:500,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify({error:'synthetic_extended_failure'})}:send(...args);
  const options={silent:true};if(guarded) options.saasRequestIsCurrent=c.saasEbayStoreRequestGuard('store-A',{interaction:true});
  await c.refreshSaasState(options);
  assert.equal(c.state.saasLoading,false);assert.equal(c.state.saasProtectedStateReady,true);
  if(outcome==='error') assert.match(c.state.saasError,/synthetic_extended_failure/);
  else assert.equal(c.state.saasError,'');
});

function installActualSettingsRendering(c) {
  // The DOM boundary stores the real rendered button attributes and listeners;
  // navigation, settings layout/account markup, disclosure restoration and
  // store-switch binding below are the unchanged application functions.
  const settings={id:'view-connect',dataset:{title:'设置'},buttons:[],elements:[],markup:'',
    classList:{toggle:()=>{}},contains(element) {return this.elements.includes(element);},querySelectorAll(selector) {
      if(selector.startsWith('#')) return this.elements.filter(element=>element.attributes.id===selector.slice(1));
      if(selector.startsWith('.')) return this.elements.filter(element=>(element.attributes.class||'').split(/\s+/).includes(selector.slice(1)));
      const attribute=selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      return attribute?this.elements.filter(button=>Object.hasOwn(button.attributes,attribute[1])&&
        (attribute[2]===undefined||button.attributes[attribute[1]]===attribute[2])):[];
    },querySelector(selector) {return this.querySelectorAll(selector)[0]||null;}};
  Object.defineProperty(settings,'innerHTML',{get:()=>settings.markup,set:html=>{
    if(settings.contains(c.document.activeElement)) c.document.activeElement=c.document.body;
    const element=(tag,raw,text='')=>{
      const attributes=Object.fromEntries([...raw.matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(([,key,value])=>[key,value??'']));
      const dataset=Object.fromEntries(Object.entries(attributes).filter(([key])=>key.startsWith('data-'))
        .map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()),value]));
      const listeners={},node={tagName:tag.toUpperCase(),attributes,dataset,disabled:Object.hasOwn(attributes,'disabled'),textContent:text,
        value:attributes.value||'',open:Object.hasOwn(attributes,'open'),
        addEventListener:(name,listener)=>{listeners[name]=listener;},click:()=>listeners.click?.(),
        focus:()=>{c.document.activeElement=node;},querySelector:()=>null};
      return node;
    };
    settings.markup=html;
    settings.buttons=[...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].map(([,raw,text])=>element('button',raw,text));
    const inputs=[...html.matchAll(/<input\b([^>]*)>/g)].map(([,raw])=>element('input',raw));
    const selects=[...html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)].map(([,raw,body])=>{
      const node=element('select',raw);
      node.options=[...body.matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)].map(([,attributes,text])=>element('option',attributes,text));
      node.value=(node.options.find(option=>Object.hasOwn(option.attributes,'selected'))||node.options[0])?.value||'';
      return node;
    });
    const details=[...html.matchAll(/<details\b([^>]*)>/g)].map(([,raw])=>element('details',raw));
    settings.elements=[...settings.buttons,...inputs,...selects,...details];
  }});
  const switchEvents=[],select={options:[{value:'saas:store-A'},{value:'saas:store-B'}],value:'saas:store-A',
    dispatchEvent:event=>switchEvents.push({type:event.type,value:select.value})};
  const originalQuery=c.document.querySelector;
  c.document.querySelector=selector=>selector==='#view-connect'?settings:selector==='#storeSwitch'?select:settings.querySelector(selector)||originalQuery(selector);
  c.document.body=c.document.body||{};c.document.activeElement=c.document.body;
  settings.ownerDocument=c.document;
  Object.assign(c.state,{saasConnected:true,saasSettingsTab:'account',saasStores:[c.store,
    {store_id:'store-B',store_name:'Second synthetic store',marketplace:'EBAY_GB'}],saasConnections:[]});
  Object.assign(c,{Event,saasSettingsAccountDisclosureSnapshots:new WeakMap(),
    renderSaasProtectedStateLoadingView:()=>false,
    saasMerchantWorkbenchContext:()=>({store:c.store,connection:{status:'connected'}}),
    saasCurrentAccountSummary:()=>({connected:true,displayName:'Synthetic merchant',email:'fixture@example.invalid'}),
    saasSettingsAccountStoreStatus:()=>({label:'已连接',tone:'neutral',detail:'Synthetic store status'}),
    saasKnownStoreCandidates:stores=>stores,saasConnectionForStore:()=>({status:'connected'}),
    saasStoreDisplayName:store=>store?.store_name||store?.store_id||'待连接 eBay 店铺',saasMerchantSafeSettingsText:(value,fallback)=>value||fallback,
    safeSaasBrowserSessionsForDisplay:()=>[],isSaasAuthorizedConnectionStatus:status=>status==='connected',
    isSaasEbayUnpublishedDraftAuthorized:()=>false,bindSaasBrowserSessionControls:()=>{},
    trustedJiejingHtml:html=>html,setJiejingTrustedHtml:(element,html)=>{element.innerHTML=html;}});
  c.window.JiejingSettingsPanels={}; // Already loaded; no script/network bootstrap.
  for(const name of ['renderSaasSettingsAccountAccessPanel','renderSaasSettingsAccountPanel','renderSaasAccountHealthPanel',
    'renderSaasBrowserSessionsPanel','renderSaasMerchantModelProviderPanel','renderSaasSettingsDataPanel',
    'renderSaasMerchantPermissionPanel','renderSaasMerchantDomesticPaymentPanel','renderSaasMerchantMediaCreditsPanel',
    'renderSaasMerchantBillingPlainSummaryPanel','renderSaasMerchantBillingEntitlementPathPanel',
    'renderSaasMerchantBillingCustomerTrustPanel','renderSaasMerchantPricingModelPanel',
    'renderSaasMerchantBillingContinuityPanel','renderSaasMerchantSecurityBoundaryPanel']) c[name]=()=>'';
  vm.runInContext(['saasSettingsAccountDisclosureScope','captureSaasSettingsAccountDisclosureState',
    'restoreSaasSettingsAccountDisclosureState','bindSaasSettingsAccountControls','saasSettingsAccountOnboardingMatchesStore',
    'renderSaasSettingsAccountPolicies','renderSaasSettingsAccountWorkspace','renderSaasSettingsSectionGroup',
    'saasSettingsTabDefinitions','renderSaasSettingsCleanLayout','renderSaasConnectCenter','renderConnect'].map(extract).join('\n'),c);
  return {settings,switchEvents,refresh:()=>settings.querySelector('[data-saas-action="refresh"]'),
    switchStore:()=>settings.querySelector('[data-saas-account-store="store-B"]')};
}

async function assertVisibleSettingsAfterObsoleteRequest(mode,outcome,newOwner='') {
  const c=mode.startsWith('inventory-')?await inventoryExecutionFixture(mode.slice(10)):interactionFixture(mode);
  const controls=installActualSettingsRendering(c);
  Object.assign(c,{saasStateRefreshGeneration:0,saasSettingsActionRequest:null,saasListingAiGenerationRequest:null});
  let entered,release;const held=new Promise(resolve=>{entered=resolve;}),send=c.fetch;
  c.fetch=async(...args)=>{const response=await send(...args);await new Promise(resolve=>{release=resolve;entered();});
    return outcome==='success'?response:{ok:false,status:409,headers:{get:()=> 'application/json'},
      text:async()=>JSON.stringify({error:'obsolete-request-failed'})};};
  const pending=(c.invoke||c.prepare)();await held;c.setView('connect');
  assert.equal(c.state.view,'connect');assert.equal(c.pageTitle.textContent,'设置');
  assert.equal(controls.refresh().disabled,true);assert.equal(controls.refresh().textContent,'正在刷新…');
  assert.equal(controls.switchStore().disabled,true);controls.switchStore().click();assert.equal(controls.switchEvents.length,0);
  if(newOwner==='ebay-request') c.saasEbayStoreRequestGuard('store-A',{interaction:true}).beginLoading();
  else if(newOwner==='refresh') c.saasStateRefreshGeneration++;
  else if(newOwner==='settings') c.saasSettingsActionRequest={epoch:1,refreshGeneration:0};
  else if(newOwner==='ai-generation') c.saasListingAiGenerationRequest={contextKey:'project-A',epoch:1,refreshGeneration:0};
  const heldRefresh=controls.refresh(),heldSwitch=controls.switchStore();
  const cards=c.state.saasConfirmations,readiness={marker:'current-settings'};
  c.state.saasLastPublishReadiness=readiness;c.state.saasError='current-settings';c.toasts=[];
  release();await pending;
  assert.equal(c.state.saasLoading,Boolean(newOwner));assert.equal(c.state.view,'connect');assert.equal(c.pageTitle.textContent,'设置');
  assert.equal(c.state.saasConfirmations,cards);assert.equal(c.state.saasLastPublishReadiness,readiness);
  assert.equal(c.state.saasError,'current-settings');assert.equal(c.toasts.length,0);assert.equal(c.calls.length,1);
  if(newOwner) {
    assert.equal(controls.refresh(),heldRefresh,'An obsolete completion must not rebuild a newer owner\'s controls');
    assert.equal(controls.switchStore(),heldSwitch);assert.equal(controls.refresh().disabled,true);
    assert.equal(controls.refresh().textContent,'正在刷新…');assert.equal(controls.switchStore().disabled,true);
    controls.switchStore().click();assert.equal(controls.switchEvents.length,0);
  } else {
    assert.equal(controls.refresh().disabled,false,'Settled own loading must repaint the visible refresh control');
    assert.equal(controls.refresh().textContent,'刷新状态');assert.equal(controls.switchStore().disabled,false);
    controls.switchStore().click();assert.deepEqual(controls.switchEvents,[{type:'change',value:'saas:store-B'}]);
  }
  assert.equal(c.calls.length,1,'The control check does not invoke a store/backend operation');
}

test('settled obsolete prepare repaints real visible settings controls without publishing old data',
  ()=>assertVisibleSettingsAfterObsoleteRequest('legacy','success'));
for(const mode of ['legacy','draft','controlled','inventory','cleanup','readonly','inventory-execute','inventory-reconcile'])
for(const outcome of ['success','error']) {
  if(mode==='legacy'&&outcome==='success') continue; // Exact original tracer above.
  test(`${mode} obsolete ${outcome} repaints visible settings controls without stale publication`,
    ()=>assertVisibleSettingsAfterObsoleteRequest(mode,outcome));
}
for(const owner of ['ebay-request','refresh','settings','ai-generation']) for(const outcome of ['success','error'])
test(`obsolete ${outcome} keeps visible settings controls disabled for newer ${owner}`,
  ()=>assertVisibleSettingsAfterObsoleteRequest('legacy',outcome,owner));

function installActualModelSettingsRendering(c) {
  const controls=installActualSettingsRendering(c);
  const providers=[{provider_key:'fixture-a',label:'Synthetic A',supported_live_adapter:true,default_model:'saved-model',default_base_url:'https://a.invalid'},
    {provider_key:'fixture-b',label:'Synthetic B',supported_live_adapter:true,default_model:'other-model',default_base_url:'https://b.invalid'}];
  Object.assign(c,{saasModelProviderRows:()=>providers,saasActiveModelSecretRef:()=>null,
    isSaasMerchantModelConfigured:()=>false,isSaasModelConfigured:()=>true,
    saasPlatformTrialModelState:()=>({allowed:true}),saasModelConnectionAttemptState:()=>({state:'ready',canRetry:true}),
    saasPrimaryTextAiState:()=>({}),saasImageRecognitionState:()=>({}),saasPublicSearchState:()=>({}),saasMediaGenerationState:()=>({})});
  vm.runInContext(extract('renderSaasMerchantModelProviderPanel'),c);
  c.state.saasSettingsTab='model';
  return controls;
}

async function assertModelDraftAfterObsoleteRequest(outcome,newOwner='') {
  const c=interactionFixture('legacy'),controls=installActualModelSettingsRendering(c);
  Object.assign(c,{saasStateRefreshGeneration:0,saasSettingsActionRequest:null,saasListingAiGenerationRequest:null});
  let entered,release;const held=new Promise(resolve=>{entered=resolve;}),send=c.fetch;
  c.fetch=async(...args)=>{const response=await send(...args);await new Promise(resolve=>{release=resolve;entered();});
    return outcome==='success'?response:{ok:false,status:409,headers:{get:()=> 'application/json'},
      text:async()=>JSON.stringify({error:'obsolete-request-failed'})};};
  const pending=c.prepare();await held;c.setView('connect');
  const fields=['saas-model-provider','saas-model-model','saas-model-api-key'].map(id=>controls.settings.querySelector(`#${id}`));
  assert(fields.every(Boolean),'Actual model renderer must provide all three editable fields');
  assert.equal(controls.settings.querySelector('[data-saas-action="save-model-api-key"]').disabled,true);
  const draftValues=['fixture-b','unsaved-synthetic-model','synthetic-input-only-not-a-credential'];
  fields.forEach((field,index)=>{field.value=draftValues[index];});fields[2].focus();
  const details=controls.settings.querySelector('.saas-model-config-details');details.open=false;
  const cards=c.state.saasConfirmations,readiness={marker:'current-model-settings'};
  c.state.saasLastPublishReadiness=readiness;c.state.saasError='current-model-settings';c.toasts=[];
  const forbiddenStorage={setItem:()=>assert.fail('An owned loading release must not persist model input')};
  c.localStorage=forbiddenStorage;c.sessionStorage=forbiddenStorage;
  if(newOwner==='ebay-request') c.saasEbayStoreRequestGuard('store-A',{interaction:true}).beginLoading();
  else if(newOwner==='refresh') c.saasStateRefreshGeneration++;
  else if(newOwner==='settings') c.saasSettingsActionRequest={epoch:1,refreshGeneration:0};
  else if(newOwner==='ai-generation') c.saasListingAiGenerationRequest={contextKey:'project-A',epoch:1,refreshGeneration:0};
  release();await pending;
  assert.equal(c.state.saasLoading,Boolean(newOwner));assert.equal(c.state.saasSettingsTab,'model');
  assert.equal(c.state.saasConfirmations,cards);assert.equal(c.state.saasLastPublishReadiness,readiness);
  assert.equal(c.state.saasError,'current-model-settings');assert.equal(c.toasts.length,0);assert.equal(c.calls.length,1);
  assert.ok(fields.every(field=>controls.settings.querySelector(`#${field.attributes.id}`)===field),
    'Retiring loading must not replace actual edited model form nodes');
  assert.ok(fields.every((field,index)=>field.value===draftValues[index]),'Unsaved model values stay only in their existing DOM nodes');
  assert.ok(c.document.activeElement===fields[2],'Focused input remains the same connected DOM node');
  assert.ok(controls.settings.querySelector('.saas-model-config-details')===details&&!details.open,'Current disclosure is unchanged');
  assert.equal(controls.settings.querySelector('[data-saas-action="save-model-api-key"]').disabled,Boolean(newOwner));
  assert.ok(!JSON.stringify(c.state).includes(draftValues[2]),'Input is not copied to application state');
  assert.ok(!JSON.stringify(c.calls).includes(draftValues[2]),'Input is not transmitted by stale completion');
}
test('obsolete own completion preserves actual model draft DOM, selection and focus without persistence',
  ()=>assertModelDraftAfterObsoleteRequest('success'));
test('obsolete failed completion preserves actual model draft DOM, selection and focus without persistence',
  ()=>assertModelDraftAfterObsoleteRequest('error'));
for(const owner of ['ebay-request','refresh','settings','ai-generation']) for(const outcome of ['success','error'])
test(`obsolete ${outcome} preserves actual model draft and loading for newer ${owner}`,
  ()=>assertModelDraftAfterObsoleteRequest(outcome,owner));

function settingsControlFixture(tab) {
  const c=interactionFixture('legacy'),controls=installActualModelSettingsRendering(c);
  const ctx={store:c.store,connection:{status:'connected'},hasPacket:true,missingKeys:[],packetBody:{}};
  const billing={entitlementActive:true,previewEntitlement:false},domestic={online:true},proof={ready:false};
  const model={state:'ready',canRetry:true};
  const clock={now:Date.parse('2026-10-15T12:00:00Z')};
  Object.assign(c,{Date:class extends Date {static now(){return clock.now;}},
    saasMerchantWorkbenchContext:()=>ctx,saasCurrentAccountSummary:()=>({connected:c.state.saasConnected,displayName:'Synthetic account'}),
    hasSaasProtectedSessionCandidate:()=>true,saasCurrentStoreEbayRefreshProofView:()=>proof,
    saasReadOnlyConnectionConfirmationView:()=>({status:'ready',copy:{}}),
    saasUnpublishedDraftConnectionConfirmationView:()=>({status:'ready',copy:{}}),
    saasModelConnectionAttemptState:()=>model,saasEbayPacketResourceRows:()=>[],saasSettingsDataSnapshotView:()=>({}),
    saasTimestampLabel:()=>'',saasMerchantBillingGuardrailState:()=>billing,saasMerchantDomesticBillingState:()=>domestic,
    normalizeSubscriptionPlanKey:value=>value,normalizePlanKey:value=>value,
    planDetails:{starter:{title:'Synthetic starter',price:'99'},operator:{title:'Synthetic operator',price:'199'}},
    isSaasDomesticBillingRefundConfirmation:()=>false,saasDomesticBillingDateLabel:()=>'',saasDomesticBillingStatusLabel:value=>value});
  Object.assign(c.state,{saasSettingsTab:tab,saasMerchantOnboarding:{store_id:'store-A',effective_stage:'account_review_required'},
    saasBillingUsage:{subscription:{plan_key:'starter',active_until:'2026-10-16T12:00:00Z'},media_credits:{
      contract_version:'2026-08-27-merchant-media-points-v1',available_points:10,included_points:10,purchased_points:0,promotional_points:0,
      purchase:{purchase_enabled:true,status:'available'},packs:[{key:'fixture-pack',points:10,amount_minor:100,label:'Synthetic pack'}]}}});
  vm.runInContext(['renderSaasSettingsAccountPanel','renderSaasMerchantOnboardingPanel','renderSaasSettingsDataPanel',
    'renderSaasDomesticRefundOrderActions','renderSaasMerchantMediaUsage','renderSaasMerchantDomesticPaymentPanel',
    'renderSaasMerchantMediaCreditsPanel'].map(extract).join('\n'),c);
  return {c,controls,ctx,billing,domestic,proof,model,clock};
}

function releaseActualSettingsControls(fixture) {
  const {c,controls}=fixture;
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});guard.beginLoading();c.setView('connect');
  const before=[...controls.settings.buttons];
  assert.equal(c.state.saasLoading,true);
  assert.equal(guard.releaseLoading(),true);
  assert.equal(c.state.saasLoading,false);
  assert.ok(before.every((button,index)=>controls.settings.buttons[index]===button),'Only existing controls are updated in place');
  assert.equal(c.calls.length,0,'Loading synchronization must not execute any action');
  return action=>controls.settings.querySelector(`[data-saas-action="${action}"]`);
}

for(const scenario of ['ready','disconnected','no-session','unauthorized','proof-ready'])
test(`actual account controls retain independent disabled predicates: ${scenario}`,()=>{
  const f=settingsControlFixture('account'),{c,ctx,proof}=f;
  if(scenario==='disconnected') c.state.saasConnected=false;
  if(scenario==='no-session') c.hasSaasProtectedSessionCandidate=()=>false;
  if(scenario==='unauthorized') ctx.connection.status='not_connected';
  if(scenario==='proof-ready') proof.ready=true;
  const action=releaseActualSettingsControls(f);
  assert.equal(action('refresh').disabled,scenario==='disconnected');assert.equal(action('refresh').textContent,'刷新状态');
  assert.equal(action('verify-ebay-credential-proof').disabled,['no-session','unauthorized','proof-ready'].includes(scenario));
  if(scenario==='disconnected') assert.equal(action('open-official-ebay-business-policies'),null);
  else assert.equal(action('open-official-ebay-business-policies').disabled,false);
  assert.equal(action('plan-ebay-oauth').disabled,scenario!=='unauthorized');
  assert.equal(action('plan-ebay-draft-oauth').disabled,['no-session','unauthorized'].includes(scenario));
  assert.equal(f.controls.settings.querySelector('[data-saas-account-open-health]').disabled,false);
  if(scenario!=='disconnected') assert.equal(f.controls.switchStore().disabled,false);
});

for(const scenario of ['ready','no-store','read-failed','no-packet','no-model'])
test(`actual model controls retain independent disabled predicates: ${scenario}`,()=>{
  const f=settingsControlFixture('model');
  if(scenario==='no-store') f.ctx.store=null;
  if(scenario==='read-failed') f.model.state='read_failed';
  if(scenario==='no-packet') f.ctx.hasPacket=false;
  if(scenario==='no-model') f.c.isSaasModelConfigured=()=>false;
  const action=releaseActualSettingsControls(f);
  assert.equal(action('save-model-api-key').disabled,['no-store','read-failed'].includes(scenario));
  assert.equal(action('verify-model-connection').disabled,scenario==='no-store');
  assert.equal(action('refresh-merchant-memory').disabled,scenario==='no-store');
  assert.equal(action('run-model-value-rehearsal').disabled,['no-packet','no-model'].includes(scenario));
  if(scenario==='read-failed') {assert.equal(action('refresh').disabled,false);assert.equal(action('refresh').textContent,'重新读取状态');}
});

for(const scenario of ['ready','disconnected','unauthorized'])
test(`actual data controls retain independent disabled predicates: ${scenario}`,()=>{
  const f=settingsControlFixture('data');
  if(scenario==='disconnected') f.c.state.saasConnected=false;
  if(scenario==='unauthorized') f.ctx.connection.status='not_connected';
  assert.equal(releaseActualSettingsControls(f)('sync-ebay-readonly').disabled,scenario!=='ready');
});

for(const scenario of ['ready','invalid-date','expired','expires-while-held','preview','inactive','legacy','offline'])
test(`actual subscription controls preserve eligibility and current expiry: ${scenario}`,()=>{
  const f=settingsControlFixture('billing'),{c,controls,billing,domestic,clock}=f;
  if(scenario==='invalid-date') c.state.saasBillingUsage.subscription.active_until='unknown';
  if(scenario==='expired') c.state.saasBillingUsage.subscription.active_until='2026-10-15T12:00:00Z';
  if(scenario==='preview') billing.previewEntitlement=true;
  if(scenario==='inactive') billing.entitlementActive=false;
  if(scenario==='legacy') c.state.saasBillingUsage.subscription.plan_key='team';
  if(scenario==='offline') domestic.online=false;
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});guard.beginLoading();c.setView('connect');
  const buttons=controls.settings.querySelectorAll('[data-saas-action="domestic-billing-create-order"]');
  assert.equal(buttons.length,scenario==='offline'?0:scenario==='legacy'?2:1);
  assert.ok(buttons.every(button=>button.disabled));
  if(scenario==='expires-while-held') clock.now=Date.parse('2026-10-16T12:00:00Z');
  assert.equal(guard.releaseLoading(),true);
  assert.ok(buttons.every(button=>button.disabled===['invalid-date','expired','expires-while-held'].includes(scenario)));
  if(scenario==='offline') {
    const refresh=controls.settings.querySelector('[data-saas-action="refresh"]');
    assert.equal(refresh.disabled,false);assert.equal(refresh.textContent,'刷新付款状态');
  }
  assert.equal(c.calls.length,0);
});

for(const scenario of ['ready','bad-contract','non-integer','negative','disabled','status-unavailable','checkout','no-packs'])
test(`actual media purchase controls retain every original eligibility requirement: ${scenario}`,()=>{
  const f=settingsControlFixture('billing'),{c,controls}=f,media=c.state.saasBillingUsage.media_credits;
  if(scenario==='bad-contract') media.contract_version='unverified';
  if(scenario==='non-integer') media.available_points=1.5;
  if(scenario==='negative') media.purchased_points=-1;
  if(scenario==='disabled') media.purchase.purchase_enabled=false;
  if(scenario==='status-unavailable') media.purchase.status='unavailable';
  if(scenario==='checkout') c.state.saasDomesticBillingCheckout={purchase_type:'media_points',qr_image_data_url:'fixture-image'};
  if(scenario==='no-packs') media.packs=[];
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});guard.beginLoading();c.setView('connect');
  const buttons=controls.settings.buttons.filter(button=>button.textContent==='购买素材点');
  assert.equal(buttons.length,scenario==='no-packs'?0:1);
  assert.ok(buttons.every(button=>button.disabled));
  assert.ok(buttons.every(button=>(button.dataset.saasAction==='media-credit-purchase')===(scenario==='ready')));
  guard.releaseLoading();
  assert.ok(buttons.every(button=>button.disabled===(scenario!=='ready')));
  assert.ok(buttons.every(button=>(button.dataset.mediaCreditPackKey==='fixture-pack')===(scenario==='ready')));
  assert.equal(c.calls.length,0,'No purchase/query/checkout action is invoked');
});

for(const compact of [false,true]) test(`actual onboarding ${compact?'compact':'full'} loading action sync is limited to Settings`,()=>{
  const f=settingsControlFixture('account'),{c,controls}=f;
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});guard.beginLoading();c.state.view='connect';
  controls.settings.innerHTML=c.renderSaasMerchantOnboardingPanel({compact,accountWorkspace:compact});
  const button=controls.settings.buttons[0];assert.equal(button.disabled,true);guard.releaseLoading();
  assert.equal(button.disabled,false);assert.equal(c.calls.length,0);
  button.disabled=true;c.state.view='product';c.syncSaasSettingsOwnedLoadingControls();assert.equal(button.disabled,true);
});

test('owned Settings sync fails closed for malformed markers and leaves unrelated dangerous controls unchanged',()=>{
  const f=settingsControlFixture('account'),{c,controls}=f;
  const guard=c.saasEbayStoreRequestGuard('store-A',{interaction:true});guard.beginLoading();c.state.view='connect';
  controls.settings.innerHTML='<button disabled data-saas-settings-loading-blocked="">empty</button>'+
    '<button disabled data-saas-settings-loading-blocked="0">numeric</button>'+
    '<button disabled data-saas-settings-loading-blocked="False">wrong-case</button>'+
    '<button disabled data-saas-action="domestic-billing-refund-request">unmarked</button>'+
    '<button data-saas-action="domestic-billing-query-order">query</button>';
  const nodes=[...controls.settings.buttons];guard.releaseLoading();
  assert.ok(nodes.slice(0,4).every(button=>button.disabled));assert.equal(nodes[4].disabled,false);
  assert.equal(c.calls.length,0);
});

test('actual successful refresh recomputes Settings predicates on the current rendered nodes',async()=>{
  const c=await protectedRefreshFixture(),controls=installActualModelSettingsRendering(c),send=c.fetch;
  c.consumeSaasStartupRequestedView=()=> 'connect';c.activeSaasRefreshView=()=> 'connect';
  c.state.saasModelSettings={read_failed:true};
  c.saasModelConnectionAttemptState=()=>({state:c.state.saasModelSettings?.read_failed?'read_failed':'ready',canRetry:true});
  c.setView('connect');const before=controls.settings.querySelector('[data-saas-action="save-model-api-key"]');
  assert.equal(before.disabled,true);assert.equal(before.dataset.saasSettingsLoadingBlocked,'true');
  c.fetch=async(...args)=>{const response=await send(...args);return args[0].endsWith('/model/settings')?
    {...response,json:async()=>({model_settings:{read_failed:false}})}:response;};
  await c.refreshSaasState({silent:true});
  assert.equal(c.state.saasError,'');assert.equal(c.state.saasProtectedStateReady,true);assert.equal(c.state.saasLoading,false);
  const current=controls.settings.querySelector('[data-saas-action="save-model-api-key"]');
  assert.ok(current!==before,'The normal successful response retains its existing real render path');
  assert.equal(current.disabled,false);assert.equal(current.dataset.saasSettingsLoadingBlocked,'false');
  assert.ok(c.calls.every(call=>call.method==='GET'));
});

// R01/run7: transport-only synthetic completion, never a real platform write.
// Preserve the original tests above; this closes the actual refresh/render seam.
async function normalCompletionRefreshFixture() {
  const c=await protectedRefreshFixture(),clone=value=>JSON.parse(JSON.stringify(value));
  const company='b1ui-company',user='b1ui-user',storeId='b1ui-store-A';
  const project={key:'b1ui-product-A',source_report_id:'b1ui-source-A',candidate_id:'b1ui-candidate-A'};
  const at='2026-10-15T13:50:27.000Z';
  const profile={identity:{company_id:company,user_id:user,role:'owner'},
    user:{user_id:user,email:'b1ui-synthetic@example.invalid',status:'active'},
    company:{company_id:company,company_name:'B1 本地合成公司',status:'active'}};
  const stores=['A','B'].map(suffix=>({company_id:company,store_id:`b1ui-store-${suffix}`,
    store_name:`B1 本地合成店铺 ${suffix}`,platform:'ebay',marketplace:'EBAY_US',status:'active',
    settings:{placeholder_store_name:false,official_store_name:`B1 本地合成店铺 ${suffix}`}}));
  const connections=stores.map(store=>({company_id:company,store_id:store.store_id,
    connection_id:'b1ui-connection-'+store.store_id,platform:'ebay',status:'authorized',scopes:['sell.inventory.readonly']}));
  const packets=stores.map((store,i)=>({packet_id:`b1ui-packet-${i?'B':'A'}`,company_id:company,
    store_id:store.store_id,platform:'ebay',source_mode:'merchant_provided',created_at:at,
    packet:{packet_id:`b1ui-packet-${i?'B':'A'}`,present_resource_keys:['inventory_locations'],inventory_locations:[],source_label:'merchant_provided'}}));
  const serverCard={confirmation_id:'b1ui-original',company_id:company,store_id:storeId,task_id:'b1ui-task-A',
    action_type:'publish_listing',status:'pending',title:'B1 本地合成铝制支架 · b1ui-original',high_risk:true,
    default_action:'hold',created_at:at,item:{product:'B1 本地合成铝制支架',listing_project_identity:clone(project),
      source_packet_id:'b1ui-packet-A',publish_payload:{listing:{sku:'B1UI-SKU-A',title:'B1 Synthetic Aluminum Stand',
        category_id:'123',price:{value:'20.00',currency:'USD'},quantity:1,merchant_location_key:'b1ui-warehouse-a'}}}};
  const executions=[],storage=new Map([['r01-hint','1'],['r01-store',storeId]]);
  const storageHost={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
  Object.assign(c.state,{view:'confirm',confirmFilter:'all',saasIdentity:clone(profile.identity),saasUser:clone(profile.user),
    saasCompany:clone(profile.company),saasStores:clone(stores),saasConnections:clone(connections),saasDataPackets:clone(packets),
    saasConfirmations:[clone(serverCard)],saasExecutionResults:[],saasProtectedStateReady:true,saasProtectedStateFromCache:false,
    saasSessionExpiryHandled:false,saasDemoBootstrapEnabled:false,saasToken:'',saasLoading:false,saasError:'',
    saasEbayReapprovalContext:null,saasEbayWriteAdapter:{real_platform_writes_enabled:false,mode:'b1_local_synthetic'},
    saasAiCeoThread:[],saasAiCeoLatestTurn:null,saasLastCeoCommand:null,saasStartupRequestedView:''});
  c.store=clone(stores[0]);c.calls=[];c.toasts=[];c.r01Trace=[];c.r01Warnings=[];
  Object.assign(c,{localStorage:storageHost,sessionStorage:storageHost,
    saasStorageKeys:{sessionHint:'r01-hint',storeId:'r01-store',token:'r01-unused-token',lastAccount:'r01-last-account'},
    purgeLegacySaasStoredBearerToken:()=>{},shouldPersistSaasBearerTokenForDev:()=>false,
    safeStorageValue:key=>storageHost.getItem(key)||'',readKnownSaasAccounts:()=>[],saasOnboardingAccountKey:()=>user,
    saasCurrentListingProjectIdentity:()=>clone(project),saasListingDraftAuthoritativeSku:()=> 'B1UI-SKU-A',
    isSaasUniqueCurrentReadOnlySyncConfirmation:()=>false,saasServerNowMs:()=>Date.parse(at),
    saasAiCeoHistoryEpoch:0,SAAS_AI_CEO_INITIAL_VISIBLE_TURNS:12,
    setTimeout,clearTimeout,console:{warn:(...args)=>c.r01Warnings.push(args.join(' '))},
    recordOptionalSaasSoftTimeout:()=>assert.fail('No synthetic GET may time out'),
  });
  const names=['approveFirstSaasConfirmation','activeSaasRefreshView','consumeSaasStartupRequestedView',
    'loadSaasSessionFromStorage','hasSaasPersistentSessionHint','hasSaasProtectedSessionCandidate','hasSaasProtectedBackendState',
    'saasAccountStorageAliases','assertSaasAccountSessionCurrent','assertSaasLiveIdentityScope','hydrateSaasProtectedStateFromCache',
    'storedSaasStoreId','ensureSaasDemoSession','ensureSaasDemoStoreAndConnection','activeSaasStore',
    'normalizeSaasRecordStoreId','saasRecordStoreId','sortedSaasDataPackets','saasConnectionsForStoreId','saasKnownStoreCandidates','preferredSaasStore',
    'saasAiCeoHistoryAccountScope','resetSaasAiCeoHistoryArchive','saasAiCeoHistoryArchive','saasAiCeoHistoryRequestContext','isCurrentSaasAiCeoHistoryRequest',
    'isSaasProtectedStateHydrating','renderSaasProtectedStateLoadingView','ensureSaasConfirmScaffold','renderConfirmations',
    'optionalSaasFetchFast'];
  vm.runInContext(names.map(extract).join('\n'),c);
  // The real renderer writes this host node. No renderer/refresh replacement.
  let html='';Object.defineProperty(c.panel,'innerHTML',{get:()=>html,set:value=>{
    html=value;c.r01Trace.push({stage:'render',completion:value.includes('本次已完成'),pending:value.includes('data-saas-action="approve-confirmation"')});
  }});
  // Observe the existing catch without changing its control flow or swallowing it.
  let readError='';Object.defineProperty(c.state,'saasError',{configurable:true,get:()=>readError,set:value=>{
    readError=value;if(value)c.r01Trace.push({stage:'state_error',message:String(value)});
  }});
  const explicit={
    '/me':profile,'/stores':{stores},'/permissions/me':{permissions:['view_report','create_task','approve_confirmation','execute_action'],roles:['owner']},
    '/connections':{connections},'/merchant-onboarding/primary-ebay':{merchant_onboarding:null},
    '/ebay-write/adapter/status':{ebay_write_adapter:{real_platform_writes_enabled:false,mode:'b1_local_synthetic'}},
    '/secret-refs':{secret_refs:[]},'/data-packets':{data_packets:packets},
    '/ai-ceo/chat-history':{ai_ceo_chat_history:{scope:'account',cross_store:true,turns:[],has_more:false}},
    '/tasks':{tasks:[]},'/auth/sessions':{sessions:[]},'/health':{status:'ok',fixture:'b1ui-local-only'},
    '/billing/plans':{billing_plan:null},'/billing/usage':{billing_usage:null},'/billing/media-credits':{media_credits:null},
    '/billing/checkout-contract':{billing_checkout:null},'/billing/domestic/contract':{domestic_billing:null},
    '/billing/domestic/orders':{domestic_billing_orders:[]},'/billing/manual-beta/orders':{manual_beta_payment_orders:[]},
    '/model/value-gate':{model_value_gate:null},'/model/providers/catalog':{model_provider_catalog:null},
    '/post-publish/cockpit':{post_publish_cockpit:null},'/ip-risk-screening':{ip_risk_screening:null},
    '/media/capabilities':{media_capabilities:null},'/ebay-read-only/field-contracts':{ebay_read_only_field_contracts:null},
    '/ebay-read-only/live-adapter/status':{ebay_live_read_adapter:null},'/ebay-read-only/http-client/status':{ebay_http_client:null},
    '/oauth/requests':{oauth_requests:[]},'/merchant-memory':{merchant_memory:[]},'/audit-logs':{audit_logs:[]},
  };
  for(const store of stores){
    explicit[`/stores/${store.store_id}/model/settings`]={model_settings:{configured:false,connection_state:'not_configured'}};
    explicit[`/stores/${store.store_id}/merchant-ceo/commands/latest`]={merchant_ceo_command:null,command:null,source_record:null,secret_exposed:false};
    explicit[`/stores/${store.store_id}/account-health`]={account_health:{status:'ready',synthetic_fixture:true}};
    explicit[`/stores/${store.store_id}/media-asset-jobs`]={media_asset_jobs:[]};
  }
  // Same normal-case data contract as fixture.cjs reportsFor(origin,false).
  // This is transport data, not a copied product projection/eligibility algorithm.
  explicit['/reports']={reports:['A','B'].flatMap(suffix=>{
    const identity={key:`b1ui-product-${suffix}`,source_report_id:`b1ui-source-${suffix}`,candidate_id:`b1ui-candidate-${suffix}`};
    const facts={product_name:`B1 本地合成铝制支架 ${suffix}`,sku:`B1UI-SKU-${suffix}`,condition:'NEW',material:'Aluminum',
      price:'20',currency:'USD',quantity:'1',category_id:'123',category_leaf:'Stand',image_urls:c.state.saasApiBase+'/assets/jiejing-app-icon.svg',
      item_specifics:'Brand: Unbranded\nType: Stand\nMaterial: Aluminum',inventory_location_key:'b1ui-warehouse-a',
      inventory_location_name:'B1 本地合成仓库',inventory_location_city:'Austin',inventory_location_state:'TX',inventory_location_country:'US',
      merchant_location_key:'b1ui-warehouse-a',item_location:'US',package_weight_g:'120',package_length_cm:'10',package_width_cm:'8',package_height_cm:'4',
      procurement_cost:'4',procurement_cost_currency:'USD',shipping_cost:'2',ebay_fee:'3',ad_budget:'0',return_risk_reserve:'1',exchange_rate:'1',
      exchange_rate_basis:'sale_currency_per_cost_currency',net_profit:'10',gross_margin_percent:'50',fulfillment_policy_id:'b1ui-fulfillment',
      payment_policy_id:'b1ui-payment',return_policy_id:'b1ui-return',image_rights_confirmed:true,merchant_owned_product_confirmed:true};
    const packet={contract_version:'merchant_product_fact_packet_v1',source:'authenticated_merchant_request',product_name:facts.product_name,
      listing_project_identity:identity,merchant_confirmed_facts:facts,source_confirmed_facts:{},derived_listing_suggestions:{},
      fact_conflicts:[],unknown_facts:[],simulation_only:false};
    const common={company_id:company,store_id:`b1ui-store-${suffix}`,user_id:user,task_id:`b1ui-task-${suffix}`,status:'saved',created_at:at};
    return [{...common,report_id:`b1ui-facts-${suffix}`,report_type:'merchant.product_facts',report:{product_name:facts.product_name,
      product:facts.product_name,listing_project_identity:identity,merchant_product_fact_packet:packet}},
      {...common,report_id:`b1ui-listing-${suffix}`,report_type:'listing.package',runtime_run_id:'listing_draft_generation',report:{
        contract_version:'listing_ai_draft_generation_v1',product:facts.product_name,listing_project_identity:identity,
        merchant_product_fact_packet:packet,listing_handoff:{source_mode:'project_scoped_live_model',ready_for_listing_draft:true,
          listing_fields:{title:facts.product_name,selling_points:['Synthetic aluminum fixture','Local evidence only'],
            description_seed:'B1 synthetic product description. No real merchant or provider is used.',price_band:'20 USD',category_id:'123',
            condition:'NEW',quantity:'1',item_specifics:{Brand:'Unbranded',Type:'Stand',Material:'Aluminum'},
            ebay_inventory_item_draft:{sku:facts.sku,condition:'NEW',product:{title:facts.product_name,description:'B1 synthetic product',imageUrls:[facts.image_urls]},
              availability:{shipToLocationAvailability:{quantity:1}}},ebay_offer_draft:{sku:facts.sku,merchantLocationKey:'b1ui-warehouse-a',
              categoryId:'123',pricingSummary:{price:{value:'20',currency:'USD'}}},merchant_product_fact_packet:packet}}}}];
  })};
  c.fetch=async(url,options={})=>{
    assert.equal(new URL(url).origin,c.state.saasApiBase,'Only the inert synthetic origin is accepted');
    const route=new URL(url).pathname,method=options.method||'GET',body=options.body?JSON.parse(options.body):null;
    c.calls.push({route,method,body});let payload;
    if(method==='GET'){
      if(route==='/confirmations') payload={confirmations:[serverCard]};
      else if(route==='/execution-results') payload={execution_results:executions};
      else {assert(Object.hasOwn(explicit,route),`Unlisted synthetic GET: ${route}`);payload=explicit[route];}
    }else{
      assert.equal(method,'POST');assert.match(route,/^\/confirmations\/b1ui-original\/(decision|preflight|execute)$/);
      const stage=route.split('/').at(-1);
      if(stage==='decision'){
        assert.equal(serverCard.status,'pending');assert.equal(body.decision,'approve');
        serverCard.status='approved';serverCard.decided_by=user;serverCard.decided_at=at;payload={confirmation:serverCard};
      }else if(stage==='preflight'){
        assert.equal(serverCard.status,'approved');payload={preflight:{status:'ready_for_platform_adapter',synthetic_fixture:true}};
      }else{
        assert.equal(serverCard.status,'approved');serverCard.status='executed';
        serverCard.execution_recovery={company_id:company,store_id:storeId,confirmation_id:serverCard.confirmation_id,action_type:'publish_listing',
          status:'execution_completed',zero_write_proven:false,next_action:'view_receipt',automatic_retry_allowed:false,secret_exposed:false};
        executions.push({confirmation_id:serverCard.confirmation_id,status:'executed',synthetic_fixture:true});
        payload={execution:{status:'executed',confirmation_id:serverCard.confirmation_id,synthetic_fixture:true}};
        assert.equal(c.state.saasConfirmations[0].status,'pending','Transport mutation must not write client state');
      }
    }
    const transferred=JSON.stringify(payload);
    c.r01Trace.push({stage:'response',method,route,status:200});
    return {ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>JSON.parse(transferred),text:async()=>transferred};
  };
  c.r01ServerCard=serverCard;return c;
}

test('R01 exact normal approval reaches completed card through real core and extended refresh',async t=>{
  const c=await normalCompletionRefreshFixture();
  assert.equal(c.state.saasProtectedStateReady,true);assert.equal(c.hasSaasPersistentSessionHint(),true);
  c.setView('confirm');assert.match(c.panel.innerHTML,/data-saas-action="approve-confirmation"/);
  await c.approveFirstSaasConfirmation('b1ui-original');
  t.diagnostic(JSON.stringify({tag:'R01_COMPLETION_TRACE',trace:c.r01Trace,warnings:c.r01Warnings,
    final:{status:c.state.saasConfirmations[0]?.status,error:c.state.saasError,view:c.state.view,
      ready:c.state.saasProtectedStateReady,generation:c.saasStateRefreshGeneration},toasts:c.toasts}));
  const writes=c.calls.filter(call=>call.method==='POST');
  assert.deepEqual(writes.map(call=>call.route.split('/').at(-1)),['decision','preflight','execute']);
  assert.equal(writes[1].body.idempotency_key,writes[2].body.idempotency_key);
  assert.equal(writes[2].body.payload.real_platform_writes_enabled,false);assert.equal(c.r01ServerCard.status,'executed');
  assert.equal(c.state.saasError,'','Actual refresh must not hide an internal failure');
  assert.equal(c.r01Warnings.length,0,'No optional endpoint may fall back silently');
  assert.ok(c.calls.some(call=>call.method==='GET'&&call.route==='/reports'),'Actual extended refresh must run');
  assert.equal(c.state.saasConfirmations[0].status,'executed');
  assert.equal(c.state.saasExecutionResults[0].confirmation_id,'b1ui-original');
  assert.equal((c.panel.innerHTML.match(/本次已完成/g)||[]).length,1);
  assert.doesNotMatch(c.panel.innerHTML,/data-saas-action="approve-confirmation"/);
  assert.equal(c.state.view,'confirm');assert.equal(c.state.saasLoading,false);
});

test('accepted execute followed by a real core GET failure stays pending verification and cannot approve twice',async()=>{
  const c=await normalCompletionRefreshFixture(),send=c.fetch;
  c.fetch=async(url,options={})=>{
    const response=await send(url,options);
    if((options.method||'GET')==='GET'&&new URL(url).pathname==='/confirmations'){
      const payload={error:'synthetic_confirmation_read_unavailable'};
      return {ok:false,status:503,headers:{get:()=> 'application/json'},json:async()=>payload,text:async()=>JSON.stringify(payload)};
    }
    return response;
  };
  c.setView('confirm');
  await c.approveFirstSaasConfirmation('b1ui-original');
  assert.equal(c.r01ServerCard.status,'executed','The synthetic backend accepted the one execution');
  assert.equal(c.state.saasConfirmations[0].status,'pending','No fabricated final card status');
  assert.equal(c.state.saasConfirmations[0].execution_recovery,undefined,'No fabricated recovery or zero-write evidence');
  assert.match(c.state.saasError,/部分状态读取失败/,'The real refresh catch must be reached');
  assert.ok(!c.toasts.some(text=>/确认已记录：当前不会操作真实 eBay|确认已提交：按发布前检查/.test(text)),
    'A failed post-execution read must not produce the ordinary success toast');
  assert.match(c.panel.innerHTML,/结果待核对/);
  assert.doesNotMatch(c.panel.innerHTML,/data-saas-action="approve-confirmation"/);
  const before=c.calls.filter(call=>call.method==='POST').length;
  await c.approveFirstSaasConfirmation('b1ui-original');
  assert.equal(c.calls.filter(call=>call.method==='POST').length,before,'A second handler invocation must not approve or execute again');
  assert.deepEqual(c.calls.filter(call=>call.method==='POST').map(call=>call.route.split('/').at(-1)),['decision','preflight','execute']);
});

// All additions below exercise the same real handler/refresh/render chain.
// Response variants live only at the inert fetch boundary; they never assign a
// completed status, recovery receipt, or qualification directly to client state.
function outcomeResponse(payload,status=200) {
  const transferred=JSON.stringify(payload);
  return {ok:status>=200&&status<300,status,headers:{get:()=> 'application/json'},
    json:async()=>JSON.parse(transferred),text:async()=>transferred};
}

async function submittedOutcomeFixture() {
  const c=await normalCompletionRefreshFixture(),send=c.fetch;
  c.r01OriginalPending=JSON.parse(JSON.stringify(c.r01ServerCard));c.r01Send=send;
  c.fetch=async(url,options={})=>{
    const response=await send(url,options);
    return (options.method||'GET')==='GET'&&new URL(url).pathname==='/confirmations'?
      outcomeResponse({error:'synthetic_confirmation_read_unavailable'},503):response;
  };
  c.setView('confirm');await c.approveFirstSaasConfirmation('b1ui-original');
  assert.equal(c.r01ServerCard.status,'executed');assert.equal(c.state.saasConfirmations[0].status,'pending');
  assert.match(c.state.saasError,/部分状态读取失败/);
  assert.ok(c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]));
  c.fetch=send;c.toasts=[];return c;
}

function useOutcomeConfirmationResponse(c,cards,status=200) {
  c.fetch=async(url,options={})=>{
    const response=await c.r01Send(url,options);
    return (options.method||'GET')==='GET'&&new URL(url).pathname==='/confirmations'?
      outcomeResponse(status===200?{confirmations:cards}:{error:'synthetic_read_failed'},status):response;
  };
}

function assertOutcomeLocked(c,record) {
  const card=c.saasEbayRecoveryCard('b1ui-original');
  assert.equal(c.saasEbaySubmittedOutcome(card),record);
  c.renderSaasConfirmPanel();
  assert.equal((c.panel.innerHTML.match(/data-saas-action="check-ebay-submitted-outcome"/g)||[]).length,1);
  assert.doesNotMatch(c.panel.innerHTML,/data-saas-action="approve-confirmation"[^>]*data-saas-confirmation="b1ui-original"/);
  assert.match(c.panel.innerHTML,/本次提交结果待核对/);
  assert.doesNotMatch(c.panel.innerHTML,/请求已提交|提交成功/);
}

test('submitted result read-only verification accepts only the bound authoritative completion and never writes',async()=>{
  const c=await submittedOutcomeFixture(),start=c.calls.length;
  assert.equal(await c.checkSaasEbaySubmittedOutcome('b1ui-original'),true);
  assert.deepEqual(c.calls.slice(start).map(call=>[call.method,call.route]),[['GET','/confirmations']]);
  assert.equal(c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]),null);
  assert.equal(c.state.saasConfirmations[0].status,'executed');
  assert.equal((c.panel.innerHTML.match(/本次已完成/g)||[]).length,1);
  assert.doesNotMatch(c.panel.innerHTML,/check-ebay-submitted-outcome|approve-confirmation/);
  await c.approveFirstSaasConfirmation('b1ui-original');
  assert.equal(c.calls.filter(call=>call.method==='POST').length,3);
});

for(const status of [401,503]) test(`read-only verification ${status} retains the mark without auth refresh or execution replay`,async()=>{
  const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
  useOutcomeConfirmationResponse(c,[],status);const start=c.calls.length,refreshes=c.refreshes;
  assert.equal(await c.checkSaasEbaySubmittedOutcome('b1ui-original'),false);
  assert.deepEqual(c.calls.slice(start).map(call=>[call.method,call.route]),[['GET','/confirmations']]);
  assert.equal(c.refreshes,refreshes);assertOutcomeLocked(c,record);
  assert.equal(c.state.saasConfirmations[0].status,'pending');assert.equal(c.state.saasConfirmations[0].execution_recovery,undefined);
  assert.equal(c.calls.filter(call=>call.method==='POST').length,3);
});

const unprovenOutcomeVariants={
  pending:(c)=>[c.r01OriginalPending],
  approved_without_receipt:(c)=>[{...c.r01OriginalPending,status:'approved'}],
  executed_without_receipt:(c)=>{const card=JSON.parse(JSON.stringify(c.r01ServerCard));delete card.execution_recovery;return [card];},
  missing_card:()=>[],
  duplicate_card:(c)=>[c.r01ServerCard,c.r01ServerCard],
  wrong_company:(c)=>[{...c.r01ServerCard,company_id:'other-company'}],
  wrong_store:(c)=>[{...c.r01ServerCard,store_id:'b1ui-store-B'}],
  wrong_action:(c)=>[{...c.r01ServerCard,action_type:'cleanup_test_listing'}],
  wrong_receipt_id:(c)=>[{...c.r01ServerCard,execution_recovery:{...c.r01ServerCard.execution_recovery,confirmation_id:'other'}}],
  wrong_receipt_scope:(c)=>[{...c.r01ServerCard,execution_recovery:{...c.r01ServerCard.execution_recovery,store_id:'b1ui-store-B'}}],
  retry_allowed:(c)=>[{...c.r01ServerCard,execution_recovery:{...c.r01ServerCard.execution_recovery,automatic_retry_allowed:true}}],
  contradictory_zero_write:(c)=>[{...c.r01ServerCard,execution_recovery:{...c.r01ServerCard.execution_recovery,zero_write_proven:true}}],
  pending_with_completed_receipt:(c)=>[{...c.r01ServerCard,status:'pending'}],
};
for(const [variant,cards] of Object.entries(unprovenOutcomeVariants))
test(`GET200 ${variant} cannot unlock a submitted result`,async()=>{
  const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
  useOutcomeConfirmationResponse(c,cards(c));const start=c.calls.length;
  assert.equal(await c.checkSaasEbaySubmittedOutcome('b1ui-original'),false);
  assert.deepEqual(c.calls.slice(start).map(call=>[call.method,call.route]),[['GET','/confirmations']]);
  assertOutcomeLocked(c,record);assert.doesNotMatch(c.panel.innerHTML,/本次已完成/);
  await c.approveFirstSaasConfirmation('b1ui-original');
  assert.equal(c.calls.filter(call=>call.method==='POST').length,3);
});

for(const variant of ['pending','executed_without_receipt'])
test(`ordinary full core/extended GET200 ${variant} does not clear the submitted mark`,async()=>{
  const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
  useOutcomeConfirmationResponse(c,unprovenOutcomeVariants[variant](c));const start=c.calls.length;
  const result=await c.refreshSaasState({silent:true});
  assert.equal(result.confirmationStateApplied,true);assert.equal(c.state.saasError,'');
  assert.ok(c.calls.slice(start).some(call=>call.route==='/reports'));
  assert.ok(c.calls.slice(start).every(call=>call.method==='GET'));assertOutcomeLocked(c,record);
  assert.doesNotMatch(c.panel.innerHTML,/本次已完成/);
});

function installOutcomeScopeTransitions(c) {
  // Existing reset/navigation functions run unchanged; unrelated storage,
  // polling, AI, and non-confirmation view boundaries remain inert VM hosts.
  for(const name of ['invalidateSaasSettingsActionContext','stopSaasAiCeoCrossDeviceSync',
    'stopSaasPendingNewListingProjectReconciliation','setSaasAiCeoTaskContextState','resetSaasProductFeedbackViewState',
    'invalidateSaasListingAiGenerationContext','resetSaasListingPublishEvidenceForNewProject','resetSaasBulkWorkspaceForListingProject']) c[name]=()=>{};
  c.saasBrowserSessionRefreshPromise=null;
  vm.runInContext(['resetSaasActiveProjectForStoreSwitch','resetSaasListingProjectTransientState',
    'invalidateSaasProtectedSessionContext'].map(extract).join('\n'),c);
}

function transitionSubmittedInteraction(c,transition) {
  installOutcomeScopeTransitions(c);
  const cards=c.state.saasConfirmations,draft=c.state.saasListingComposerDraft;
  if(transition==='store-ABA') {
    c.localStorage.setItem('r01-store','b1ui-store-B');c.resetSaasActiveProjectForStoreSwitch();
    assert.equal(c.activeSaasStore().store_id,'b1ui-store-B');assert.equal(c.saasEbaySubmittedOutcome(cards[0]),null);
    c.localStorage.setItem('r01-store','b1ui-store-A');c.resetSaasActiveProjectForStoreSwitch();
    c.state.saasConfirmations=cards;c.state.saasListingComposerDraft=draft;
  }else if(transition==='account-ABA') {
    const identity=c.state.saasIdentity,user=c.state.saasUser;
    c.invalidateSaasProtectedSessionContext();c.state.saasIdentity={...identity,user_id:'other-user'};c.state.saasUser={...user,user_id:'other-user'};
    assert.equal(c.saasEbaySubmittedOutcome(cards[0]),null);
    c.invalidateSaasProtectedSessionContext();c.state.saasIdentity=identity;c.state.saasUser=user;c.state.saasProtectedStateReady=true;
  }else if(transition==='view-ABA') {
    c.setView('connect');c.setView('confirm');
  }else if(transition==='project-ABA') {
    const identity=c.saasCurrentListingProjectIdentity;
    c.saasCurrentListingProjectIdentity=()=>({key:'other-project'});c.resetSaasListingProjectTransientState();
    c.saasCurrentListingProjectIdentity=identity;c.resetSaasListingProjectTransientState();
  }else if(transition==='same-ID-new-selection') {
    c.state.saasEbayReapprovalContext=c.saasEbayRecoveryContext(cards[0]);
  }else {
    c.saasEbayStoreRequestGuard('b1ui-store-A',{interaction:true}).beginLoading();
  }
}

for(const transition of ['store-ABA','account-ABA','view-ABA','project-ABA','same-ID-new-selection','same-scope-new-request'])
test(`accepted POST then held real core GET cannot publish or unlock after ${transition}`,async()=>{
  const c=await normalCompletionRefreshFixture(),send=c.fetch;
  let entered,release;const held=new Promise(resolve=>{entered=resolve;});
  c.fetch=async(url,options={})=>{
    const response=await send(url,options);
    if((options.method||'GET')==='GET'&&new URL(url).pathname==='/confirmations')
      await new Promise(resolve=>{release=resolve;entered();});
    return response;
  };
  c.setView('confirm');const pending=c.approveFirstSaasConfirmation('b1ui-original');await held;
  assert.equal(c.r01ServerCard.status,'executed');
  const record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);assert.ok(record);
  transitionSubmittedInteraction(c,transition);
  const cards=c.state.saasConfirmations;c.state.saasError='current-interaction';c.toasts=[];
  c.renderSaasConfirmPanel();const html=c.panel.innerHTML;
  release();await pending;
  assert.equal(c.state.saasConfirmations,cards);assert.equal(cards[0].status,'pending');
  assert.equal(cards[0].execution_recovery,undefined);assert.equal(c.state.saasError,'current-interaction');
  assert.equal(c.toasts.length,0);assert.equal(c.panel.innerHTML,html);assertOutcomeLocked(c,record);
  await c.approveFirstSaasConfirmation('b1ui-original');
  assert.equal(c.calls.filter(call=>call.method==='POST').length,3);
});

for(const scope of ['user','company','store'])
test(`same confirmation ID in another ${scope} does not inherit or remove the original scope mark`,async()=>{
  const c=await submittedOutcomeFixture(),original=c.state.saasConfirmations;
  const identity=c.state.saasIdentity,user=c.state.saasUser,company=c.state.saasCompany;
  const record=c.saasEbaySubmittedOutcome(original[0]);
  const other=JSON.parse(JSON.stringify(c.r01OriginalPending));
  if(scope==='user') {c.state.saasIdentity={...identity,user_id:'other-user'};c.state.saasUser={...user,user_id:'other-user'};}
  if(scope==='company') {other.company_id='other-company';c.state.saasIdentity={...identity,company_id:'other-company'};c.state.saasCompany={company_id:'other-company'};}
  if(scope==='store') {other.store_id='b1ui-store-B';c.localStorage.setItem('r01-store','b1ui-store-B');}
  c.state.saasConfirmations=[other];assert.equal(c.saasEbaySubmittedOutcome(other),null);
  c.renderSaasConfirmPanel();assert.doesNotMatch(c.panel.innerHTML,/check-ebay-submitted-outcome/);
  const start=c.calls.length;assert.equal(await c.checkSaasEbaySubmittedOutcome('b1ui-original'),false);assert.equal(c.calls.length,start);
  assert.equal(c.state.saasEbaySubmittedOutcomes.length,1);
  c.state.saasIdentity=identity;c.state.saasUser=user;c.state.saasCompany=company;
  c.localStorage.setItem('r01-store','b1ui-store-A');c.state.saasConfirmations=original;assertOutcomeLocked(c,record);
  assert.deepEqual(Object.keys(record).sort(),['actionType','companyId','confirmationId','storeId','userId']);
});

test('older read-only completion cannot clear the mark or replace a newer same-scope verification',async()=>{
  const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
  let entered,release,reads=0;const held=new Promise(resolve=>{entered=resolve;});
  c.fetch=async(url,options={})=>{
    const response=await c.r01Send(url,options);
    assert.equal(options.method,'GET');assert.equal(new URL(url).pathname,'/confirmations');
    if(++reads===1) {await new Promise(resolve=>{release=resolve;entered();});return response;}
    return outcomeResponse({confirmations:[c.r01OriginalPending]});
  };
  const start=c.calls.length,older=c.checkSaasEbaySubmittedOutcome('b1ui-original');await held;
  assert.equal(await c.checkSaasEbaySubmittedOutcome('b1ui-original'),false);
  const current=c.state.saasConfirmations;c.toasts=[];release();assert.equal(await older,false);
  assert.equal(c.state.saasConfirmations,current);assert.equal(c.toasts.length,0);assertOutcomeLocked(c,record);
  assert.deepEqual(c.calls.slice(start).map(call=>call.method),['GET','GET']);
});

test('held read-only GET cannot replace an in-progress or completed newer real refresh or its qualifications',async()=>{
  for(const phase of ['completed','in-progress']) {
    const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
    let entered,release,enteredNew,releaseNew,confirmationReads=0;
    const held=new Promise(resolve=>{entered=resolve;}),newHeld=new Promise(resolve=>{enteredNew=resolve;});
    const newCard={...c.r01OriginalPending,confirmation_id:'newer-pending',title:'Newer pending card'};
    c.fetch=async(url,options={})=>{
      const response=await c.r01Send(url,options);
      if((options.method||'GET')==='GET'&&new URL(url).pathname==='/confirmations') {
        if(++confirmationReads===1) {await new Promise(resolve=>{release=resolve;entered();});return response;}
        await new Promise(resolve=>{releaseNew=resolve;enteredNew();});
        return outcomeResponse({confirmations:[c.r01OriginalPending,newCard]});
      }
      return response;
    };
    const start=c.calls.length,older=c.checkSaasEbaySubmittedOutcome('b1ui-original');await held;
    const fresh=c.refreshSaasState({silent:true});await newHeld;
    try {
      if(phase==='completed') {releaseNew();assert.equal((await fresh).confirmationStateApplied,true);}
      const current=c.state.saasConfirmations,qualifications=[c.saasVerifiedUnpublishedDraftSaveConfirmations,
        c.saasVerifiedControlledPublishConfirmations,c.saasVerifiedInventoryLocationConfirmations];
      assertOutcomeLocked(c,record);c.toasts=[];release();
      assert.equal(await older,false,`The older verification is obsolete as soon as the newer refresh is ${phase}`);
      assert.equal(c.state.saasConfirmations,current,'An older verification must not overwrite the current authoritative collection');
      const after=[c.saasVerifiedUnpublishedDraftSaveConfirmations,c.saasVerifiedControlledPublishConfirmations,
        c.saasVerifiedInventoryLocationConfirmations];
      qualifications.forEach((qualification,index)=>assert.equal(after[index],qualification));
      assert.equal(c.toasts.length,0);assertOutcomeLocked(c,record);
    } finally {releaseNew();await fresh;}
    assert.equal(c.state.saasError,'');assert.ok(c.calls.slice(start).some(call=>call.route==='/reports'));
    assert.ok(c.state.saasConfirmations.some(card=>card.confirmation_id==='newer-pending'));assertOutcomeLocked(c,record);
    assert.ok(c.calls.slice(start).every(call=>call.method==='GET'));
  }
});

test('older extended refresh cannot replace a newer successful read-only completion with its stale pending core',async()=>{
  const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
  let entered,release,confirmationReads=0;const held=new Promise(resolve=>{entered=resolve;});
  c.fetch=async(url,options={})=>{
    const response=await c.r01Send(url,options),route=new URL(url).pathname;
    assert.equal(options.method||'GET','GET');
    if(route==='/confirmations'&&++confirmationReads===1) return outcomeResponse({confirmations:[c.r01OriginalPending]});
    if(route==='/reports') await new Promise(resolve=>{release=resolve;entered();});
    return response;
  };
  const start=c.calls.length,older=c.refreshSaasState({silent:true});await held;
  try {
    assert.equal(c.state.saasConfirmations[0].status,'pending');assert.equal(c.state.saasLoading,false);
    assertOutcomeLocked(c,record);
    const button=c.panel.innerHTML.match(/data-saas-action="check-ebay-submitted-outcome" data-saas-confirmation="([^"]+)"/);
    assert.ok(button,'The actual renderer exposes the read-only control after core publication');
    assert.equal(await c.checkSaasEbaySubmittedOutcome(button[1]),true);
    const completed=c.state.saasConfirmations,qualifications=[c.saasVerifiedUnpublishedDraftSaveConfirmations,
      c.saasVerifiedControlledPublishConfirmations,c.saasVerifiedInventoryLocationConfirmations];
    assert.equal(completed[0].status,'executed');assert.equal(c.saasEbaySubmittedOutcome(completed[0]),null);
    assert.match(c.panel.innerHTML,/本次已完成/);assert.doesNotMatch(c.panel.innerHTML,/approve-confirmation/);
    release();await older;
    assert.equal(c.state.saasConfirmations,completed,'Old extended data must not resurrect the pending card after a newer bound receipt');
    const after=[c.saasVerifiedUnpublishedDraftSaveConfirmations,c.saasVerifiedControlledPublishConfirmations,c.saasVerifiedInventoryLocationConfirmations];
    qualifications.forEach((qualification,index)=>assert.equal(after[index],qualification));
    assert.equal(c.state.saasConfirmations[0].status,'executed');assert.equal(c.saasEbaySubmittedOutcome(completed[0]),null);
    assert.equal((c.panel.innerHTML.match(/本次已完成/g)||[]).length,1);assert.doesNotMatch(c.panel.innerHTML,/approve-confirmation|check-ebay-submitted-outcome/);
    assert.equal(c.state.saasLoading,false);assert.equal(c.state.saasError,'');
    assert.ok(c.state.saasReports.length>0,'Unrelated extended data must still complete normally');
    await c.approveFirstSaasConfirmation('b1ui-original');
    assert.ok(c.calls.slice(start).every(call=>call.method==='GET'));assert.equal(c.calls.filter(call=>call.method==='POST').length,3);
  } finally {release();await older;}
});

test('older held core response cannot replace a newer same-generation read-only completion',async()=>{
  const c=await submittedOutcomeFixture(),record=c.saasEbaySubmittedOutcome(c.state.saasConfirmations[0]);
  let entered,release,confirmationReads=0;const held=new Promise(resolve=>{entered=resolve;});
  c.fetch=async(url,options={})=>{
    const response=await c.r01Send(url,options),route=new URL(url).pathname;
    assert.equal(options.method||'GET','GET');
    if(route==='/confirmations'&&++confirmationReads===1) {
      await new Promise(resolve=>{release=resolve;entered();});
      return outcomeResponse({confirmations:[c.r01OriginalPending]});
    }
    return response;
  };
  const start=c.calls.length,older=c.refreshSaasState({silent:true});await held;
  try {
    assert.equal(c.state.saasConfirmations[0].status,'pending');assert.equal(c.state.saasLoading,true);
    assertOutcomeLocked(c,record);
    const button=c.panel.innerHTML.match(/<button\b[^>]*data-saas-action="check-ebay-submitted-outcome"[^>]*>/);
    assert.ok(button,'The real read-only control remains visible while the older core is pending');
    assert.doesNotMatch(button[0],/\bdisabled\b/);
    const id=button[0].match(/data-saas-confirmation="([^"]+)"/)[1],generation=c.saasStateRefreshGeneration;
    assert.equal(await c.checkSaasEbaySubmittedOutcome(id),true);
    assert.equal(c.saasStateRefreshGeneration,generation,'The newer verification does not cancel unrelated refresh work');
    const completed=c.state.saasConfirmations,qualifications=[c.saasVerifiedUnpublishedDraftSaveConfirmations,
      c.saasVerifiedControlledPublishConfirmations,c.saasVerifiedInventoryLocationConfirmations];
    assert.equal(completed[0].status,'executed');assert.equal(c.saasEbaySubmittedOutcome(completed[0]),null);
    assert.match(c.panel.innerHTML,/本次已完成/);assert.doesNotMatch(c.panel.innerHTML,/approve-confirmation/);
    release();await older;
    assert.equal(c.state.saasConfirmations,completed,'Old core must not resurrect pending after a newer bound receipt');
    const after=[c.saasVerifiedUnpublishedDraftSaveConfirmations,c.saasVerifiedControlledPublishConfirmations,c.saasVerifiedInventoryLocationConfirmations];
    qualifications.forEach((qualification,index)=>assert.equal(after[index],qualification));
    assert.equal(c.state.saasConfirmations[0].status,'executed');assert.equal(c.saasEbaySubmittedOutcome(completed[0]),null);
    assert.equal((c.panel.innerHTML.match(/本次已完成/g)||[]).length,1);assert.doesNotMatch(c.panel.innerHTML,/approve-confirmation|check-ebay-submitted-outcome/);
    assert.equal(c.state.saasLoading,false);assert.equal(c.state.saasError,'');
    assert.ok(c.state.saasReports.length>0,'Skipping stale core confirmations must not cancel extended reports');
    await c.approveFirstSaasConfirmation('b1ui-original');
    assert.ok(c.calls.slice(start).every(call=>call.method==='GET'));assert.equal(c.calls.filter(call=>call.method==='POST').length,3);
  } finally {release();await older;}
});
