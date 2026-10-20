#!/usr/bin/env python3
"""Real-repository execution authority regressions; synthetic identities only."""
from __future__ import annotations
import json
import copy
from dataclasses import replace
import os
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.config import SaaSSettings
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter, build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied
from jiejing_saas.confirmation_authority import item_digest
from jiejing_runtime.execution import ExecutionRequest, ExecutionService
sys.path.insert(0,str(ROOT/'tools'))
from test_jiejing_ebay_write_adapter import attach_publish_evidence
from test_jiejing_unpublished_draft_claim_capability import _new_case

SCOPED_ENV={
    'JIEJING_SAAS_ENV':'staging','JIEJING_EBAY_CLIENT_ID':'B1-SYNTHETIC-CLIENT',
    'JIEJING_EBAY_CLIENT_SECRET':'B1-SYNTHETIC-CLIENT-SECRET','JIEJING_EBAY_RU_NAME':'Jiejing_Auth_RuName',
    'JIEJING_EBAY_OAUTH_EXCHANGE_LIVE':'true','JIEJING_VAULT_ENABLED':'true','JIEJING_VAULT_PROVIDER':'vault',
    'JIEJING_VAULT_LIVE_RESOLVE_ENABLED':'true','JIEJING_VAULT_ADDR':'https://vault.example.test',
    'JIEJING_VAULT_TOKEN':'B1-SYNTHETIC-VAULT-TOKEN','JIEJING_VAULT_MOUNT':'secret',
    'JIEJING_VAULT_KEYSPACE':'b1-synthetic','JIEJING_VAULT_KV_VERSION':'v2',
    'JIEJING_ENABLE_REAL_PLATFORM_WRITES':'false','JIEJING_EBAY_WRITE_LIVE':'false',
    'JIEJING_EBAY_DRAFT_SAVE_LIVE':'true'}

def scoped_case(root, key):
    with patch.dict(os.environ,SCOPED_ENV):
        return _new_case(root,key)


def approved_adapter_case(root, key, prototype, *, scoped=True):
    """Legal real-repository setup for complete legacy adapter regressions."""
    if scoped:
        repo,scope,old,_=scoped_case(root,key)
        task_id=old['task_id']
    else:
        repo=SaaSRepository(root/(key+'.sqlite'),database_engine='sqlite',database_url='')
        account=repo.create_user_with_company(email=key+'@example.test',password='synthetic-only',company_name=key)
        scope={'user_id':account['user']['user_id'],'company_id':account['company']['company_id']}
        scope['store_id']=repo.create_store(**scope,payload={'platform':'ebay','marketplace':'EBAY_US'})['store_id']
        task_id=repo.create_task(**scope,task_type='product.workflow',title=key,input_data={})['task_id']
        old={'item':{}}
    payload=copy.deepcopy(prototype.payload)
    attach_publish_evidence(payload,company_id=scope['company_id'],store_id=scope['store_id'])
    source=('merchant_ebay_draft_save_intake' if prototype.action_type=='save_ebay_listing_draft'
        else 'merchant_existing_ebay_draft_publish_intake' if payload.get('existing_ebay_draft') else 'merchant_publish_intake')
    record=repo.create_confirmation(company_id=scope['company_id'],store_id=scope['store_id'],task_id=task_id,
        runtime_run_id=source,action_type=prototype.action_type,title=key,item={**old['item'],
            'source':source,'company_id':scope['company_id'],'store_id':scope['store_id'],
            'publish_payload':payload,'publish_payload_sha256':item_digest(payload),
            'existing_ebay_draft':payload.get('existing_ebay_draft',{})})
    epochs=repo.access_session_epochs(user_id=scope['user_id'],company_id=scope['company_id'])
    record=repo.decide_confirmation(company_id=scope['company_id'],confirmation_id=record['confirmation_id'],
        decision='approve',decided_by=scope['user_id'],note='Original adapter regression with real authority.',expected_access_epochs=epochs)
    request=replace(prototype,**scope,task_id=task_id,confirmation_id=record['confirmation_id'],
        confirmed_by=scope['user_id'],confirmed_at=record['decided_at'],payload=payload)
    if scoped:
        credential=repo.unpublished_draft_execution_credential_boundary(company_id=scope['company_id'],store_id=scope['store_id'])
    else:
        connection=repo.create_platform_connection(**scope,payload={'platform':'ebay','connection_type':'oauth',
            'status':'publish_authorized','scopes':['https://api.ebay.com/oauth/api_scope/sell.inventory'],
            'create_secret_ref':True,'metadata':{'ebay_user_id_hash':'synthetic-'+key}})
        with repo._connect() as conn:
            conn.execute("update secret_refs set status='stored' where secret_ref=?",(connection['secret_ref'],))
        credential=repo.ebay_execution_connections(company_id=scope['company_id'],store_id=scope['store_id'])[0]
    return repo,request,record,epochs,credential


