"""No-network regression for the reported Nasdaq answer, including streaming."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jiejing_saas import ai_ceo_chat as chat
from jiejing_saas.repository import _normalize_ai_ceo_chat_history_turn

NOW = '2026-09-29T02:20:00+00:00'
QUESTION = '今天纳斯达克指数收盘多少点'
BAD = ('纳斯达克综合指数今天收盘报26,939.37点，较前一交易日上涨3.34点，涨幅0.01% [S1]。\n'
       '当前来源片段未标注具体日期，无法独立确认今天对应的交易日。'
       '请查看来源页面的日期，公开搜索可能存在延迟。')
SOURCE = {'citation_id': 'S1', 'title': 'NASDAQ Composite (^IXIC)',
          'url': 'https://finance.yahoo.com/quote/%5EIXIC/', 'domain': 'finance.yahoo.com',
          'snippet': '26,939.37 +3.34 (+0.01%) At close: 4:45 PM EDT',
          'captured_at': NOW, 'published_at': ''}


class Model:
    name = 'offline-fixture'
    def __init__(self, answer=BAD):
        self.answer = answer
        self.calls = []

    def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get('on_text_delta'):
            kwargs['on_text_delta'](self.answer)
        return {'text': self.answer, 'finish_reason': 'stop'}


class MarketQuoteBoundary(unittest.TestCase):
    def test_decimal_quote_is_not_changed_during_source_sanitization(self):
        record = chat._source_records_for_model([SOURCE])[0]
        self.assertIn('26,939.37', record['snippet'])
        self.assertNotIn('26,939. 37', record['snippet'])

    def test_standalone_market_question_does_not_inherit_ebay_workflow(self):
        history = [{'user_text': '帮我生成平板电脑支架Listing', 'assistant_text': '请核对资料。',
                    'route': chat.AI_CEO_ROUTE_EBAY_WORKFLOW}]
        for message in (QUESTION, '上海今天天气怎么样', '美股为什么大跌'):
            with self.subTest(message=message):
                plan = chat.build_ai_ceo_turn_plan(message, conversation_history=history)
                self.assertEqual(plan['route'], chat.AI_CEO_ROUTE_EXTERNAL_REALTIME)
                self.assertNotIn('ebay_public_research', plan['required_tools'])

    def test_exact_reported_answer_fails_quality(self):
        self.assertTrue(chat._realtime_answer_needs_repair(BAD, [SOURCE], 'stock_quote', message=QUESTION))

    def test_index_quote_variants_reach_same_evidence_gate(self):
        for message in ('今天纳指多少点', 'NASDAQ Composite close today?', '今天納斯達克指數收盤多少點'):
            with self.subTest(message=message):
                plan = chat.build_ai_ceo_turn_plan(message)
                self.assertEqual(plan['realtime_kind'], 'stock_quote')

    def test_short_product_fact_replies_keep_existing_workflow(self):
        history = [{'user_text': '帮我生成平板支架Listing',
                    'assistant_text': '请补充材质、颜色和尺寸。',
                    'route': chat.AI_CEO_ROUTE_EBAY_WORKFLOW}]
        for message in ('铝合金，银色，15×12厘米', '售价20美元', '是的'):
            with self.subTest(message=message):
                plan = chat.build_ai_ceo_turn_plan(message, conversation_history=history)
                self.assertEqual(plan['route'], chat.AI_CEO_ROUTE_EBAY_WORKFLOW)

    def test_ordinary_close_word_is_not_a_market_request(self):
        for message in ('Please close this now.', 'How close is the latest prototype to finished?'):
            with self.subTest(message=message):
                plan = chat.build_ai_ceo_turn_plan(message)
                self.assertNotEqual(plan['realtime_kind'], 'stock_quote')

    def test_traditional_nasdaq_100_query_keeps_requested_index(self):
        with patch.object(chat, 'now_iso', return_value=NOW):
            query = chat._realtime_search_query(kind='stock_quote', message='納斯達克100今天收盤多少點')
        self.assertIn('NASDAQ-100 NDX', query)
        self.assertNotIn('NASDAQ Composite', query)

    def test_short_honest_missing_evidence_is_not_forced_to_expand(self):
        self.assertFalse(chat._realtime_answer_needs_repair('本次未核实到带交易日期的收盘行情，暂不能确认。',
                                                           [SOURCE], 'stock_quote', message=QUESTION))

    def test_index_query_names_instrument_and_anchors_exchange_date(self):
        with patch.object(chat, 'now_iso', return_value=NOW):
            query = chat._realtime_search_query(kind='stock_quote', message=QUESTION)
        self.assertIn('NASDAQ Composite', query)
        self.assertIn('2026-09-28', query)
        self.assertIn('close', query.lower())
        self.assertNotIn('stock price', query)

    def test_prompt_distinguishes_clock_publication_and_trading_date(self):
        with patch.object(chat, 'now_iso', return_value=NOW):
            system, user = chat.build_ai_ceo_realtime_search_prompts(
                message=QUESTION, context={'server_now': NOW, 'client_timezone':'Asia/Shanghai'},
                route_meta={'realtime_kind':'stock_quote'},
                realtime_search={'status':'ready', 'captured_at':NOW, 'source_records':[SOURCE]})
        payload = json.loads(user)
        self.assertIn('market_time_context', payload)
        self.assertIn('America/New_York', json.dumps(payload['market_time_context']))
        self.assertIn('抓取时间', system)
        self.assertIn('交易日', system)

    def test_bad_number_never_reaches_stream_or_final_answer(self):
        model = Model()
        deltas = []
        snapshot = {'status':'ready', 'provider':'fixture', 'captured_at':NOW,
                    'query':QUESTION, 'source_records':[SOURCE]}
        with patch.object(chat, 'build_ai_ceo_chat_context', return_value={'server_now':NOW}), \
             patch.object(chat, '_run_realtime_search', return_value=snapshot), \
             patch.object(chat, 'now_iso', return_value=NOW), \
             patch.dict('os.environ', {'JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED':'true'}):
            result = chat.run_ai_ceo_chat(repository=None, company_id='test-company', store_id='test-store',
                user_id='test-user', message=QUESTION, model_client=model, on_text_delta=deltas.append)
        self.assertNotIn('26,939', result['answer'])
        self.assertNotIn('26,939', ''.join(deltas))
        self.assertIn('未核实', result['answer'])
        self.assertEqual(result['market_quote_quality']['accepted'], False)
        self.assertEqual(result['status'], 'realtime_search_answered_without_model')

    def test_no_model_fallback_does_not_repeat_unverified_snippets(self):
        answer = chat._fallback_realtime_search_answer('stock_quote', {'source_records':[SOURCE], 'captured_at':NOW})
        self.assertNotIn('26,939', answer)
        self.assertIn('未核实', answer)

    def test_valid_dated_quote_remains_answerable(self):
        answer = '截至美国2026-09-28交易日，纳斯达克综合指数收于26,820.38点，下跌248.34点（0.92%）[S1]。'
        source = {**SOURCE, 'snippet':'2026-09-28 Nasdaq Composite closed at 26,820.38, down 248.34 (0.92%).'}
        model = Model(answer)
        snapshot = {'status':'ready', 'provider':'fixture', 'captured_at':NOW, 'source_records':[source]}
        with patch.object(chat, 'build_ai_ceo_chat_context', return_value={'server_now':NOW}), \
             patch.object(chat, '_run_realtime_search', return_value=snapshot), \
             patch.object(chat, 'now_iso', return_value=NOW), \
             patch.dict('os.environ', {'JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED':'true'}):
            result = chat.run_ai_ceo_chat(repository=None, company_id='test-company', store_id='test-store',
                user_id='test-user', message=QUESTION, model_client=model)
        self.assertEqual(result['answer'], answer)
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(result['market_quote_quality']['accepted'])
        self.assertEqual(result['route'], chat.AI_CEO_ROUTE_EXTERNAL_REALTIME)

    def test_undated_non_quote_realtime_is_also_buffered(self):
        answer = '根据公开来源，当前能确认的事实需要与市场判断分开。市场波动可能受预期与风险偏好影响，不能把推断当成已经发生的事实。' * 3
        model = Model(answer)
        deltas = []
        snapshot = {'status':'ready', 'provider':'fixture', 'source_records':[SOURCE]}
        with patch.object(chat, 'build_ai_ceo_chat_context', return_value={}), \
             patch.object(chat, '_run_realtime_search', return_value=snapshot), \
             patch.dict('os.environ', {'JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED':'true'}):
            result = chat.run_ai_ceo_chat(repository=None, company_id='test-company', store_id='test-store',
                user_id='test-user', message='美股为什么大跌', model_client=model, on_text_delta=deltas.append)
        # The general time-sensitive evidence contract extends the former
        # quote-only buffer. Ordinary chat streaming has separate coverage.
        self.assertIn('未核实', result['answer'])
        self.assertTrue(result['answer_stream_buffered'])
        self.assertEqual(deltas, [])

    def test_history_preserves_citation_and_publication_separately(self):
        source = {**SOURCE, 'published_at':'2026-09-28T22:00:00Z'}
        turn = _normalize_ai_ceo_chat_history_turn({'user_text':QUESTION, 'assistant_text':'本次未核实。',
            'source_records':[source]}, company_id='test-company', user_id='test-user')
        saved = turn['source_records'][0]
        self.assertEqual(saved['citation_id'], 'S1')
        self.assertEqual(saved['published_at'], source['published_at'])
        self.assertEqual(saved['captured_at'], NOW)


if __name__ == '__main__':
    unittest.main()
