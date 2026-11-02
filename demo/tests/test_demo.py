import hashlib
import json
from pathlib import Path
import unittest
from itertools import product
from demo_service import run_request, PRESETS, MAX_ACTIONS

class Session:
    def __init__(self, preset='start', tracker='libra'):
        self.body={'preset':preset,'tracker':tracker,'actions':[]};self.result=run_request(self.body)
    def do(self, action):
        self.body['actions'].append(action);self.result=run_request(self.body);return self.result
    def message(self,key):return self.do({'type':'message','key':key})
    def experiment(self,key):return self.do({'type':'experiment','key':key})
    def accept(self):return self.do({'type':'confirmation','proposal_id':self.result['state']['pending']['id'],'accept':True})
    def choose(self,priority):
        self.message('minimum_30');self.accept();self.message('search');self.message(priority);self.accept()

class DemoTests(unittest.TestCase):
    def test_question_orders(self):
        for tracker in ['libra','conventional']:
            for priority in ['cost','sustainability']:
                for length in range(1,4):
                    for order in product(['why','grounds','challenge'],repeat=length):
                        with self.subTest(tracker=tracker,priority=priority,order=order):
                            s=Session(tracker=tracker);s.choose(priority)
                            original=s.result['state']['recommended']
                            for question in order:
                                r=s.message(question)
                                self.assertTrue(r['last_result']['event_accepted'])
                                self.assertEqual(r['last_result']['status'],'released')
                                self.assertEqual(r['state']['recommended'],original)
                                self.assertEqual(r['state']['libra']['targets'],{})
                                if question=='grounds':self.assertIn('fictional product table',r['chat'][-1]['text'])
    def test_evidence_first_preserves_provenance_but_hides_identifiers_in_reply(self):
        s=Session();s.choose('sustainability');r=s.message('grounds')
        self.assertIn('paper.table1.C',json.dumps(r['history']))
        self.assertTrue(any(x['kind']=='evidence_request_expanded' for x in r['history']))
        for m in r['chat']:
            self.assertNotRegex(m['text'],r'paper\.table1|fixture-v|comparison k\d|reference: b\d')
        self.assertEqual(r['chat'][-2]['speaker'],'client')
        self.assertIn('confirmation',r['chat'][-1]['text'])
    def test_ground_request_does_not_erase_an_unanswered_challenge(self):
        s=Session('explanation');s.message('grounds')
        self.assertIn('T:adviser:D:C',s.result['state']['libra']['targets'])
        s.experiment('resume');self.assertFalse(s.result['state']['libra']['targets'])
    def test_support_withdrawal_before_or_after_explanation(self):
        for tracker in ['libra','conventional']:
            for question in [None,'why','grounds']:
                s=Session(tracker=tracker);s.choose('cost')
                if question:s.message(question)
                s.experiment('withdraw_support');self.assertIsNone(s.result['state']['recommended'])
                r=s.message('grounds');self.assertFalse(r['last_result']['event_accepted'])
                self.assertIn('no current recommendation',r['chat'][-1]['text'])
    def test_evidence_after_revision_and_reconfirmed_choice(self):
        s=Session('recovery');s.experiment('restore_d');s.message('search');s.message('sustainability');s.accept()
        r=s.message('grounds');self.assertTrue(r['last_result']['event_accepted'])
        self.assertIn('injected-fixture-v',json.dumps(r['history']))
        self.assertNotIn('injected-fixture-v',r['chat'][-1]['text'])
    def test_first_screening_explicitly_has_two_products(self):
        s=Session();s.message('minimum_30');r=s.accept()
        self.assertIn('two products checked so far',r['chat'][-1]['text'])
        self.assertIn('remaining two',r['chat'][-1]['text'])
    def test_distributed_engine_file_integrity(self):
        root=Path(__file__).resolve().parents[1]
        for name,expected in json.loads((root/'ENGINE_PROVENANCE.json').read_text())['sha256'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected)
    def test_two_selection_directions_and_tracker_agreement(self):
        for priority,product in [('cost','D'),('sustainability','C')]:
            results=[]
            for tracker in ['libra','conventional']:
                s=Session(tracker=tracker);s.choose(priority)
                self.assertEqual(s.result['state']['recommended'],product)
                self.assertEqual(s.result['state']['profile']['minimum'],30)
                results.append(s.result['chat'])
            self.assertEqual(*results)
    def test_text_cannot_confirm_and_stale_control_fails(self):
        s=Session();s.message('minimum_30');s.message('text_accept')
        self.assertIsNone(s.result['state']['profile']['minimum'])
        self.assertFalse(s.result['last_result']['event_accepted'])
        ref=s.result['state']['pending']['id'];s.accept()
        with self.assertRaises(ValueError):s.do({'type':'confirmation','proposal_id':ref,'accept':True})
    def test_decline_preserves_profile(self):
        s=Session();s.message('minimum_30')
        s.do({'type':'confirmation','proposal_id':s.result['state']['pending']['id'],'accept':False})
        self.assertIsNone(s.result['state']['profile']['minimum']);self.assertIsNone(s.result['state']['pending'])
    def test_obligation_survives_retraction_then_is_answered(self):
        for tracker in ['libra','conventional']:
            s=Session('explanation',tracker);self.assertEqual(len(s.result['state']['libra']['targets']),1)
            s.message('retract');self.assertEqual(len(s.result['state']['libra']['targets']),1)
            s.experiment('resume');self.assertEqual(len(s.result['state']['libra']['targets']),0)
            self.assertEqual(s.result['last_result']['status'],'released')
    def test_temporary_change_expires(self):
        s=Session('adaptation');s.accept()
        self.assertEqual(s.result['state']['profile']['minimum'],50);self.assertEqual(s.result['effective_minimum'],30)
        s.message('cost');s.accept();self.assertEqual(s.result['state']['recommended'],'D')
        s.experiment('end_episode')
        self.assertEqual(s.result['effective_minimum'],50);self.assertIsNone(s.result['state']['adaptation'])
        self.assertIsNone(s.result['state']['recommended'])
    def test_evidence_update_requires_fresh_confirmation(self):
        s=Session('recovery');self.assertIsNone(s.result['state']['recommended'])
        self.assertNotIn('D',s.result['state']['eligible'])
        s.experiment('restore_d');s.message('search');self.assertIsNone(s.result['state']['recommended'])
        s.message('cost');s.accept();self.assertEqual(s.result['state']['recommended'],'D')
    def test_sessions_and_presets_are_isolated(self):
        first=run_request({})
        for tracker in ['libra','conventional']:
            for preset in PRESETS:run_request({'preset':preset,'tracker':tracker})
        self.assertEqual(first,run_request({}))
    def test_request_limits_and_closed_action_schema(self):
        for body in [{'actions':[{}]*(MAX_ACTIONS+1)}, {'actions':[{'type':'message','key':'search','event':{}}]},
                     {'tracker':'llm_only'}, {'preset':'unknown'}, {'actions':[{'type':'confirmation','proposal_id':'x','accept':'true'}]}]:
            with self.assertRaises((ValueError,KeyError,TypeError)):run_request(body)
    def test_malformed_keys_never_evaluate_code(self):
        for key in ['../../secrets','__import__("os")',[],{}]:
            with self.assertRaises((ValueError,KeyError,TypeError)):
                run_request({'actions':[{'type':'message','key':key}]})

if __name__=='__main__':unittest.main()