def claimed_legacy_adapter_case(root,key,prototype):
    repo,request,record,epochs,connection=approved_adapter_case(root,key,prototype,scoped=False)
    result=repo.claim_external_execution(company_id=request.company_id,confirmation_id=request.confirmation_id,
        user_id=request.user_id,expected_access_epochs=epochs,operation_plan=build_ebay_execution_plan(
            request=request,marketplace_id='EBAY_US',connections=[connection]))
    return request,connection,result['_execution_permit']


class EbayExecutionAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.directory=Path(tempfile.mkdtemp(prefix='b1-'))
        self.repo=SaaSRepository(self.directory/'case.sqlite',database_engine='sqlite',database_url='')
        account=self.repo.create_user_with_company(email='b1@example.test',password='synthetic-only',company_name='B1 Synthetic')
        self.company=account['company']['company_id']
        self.user=account['user']['user_id']
        self.store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        self.epochs=self.repo.access_session_epochs(user_id=self.user,company_id=self.company)
        self.record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,
            runtime_run_id='b1-synthetic',item={'sku':'b1','title':'Synthetic item'},
            action_type='publish_listing',title='Synthetic decision')
        self.repo.decide_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'],
            decision='approve',decided_by=self.user,note='Keep the complete original decision.',expected_access_epochs=self.epochs)

    def claim(self):
        if not hasattr(self, 'request'):
            self.publish_fixture()
        args=dict(company_id=self.company,confirmation_id=self.record['confirmation_id'],user_id=self.user,
                  expected_access_epochs=self.epochs, operation_plan=build_ebay_execution_plan(
                      request=self.request, marketplace_id='EBAY_US', connections=[self.connection]))
        return self.repo.claim_external_execution(**args)

    def test_b01_revoked_approver_cannot_claim(self):
        self.publish_fixture()
        self.repo.set_user_access_status(user_id=self.user,status='disabled')
        with self.assertRaisesRegex(PermissionError,'authority|principal|permission'):
            self.claim()
        current=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertEqual(current['status'],'approved')
        self.assertEqual(current['decision_note'],'Original publish decision.')

    def test_valid_same_principal_claim_control(self):
        result=self.claim()
        self.assertTrue(result['external_execution_claimed'])

    def publish_fixture(self):
        payload={
            'account_health':{'status':'clear','selling_status':'active','payout_status':'available','restrictions':[]},
            'listing':{'sku':'B1-001','title':'Ceramic Incense Burner','description_html':'<p>Ceramic incense burner.</p>',
                'category_id':'159895','condition':'NEW','price':{'value':'22.99','currency':'USD'},'quantity':1,
                'item_specifics':{'Brand':'Unbranded','Type':'Incense Burner'},'merchant_location_key':'default'},
            'business_policies':{'fulfillment_policy_id':'fixture-fulfill','payment_policy_id':'fixture-pay','return_policy_id':'fixture-return'},
            'supplier_facts':{'package_weight_g':650,'package_dimensions_cm':{'length':20,'width':15,'height':12},'material':'Ceramic','item_location':'US'},
            'asset_manifest':{'assets':[{'url':'https://example.test/image.jpg'}]},
            'finance_review':{'net_profit_money':{'value':'6.50','currency':'USD'}}}
        attach_publish_evidence(payload,company_id=self.company,store_id=self.store)
        self.record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,
            runtime_run_id='b1-synthetic',item={'publish_payload':payload},action_type='publish_listing',title='Synthetic publish')
        approved=self.repo.decide_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'],
            decision='approve',decided_by=self.user,note='Original publish decision.',expected_access_epochs=self.epochs)
        request=ExecutionRequest(action_type='publish_listing',task_id='',user_id=self.user,company_id=self.company,store_id=self.store,
            platform='ebay',payload=payload,confirmation_id=approved['confirmation_id'],confirmed_by=self.user,
            confirmed_at=approved['decided_at'],idempotency_key='b1-publish')
        connection=self.repo.create_platform_connection(company_id=self.company,store_id=self.store,user_id=self.user,
            payload={'platform':'ebay','connection_type':'oauth','status':'publish_authorized',
                     'scopes':['https://api.ebay.com/oauth/api_scope/sell.inventory'],'create_secret_ref':True,
                     'metadata':{'ebay_user_id_hash':'b1-synthetic-seller'}})
        with self.repo._connect() as conn:
            conn.execute("update secret_refs set status='stored' where secret_ref=?", (connection['secret_ref'],))
        connection=self.repo.ebay_execution_connections(company_id=self.company,store_id=self.store)[0]
        settings=SaaSSettings.from_env(db_path=self.directory/'adapter.sqlite',runtime_db_path=self.directory/'runtime.sqlite',
            output_root=self.directory,host='127.0.0.1',port=0)
        settings.environment='staging'
        settings.requested_real_platform_writes=True
        settings.ebay_write_live_enabled=True
        settings.ebay_token_refresh_live_enabled=True
        self.request,self.connection,self.settings=request,connection,settings
        return request,connection,settings

    def test_b11_token_wait_revocation_blocks_actual_inventory_put(self):
        request,connection,settings=self.publish_fixture()
        preflight=ExecutionService(demo_mode=False).preflight(request)
        self.assertEqual(preflight['status'],'ready_for_platform_adapter')
        claimed=self.claim()
        writes=[]
        def transport(request,timeout):
            writes.append((request.get_method(),request.full_url))
            response={'offerId':'offer-b1'} if request.full_url.endswith('/offer') else {'listingId':'listing-b1'}
            return 200,{},json.dumps(response).encode()
        def token(**kwargs):
            self.repo.set_user_access_status(user_id=self.user,status='disabled')
            return {'ok':True,'access_token':'synthetic-only','source':'injected'}
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        with patch.object(adapter,'_resolve_access_token',side_effect=token), self.assertRaises(EbayExecutionDenied) as denied:
            adapter.publish_listing(request=request,preflight=preflight,connections=[connection],secret_refs=[],marketplace_id='EBAY_US',
                                    execution_permit=claimed['_execution_permit'])
        self.assertEqual(writes,[], 'A revoked original request reached the actual supplier write transport')
        self.assertTrue(denied.exception.recovery['zero_write_proven'])
        self.assertFalse(denied.exception.recovery['automatic_retry_allowed'])

    def test_real_transport_normal_control(self):
        request,connection,settings=self.publish_fixture()
        claimed=self.claim()
        writes=[]
        def transport(request,timeout):
            writes.append((request.get_method(),request.full_url))
            response={'offerId':'offer-b1'} if request.full_url.endswith('/offer') else {'listingId':'listing-b1'}
            return 200,{},json.dumps(response).encode()
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'synthetic-only','source':'injected'}):
            result=adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=claimed['_execution_permit'])
        self.assertEqual(result['status'],'published_to_ebay')
        self.assertEqual([method for method,url in writes],['PUT','POST','POST'])

    def scoped_claim(self, key):
        repo,scope,record,binding=scoped_case(self.directory,key)
        request=SimpleNamespace(**scope,confirmation_id=record['confirmation_id'],task_id=record['task_id'],
            action_type='save_ebay_listing_draft',payload=record['item']['publish_payload'])
        epochs=repo.access_session_epochs(user_id=scope['user_id'],company_id=scope['company_id'])
        credential=repo.unpublished_draft_execution_credential_boundary(company_id=scope['company_id'],store_id=scope['store_id'])
        claimed,capability=repo.claim_unpublished_draft_execution(company_id=scope['company_id'],
            confirmation_id=record['confirmation_id'],user_id=scope['user_id'],expected_binding=binding,
            expected_access_epochs=epochs,operation_plan=build_ebay_execution_plan(request=request,
                marketplace_id='EBAY_US',credential_boundary=credential,draft_offer_id=''))
        return repo,scope,record,claimed,capability

    def test_draft_consume_valid_control(self):
        repo,scope,record,claimed,capability=self.scoped_claim('b1-consume-control')
        self.assertTrue(capability.consume()['external_execution_claimed'])

    def test_b04_draft_consume_rechecks_original_principal(self):
        repo,scope,record,claimed,capability=self.scoped_claim('b1-consume-revoked')
        repo.set_user_access_status(user_id=scope['user_id'],status='disabled')
        with self.assertRaises(PermissionError):
            capability.consume()

    def test_completed_attempt_replay_preserves_terminal_receipts(self):
        request,connection,settings=self.publish_fixture()
        claimed=self.claim()
        permit=claimed['_execution_permit']
        writes=[]
        def transport(request,timeout):
            writes.append(request.full_url)
            return 200,{},json.dumps({'offerId':'offer-b1','listingId':'listing-b1'}).encode()
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        args=dict(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                  connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=permit)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'synthetic-only','source':'injected'}):
            self.assertEqual(adapter.publish_listing(**args)['status'],'published_to_ebay')
            with self.assertRaises(PermissionError):
                adapter.publish_listing(**args)
        with self.repo._connect() as conn:
            row=conn.execute('select phase,operation_state_json from confirmation_execution_authorities_v1 where attempt_id=?',(permit._attempt,)).fetchone()
        self.assertEqual(len(writes),3)
        self.assertEqual(row['phase'],'completed')
        self.assertTrue(all(op['status']=='succeeded' for op in json.loads(row['operation_state_json'])['operations']))

    def test_inflight_duplicate_does_not_destroy_original_receipt(self):
        request,connection,settings=self.publish_fixture()
        claimed=self.claim()
        permit=claimed['_execution_permit']
        writes=[]
        adapter=None
        args=dict(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                  connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=permit)
        def transport(request,timeout):
            writes.append(request.full_url)
            if len(writes)==1:
                with self.assertRaises(PermissionError):
                    adapter.publish_listing(**args)
            return 200,{},json.dumps({'offerId':'offer-b1','listingId':'listing-b1'}).encode()
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'synthetic-only','source':'injected'}):
            self.assertEqual(adapter.publish_listing(**args)['status'],'published_to_ebay')
        with self.repo._connect() as conn:
            row=conn.execute('select phase,operation_state_json from confirmation_execution_authorities_v1 where attempt_id=?',(permit._attempt,)).fetchone()
        self.assertEqual(len(writes),3)
        self.assertEqual(row['phase'],'completed')
        self.assertTrue(all(op['status']=='succeeded' for op in json.loads(row['operation_state_json'])['operations']))


if __name__=='__main__':
    unittest.main(verbosity=2)
