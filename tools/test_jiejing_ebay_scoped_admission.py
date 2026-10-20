#!/usr/bin/env python3
"""Real scoped claims and adapters; every provider transport is injected."""
import copy
from datetime import datetime,timedelta,timezone
import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
import test_jiejing_ebay_execution_authority as fixtures
from test_jiejing_ebay_inventory_location_adapter import _payload as location_payload
from jiejing_runtime.execution import ExecutionRequest,ExecutionService
from jiejing_saas.confirmation_authority import item_digest
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter,build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied
import jiejing_saas.ebay_execution_authority as authority


class ScopedAdmissionTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture

    def scoped(self, action):
        base,connection,settings=self.publish_fixture()
        repo,scope,old,binding=fixtures.scoped_case(self.directory,'b1-scoped')
        payload=copy.deepcopy(base.payload)
        fixtures.attach_publish_evidence(payload,company_id=scope['company_id'],store_id=scope['store_id'])
        source='merchant_ebay_draft_save_intake'
        if action=='publish_listing':
            source='merchant_existing_ebay_draft_publish_intake'
            payload['existing_ebay_draft']={'offer_id':'offer-exact','sku':payload['listing']['sku'],'offer_status':'UNPUBLISHED',
                'public_listing_created':False,'source_execution_id':'synthetic-draft-receipt',
                'source_confirmation_id':old['confirmation_id'],'secret_exposed':False}
        record=repo.create_confirmation(company_id=scope['company_id'],store_id=scope['store_id'],task_id=old['task_id'],
            runtime_run_id=source,action_type=action,title='B1 scoped operation',item={**old['item'],
                'source':source,'publish_payload':payload,'publish_payload_sha256':item_digest(payload),
                'existing_ebay_draft':payload.get('existing_ebay_draft',{})})
        epochs=repo.access_session_epochs(user_id=scope['user_id'],company_id=scope['company_id'])
        record=repo.decide_confirmation(company_id=scope['company_id'],confirmation_id=record['confirmation_id'],
            decision='approve',decided_by=scope['user_id'],note='Exact scoped B1 decision.',expected_access_epochs=epochs)
        request=ExecutionRequest(**scope,action_type=action,task_id=record['task_id'],platform='ebay',payload=payload,
            confirmation_id=record['confirmation_id'],confirmed_by=scope['user_id'],confirmed_at=record['decided_at'],
            idempotency_key='b1-scoped-attempt')
        settings.ebay_draft_save_live_enabled=True
        settings.ebay_controlled_publish_live_enabled=True
        settings.ebay_read_only_live_enabled=True
        settings.requested_real_platform_writes=False
        settings.ebay_write_live_enabled=False
        credential=repo.unpublished_draft_execution_credential_boundary(company_id=scope['company_id'],store_id=scope['store_id'])
        return repo,scope,record,epochs,request,settings,credential

    def draft(self, *, update=False, revoke=False, expire=False):
        repo,scope,record,epochs,request,settings,credential=self.scoped('save_ebay_listing_draft')
        calls=[]
        elapsed=[0]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return datetime.now(tz)+timedelta(seconds=elapsed[0])
        def transport(http_request,timeout):
            method=http_request.get_method()
            calls.append((method,http_request.full_url,json.loads(http_request.data or b'{}')))
            if method=='GET':
                if revoke and len(calls)==2: repo.set_user_access_status(user_id=scope['user_id'],status='disabled')
                if expire and len(calls)==2: elapsed[0]=31
                offers=[{'offerId':'offer-exact','marketplaceId':'EBAY_US','status':'UNPUBLISHED'}] if update else []
                return 200,{},json.dumps({'offers':offers}).encode()
            return 200,{},json.dumps({'offerId':'offer-exact'}).encode()
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        preflight=ExecutionService(demo_mode=False).preflight(request)
        self.assertEqual(preflight['status'],'ready_for_platform_adapter')
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC-TOKEN','source':'injected'}),patch.object(authority,'datetime',Clock):
            prepared=adapter.prepare_listing_draft(request=request,preflight=preflight,credential_boundary=credential,marketplace_id='EBAY_US')
            self.assertTrue(hasattr(prepared,'execution_plan'),str(prepared))
            claimed,capability=repo.claim_unpublished_draft_execution(company_id=scope['company_id'],confirmation_id=record['confirmation_id'],
                user_id=scope['user_id'],expected_binding=prepared.claim_binding(),expected_access_epochs=epochs,operation_plan=prepared.execution_plan())
            if revoke or expire:
                with self.assertRaises(EbayExecutionDenied) as denied:
                    adapter.execute_prepared_listing_draft(request=request,preflight=preflight,prepared=prepared,
                        claim_capability=capability,marketplace_id='EBAY_US')
                self.assertTrue(denied.exception.recovery['zero_write_proven'])
                self.assertEqual([c[0] for c in calls],['GET','GET'])
                with self.assertRaises((PermissionError,ValueError)): capability.consume()
            else:
                result=adapter.execute_prepared_listing_draft(request=request,preflight=preflight,prepared=prepared,
                    claim_capability=capability,marketplace_id='EBAY_US')
                self.assertEqual(result['status'],'saved_to_ebay_draft')
                self.assertEqual([c[0] for c in calls],['GET','GET','PUT','PUT' if update else 'POST'])
        self.assertFalse(any(c[1].endswith('/publish') for c in calls))

    def test_draft_create_complete_real_transport(self): self.draft()
    def test_draft_update_complete_real_transport(self): self.draft(update=True)
    def test_b04_draft_final_get_revocation_sends_nothing(self): self.draft(revoke=True)
    def test_draft_final_get_crosses_preparation_deadline(self): self.draft(expire=True)

    def existing(self, *, revoke=False, expire=False):
        repo,scope,record,epochs,request,settings,credential=self.scoped('publish_listing')
        claimed=repo.claim_external_execution(company_id=scope['company_id'],confirmation_id=record['confirmation_id'],user_id=scope['user_id'],
            expected_access_epochs=epochs,operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',credential_boundary=credential))
        calls=[]
        elapsed=[0]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return datetime.now(tz)+timedelta(seconds=elapsed[0])
        def transport(http_request,timeout):
            method=http_request.get_method(); calls.append((method,http_request.full_url))
            if http_request.full_url.endswith('/kyc'): return 204,{},b''
            if method=='GET':
                if revoke: repo.set_user_access_status(user_id=scope['user_id'],status='disabled')
                if expire: elapsed[0]=901
                return 200,{},b'{"offers":[{"offerId":"offer-exact","marketplaceId":"EBAY_US","status":"UNPUBLISHED"}]}'
            return 200,{},b'{"listingId":"listing-exact"}'
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        args=dict(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),credential_boundary=credential,
            marketplace_id='EBAY_US',expected_offer_id='offer-exact',execution_permit=claimed['_execution_permit'])
        self.assertEqual(args['preflight']['status'],'ready_for_platform_adapter')
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC-TOKEN','source':'injected'}),patch.object(authority,'datetime',Clock):
            if revoke or expire:
                with self.assertRaises(EbayExecutionDenied): adapter.publish_existing_listing_draft(**args)
                self.assertEqual([c[0] for c in calls],['GET','GET'])
            else:
                self.assertEqual(adapter.publish_existing_listing_draft(**args)['status'],'published_to_ebay')
                self.assertEqual([c[0] for c in calls],['GET','GET','POST'])
                self.assertTrue(calls[-1][1].endswith('/offer/offer-exact/publish'))
        self.assertFalse(any('/inventory_item/' in c[1] or c[1].endswith('/offer') for c in calls))

    def test_existing_draft_exact_single_publish(self): self.existing()
    def test_b05_existing_draft_final_get_revocation(self): self.existing(revoke=True)
    def test_existing_draft_final_get_crosses_approval_deadline(self): self.existing(expire=True)

    def location(self, *, revoke=False, change_body=False, expire=False):
        repo,scope,old,epochs,request,settings,credential=self.scoped('save_ebay_listing_draft')
        payload=location_payload()
        created=repo.create_ebay_inventory_location_confirmation(company_id=scope['company_id'],store_id=scope['store_id'],
            user_id=scope['user_id'],location_payload=payload,payload_sha256=item_digest(payload))
        record=repo.decide_confirmation(company_id=scope['company_id'],confirmation_id=created['confirmation']['confirmation_id'],
            decision='approve',decided_by=scope['user_id'],note='Location B1 decision.',expected_access_epochs=epochs)
        calls=[]
        def transport(http_request,timeout):
            method=http_request.get_method(); calls.append((method,http_request.full_url,json.loads(http_request.data or b'{}')))
            if method=='GET':
                if revoke: repo.set_user_access_status(user_id=scope['user_id'],status='disabled')
                raise HTTPError(http_request.full_url,404,'missing',{},io.BytesIO(b'{"errors":[{"errorId":25805,"domain":"API_INVENTORY","category":"REQUEST"}]}'))
            return 204,{},b''
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC-TOKEN','source':'injected'}):
            prepared=adapter.prepare_inventory_location(confirmation=record,location_payload=payload,credential_boundary=credential,marketplace_id='EBAY_US')
        self.assertTrue(hasattr(prepared,'execution_plan'),str(prepared))
        args=dict(company_id=scope['company_id'],store_id=scope['store_id'],confirmation_id=record['confirmation_id'],user_id=scope['user_id'],
            expected_payload_sha256=item_digest(payload),expected_claim_binding=prepared.claim_binding(),marketplace_id='EBAY_US',
            expected_access_epochs=epochs,operation_plan=prepared.execution_plan())
        if revoke:
            with self.assertRaises(PermissionError): repo.claim_ebay_inventory_location_execution(**args)
            self.assertEqual([c[0] for c in calls],['GET']); return
        claimed=repo.claim_ebay_inventory_location_execution(**args)
        permit=claimed.pop('_execution_permit')
        execute=dict(confirmation=claimed,prepared=prepared,marketplace_id='EBAY_US',execution_permit=permit)
        if expire:
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None): return datetime.now(tz)+timedelta(seconds=31)
            with patch.object(authority,'datetime',Clock),self.assertRaises(EbayExecutionDenied):
                adapter.execute_prepared_inventory_location(**execute)
            self.assertEqual([c[0] for c in calls],['GET'])
        elif change_body:
            send=adapter._send_authorized
            def changed(**kwargs):
                kwargs['body']['name']='Not the approved warehouse'
                return send(**kwargs)
            with patch.object(adapter,'_send_authorized',side_effect=changed),self.assertRaises(EbayExecutionDenied):
                adapter.execute_prepared_inventory_location(**execute)
            self.assertEqual([c[0] for c in calls],['GET'])
        else:
            self.assertEqual(adapter.execute_prepared_inventory_location(**execute)['status'],'inventory_location_created')
            self.assertEqual([c[0] for c in calls],['GET','POST'])
            self.assertEqual(calls[-1][2],{key:value for key,value in payload.items() if key!='merchantLocationKey'})

    def test_inventory_actual_body_excludes_route_key(self): self.location()
    def test_inventory_original_epochs_survive_readonly_get(self): self.location(revoke=True)
    def test_inventory_actual_body_tamper_is_denied(self): self.location(change_body=True)
    def test_inventory_final_admission_crosses_preparation_deadline(self): self.location(expire=True)

    def preclaim_denial(self, kind):
        repo,scope,record,epochs,request,settings,credential=self.scoped('publish_listing' if kind=='controlled' else 'save_ebay_listing_draft')
        calls=[]
        def transport(http_request,timeout):
            method=http_request.get_method();calls.append(method)
            self.assertEqual(method,'GET','A preclaim denial must never reach a provider write')
            if kind=='inventory':
                raise HTTPError(http_request.full_url,404,'missing',{},io.BytesIO(b'{"errors":[{"errorId":25805,"domain":"API_INVENTORY","category":"REQUEST"}]}'))
            return 200,{},b'{"offers":[]}'
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        adapter._resolve_access_token=lambda **_:{'ok':True,'access_token':'B1-SYNTHETIC-DENIAL','source':'injected'}
        args=dict(company_id=scope['company_id'],confirmation_id=record['confirmation_id'],user_id=scope['user_id'],expected_access_epochs=epochs)
        if kind=='draft':
            prepared=adapter.prepare_listing_draft(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                credential_boundary=credential,marketplace_id='EBAY_US')
            args.update(expected_binding=prepared.claim_binding(),operation_plan=prepared.execution_plan())
            claim=lambda:repo.claim_unpublished_draft_execution(**args)
        elif kind=='inventory':
            payload=location_payload()
            created=repo.create_ebay_inventory_location_confirmation(company_id=scope['company_id'],store_id=scope['store_id'],
                user_id=scope['user_id'],location_payload=payload,payload_sha256=item_digest(payload))
            record=repo.decide_confirmation(company_id=scope['company_id'],confirmation_id=created['confirmation']['confirmation_id'],
                decision='approve',decided_by=scope['user_id'],note='Independent inventory decision.',expected_access_epochs=epochs)
            prepared=adapter.prepare_inventory_location(confirmation=record,location_payload=payload,credential_boundary=credential,marketplace_id='EBAY_US')
            args.update(confirmation_id=record['confirmation_id'],store_id=scope['store_id'],expected_payload_sha256=item_digest(payload),
                expected_claim_binding=prepared.claim_binding(),marketplace_id='EBAY_US',operation_plan=prepared.execution_plan())
            claim=lambda:repo.claim_ebay_inventory_location_execution(**args)
        else:
            args['operation_plan']=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',credential_boundary=credential)
            claim=lambda:repo.claim_external_execution(**args)
        with repo._connect() as conn:
            approval_id=conn.execute('select approval_authority_id from confirmations where confirmation_id=?',(record['confirmation_id'],)).fetchone()[0]
            approvals=[dict(row) for row in conn.execute('select * from confirmation_approval_authorities_v1 order by authority_id')]
            conn.execute('update confirmations set approval_authority_id=NULL where confirmation_id=?',(record['confirmation_id'],))
            before=[dict(row) for row in conn.execute('select * from audit_logs order by audit_id')]
        reason='approval_authority_missing_reapproval_required'
        with self.assertRaisesRegex(PermissionError,reason): claim()
        denial=dict(company_id=scope['company_id'],store_id=scope['store_id'],confirmation_id=record['confirmation_id'],
            expected_confirmation=repo.get_confirmation(company_id=scope['company_id'],confirmation_id=record['confirmation_id']),reason_code=reason)
        repo._record_ebay_preclaim_denial(**denial)
        with repo._connect() as conn: conn.execute('update confirmations set approval_authority_id=? where confirmation_id=?',(approval_id,record['confirmation_id']))
        with self.assertRaisesRegex(PermissionError,reason): claim()
        # Re-open the actual DB before the display GET, not an in-memory projection.
        fresh=fixtures.SaaSRepository(repo.db_path,database_engine='sqlite',database_url='')
        current=next(row for row in fresh.list_confirmations(company_id=scope['company_id']) if row['confirmation_id']==record['confirmation_id'])
        self.assertEqual(current['status'],'approved');self.assertEqual(current['execution_recovery']['reason_code'],reason)
        self.assertEqual(current['execution_recovery']['next_action'],'prepare_reapproval')
        for key in ('item','decided_by','decided_at','decision_note'): self.assertEqual(current[key],record[key])
        repo._record_ebay_preclaim_denial(**denial)
        with repo._connect() as conn:
            self.assertEqual([dict(row) for row in conn.execute('select * from confirmation_approval_authorities_v1 order by authority_id')],approvals)
            after=[dict(row) for row in conn.execute('select * from audit_logs order by audit_id')]
            self.assertEqual(conn.execute('select count(*) from confirmation_execution_authorities_v1 where confirmation_id=?',(record['confirmation_id'],)).fetchone()[0],0)
        self.assertTrue(all(row in after for row in before));added=[row for row in after if row not in before]
        self.assertEqual(len(added),1);self.assertEqual(added[0]['action_type'],'external_execution.preclaim_denied')
        self.assertEqual((added[0]['company_id'],added[0]['store_id'],added[0]['target_id']),
            (scope['company_id'],scope['store_id'],record['confirmation_id']))
        self.assertEqual(calls,[] if kind=='controlled' else ['GET'])

    def test_draft_preclaim_denial_persists_without_reviving_approval(self): self.preclaim_denial('draft')
    def test_controlled_preclaim_denial_persists_without_reviving_approval(self): self.preclaim_denial('controlled')
    def test_inventory_preclaim_denial_persists_without_reviving_approval(self): self.preclaim_denial('inventory')


if __name__=='__main__': unittest.main(verbosity=2)
