import base64
import json
import io
import os
import unittest
from itertools import product
from unittest.mock import patch
from urllib.error import HTTPError
import live_service as live


def event(kind,text,scope=None,**payload):
    return {'kind':kind,'payload':payload,'scope':scope or ('standing' if kind=='propose_minimum' else 'unresolved'),'ref':None,'spans':[text]}

class LiveTests(unittest.TestCase):
    def setUp(self):
        with live.LOCK:live.CACHE.clear();live.ACTIVE.clear();live.CALL_TIMES.clear()
        self.result=live.live_request({'mode':'live','action':{'type':'start'}})
    def body(self,action):return {'mode':'live','session_token':self.result['session_token'],'action':action}
    def send(self,text,kind,**payload):
        self.result=live.live_request(self.body({'type':'message','text':text}),lambda t,e:(event(kind,t,**payload),{'provider':'test'}))
        return self.result
    def accept(self):
        self.result=live.live_request(self.body({'type':'confirmation','proposal_id':self.result['state']['pending']['id'],'accept':True}));return self.result
    def choose(self):
        self.send('My usual minimum is 30%.','propose_minimum',minimum=30,mode='firm');self.accept()
        self.send('Check the other products.','search')
        self.send('For this comparison, sustainability matters more.','propose_priority',dimension='sustainability');self.accept()
    def test_replay_needs_no_model_calls_and_evidence_first_works(self):
        self.choose();r=self.send('What are the sources and confirmation?','question_ground')
        self.assertEqual(r['state']['recommended'],'C');self.assertEqual(r['model_calls'],4)
        self.assertIn('fictional product table',r['chat'][-1]['text'])
        self.assertFalse(r['state']['libra']['targets'])
        replay=live.restore(live.unseal(r['session_token']))
        self.assertEqual(replay.snapshot(),r['state'])
    def test_duplicate_message_does_not_call_model_twice(self):
        body=self.body({'type':'message','text':'Hello'})
        calls=[]
        def model(t,e):calls.append(t);return event('unresolved',t,reason='greeting'),{}
        first=live.live_request(body,model);second=live.live_request(body,model)
        self.assertEqual(first,second);self.assertEqual(len(calls),1)
    def test_tampered_or_expired_session_cannot_apply_events(self):
        token=self.result['session_token'];raw,sig=token.split('.')
        session=json.loads(live.decode(raw));session['steps'].append({'type':'confirmation','accept':True,'proposal_id':'x'})
        forged=live.encode(json.dumps(session).encode())+'.'+sig
        with self.assertRaises(live.LiveError):live.live_request({'mode':'live','session_token':forged,'action':{'type':'experiment','key':'end_episode'}})
        session['expires']=0
        with self.assertRaises(live.LiveError):live.unseal(live.seal(session))
    def test_typed_accept_cannot_confirm(self):
        self.send('Set my usual minimum to 30%.','propose_minimum',minimum=30,mode='firm')
        r=self.send('Yes, accept.','unresolved',reason='confirmation_control')
        self.assertIsNone(r['state']['profile']['minimum']);self.assertIsNotNone(r['state']['pending'])
    def test_social_replies_preserve_each_pending_proposal(self):
        for proposal, description in [('minimum','usual minimum of 28%'),('cost','D’s lower annual cost'),
                                      ('sustainability','C’s higher sustainable share'),('adaptation','28% minimum for this conversation only')]:
            for reason, text in product(['confirmation_control','greeting','acknowledgment'],
                                        ['Ok. PErfect! THanks!', "Great! Let's do this way!", 'Sounds good, please go ahead.']):
                with self.subTest(proposal=proposal,reason=reason,text=text):
                    self.setUp()
                    minimum=50 if proposal=='adaptation' else 28
                    self.send(f'My usual minimum is {minimum}%.','propose_minimum',minimum=minimum,mode='firm')
                    if proposal!='minimum':
                        self.accept();self.send('Check the remaining products.','search')
                        if proposal=='adaptation':
                            self.send('Use 28% for this conversation because no product meets 50%.','propose_adaptation',
                                      minimum=28,reason='No product meets my usual minimum.',scope=self.result['state']['advice_id'])
                        else:self.send(f'For this comparison, I prefer {proposal}.','propose_priority',dimension=proposal)
                    before=self.result['state']
                    r=self.send(text,'unresolved',reason=reason)
                    self.assertIn(description,r['chat'][-1]['text'])
                    self.assertIn('still waiting for confirmation',r['chat'][-1]['text'])
                    self.assertIn('Confirm this change',r['chat'][-1]['text'])
                    self.assertIn('Decline',r['chat'][-1]['text'])
                    self.assertEqual({k:v for k,v in before.items() if k!='revision'},
                                     {k:v for k,v in r['state'].items() if k!='revision'})
                    replay=live.restore(live.unseal(r['session_token']))
                    self.assertEqual(replay.snapshot(),r['state'])
                    # Both explicit controls remain usable after a social reply.
                    declined=live.live_request(self.body({'type':'confirmation','proposal_id':before['pending']['id'],'accept':False}))
                    self.assertIsNone(declined['state']['pending'])
                    self.assertEqual(declined['state']['profile'],before['profile'])
                    accepted=self.accept()
                    self.assertIsNone(accepted['state']['pending'])
                    if proposal in {'cost','sustainability'}:
                        self.assertEqual(accepted['state']['recommended'],'D' if proposal=='cost' else 'C')
    def test_acknowledgments_follow_the_current_conversation(self):
        for stage, expected in [('start','minimum sustainable share'),('screened','28% minimum is recorded'),
                                ('comparison','which matters more'),('recommended','why D was recommended')]:
            with self.subTest(stage=stage):
                self.setUp()
                if stage!='start':
                    self.send('My usual minimum is 28%.','propose_minimum',minimum=28,mode='firm');self.accept()
                if stage in {'comparison','recommended'}:self.send('Check the remaining products.','search')
                if stage=='recommended':
                    self.send('For this comparison, lower cost matters more.','propose_priority',dimension='cost');self.accept()
                before=self.result['state']
                r=self.send('Thanks!','unresolved',reason='acknowledgment')
                self.assertIn('You’re welcome.',r['chat'][-1]['text'])
                self.assertIn(expected,r['chat'][-1]['text'])
                self.assertEqual({k:v for k,v in before.items() if k!='revision'},
                                 {k:v for k,v in r['state'].items() if k!='revision'})
                r=self.send('Yes, accept.','unresolved',reason='confirmation_control')
                self.assertIn('no proposal waiting',r['chat'][-1]['text'])
                if stage=='recommended':
                    r=self.send('Thanks, show me the evidence.','question_ground')
                    self.assertIn('fictional product table',r['chat'][-1]['text'])
                    self.assertEqual(r['state']['recommended'],'D')
    def test_no_free_tier_confirmation_means_no_request(self):
        with patch.dict(os.environ,{'GROQ_API_KEY':'test','GROQ_FREE_TIER_CONFIRMED':'0'}),patch.object(live,'urlopen') as call:
            with self.assertRaises(live.LiveError):live.interpret('hello',live.DemoEngine())
            call.assert_not_called()
    def test_api_failure_preserves_session_and_has_no_retry(self):
        old=self.result['session_token']
        with patch.dict(os.environ,{'GROQ_API_KEY':'test','GROQ_FREE_TIER_CONFIRMED':'1'}),patch.object(live,'urlopen',side_effect=HTTPError(live.ENDPOINT,429,'quota',{},None)) as call:
            with self.assertRaises(live.LiveError) as caught:live.live_request(self.body({'type':'message','text':'hello'}))
            self.assertEqual(caught.exception.status,429);self.assertEqual(call.call_count,1)
        self.assertEqual(live.unseal(old)['model_calls'],0)
    def test_message_and_action_limits(self):
        for action in [{'type':'message','text':'x'*501},{'type':'experiment','key':'lower_d'},{'type':'message','text':'hello','event':{}},{'type':'confirmation','accept':'yes','proposal_id':'x'}]:
            with self.assertRaises(live.LiveError):live.live_request(self.body(action))
        s=live.unseal(self.result['session_token']);s['model_calls']=12
        body={'mode':'live','session_token':live.seal(s),'action':{'type':'message','text':'hello'}}
        with self.assertRaises(live.LiveError):live.live_request(body)
    def test_provider_parse_failure_requests_rephrasing_without_state_change(self):
        old=self.result['session_token']
        error=HTTPError(live.ENDPOINT,400,'parse',{},io.BytesIO(json.dumps({'error':{'code':'output_parse_failed','message':'Parsing failed'}}).encode()))
        with patch.dict(os.environ,{'GROQ_API_KEY':'test','GROQ_FREE_TIER_CONFIRMED':'1'}),patch.object(live,'urlopen',side_effect=error) as call:
            with self.assertRaises(live.LiveError) as caught:live.live_request(self.body({'type':'message','text':'Explain this choice'}))
            self.assertIn('rephrase',str(caught.exception));self.assertEqual(call.call_count,1)
        self.assertEqual(live.unseal(old)['steps'],[])
    def test_valid_json_cannot_bypass_event_validation(self):
        old=self.result['session_token']
        raw={'kind':'propose_minimum','minimum':30,'dimension':None,'product':None,'scope':'standing','reason':None,'spans':['30%']}
        for changed in [{'minimum':True},{'spans':['invented quotation']},{'kind':'confirm'},{'extra':'ignored?'}]:
            response={'model':live.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps({**raw,**changed})}}]}
            with patch.dict(os.environ,{'GROQ_API_KEY':'test','GROQ_FREE_TIER_CONFIRMED':'1'}),patch.object(live,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
                with self.assertRaises(live.LiveError):live.live_request(self.body({'type':'message','text':'I want 30%.'}))
                self.assertEqual(call.call_count,1)
            self.assertEqual(live.unseal(old)['steps'],[])
    def test_schema_rejects_fake_spans_confirm_and_facts(self):
        raw={'kind':'unresolved','minimum':None,'dimension':None,'product':None,'scope':'unresolved','reason':'unsupported','spans':['hello']}
        self.assertEqual(live.to_event(raw,'hello',live.DemoEngine())['kind'],'unresolved')
        acknowledgment={**raw,'reason':'acknowledgment','spans':['Thanks!']}
        self.assertEqual(live.to_event(acknowledgment,'Thanks!',live.DemoEngine())['payload']['reason'],'acknowledgment')
        for changes in [{'kind':'confirm'},{'spans':['not in message']},{'facts':{'D':0}},{'minimum':True},{'product':'C'},{'reason':None}]:
            with self.assertRaises(ValueError):live.to_event({**raw,**changes},'hello',live.DemoEngine())
        minimum={**raw,'kind':'propose_minimum','minimum':30,'scope':'standing','reason':None,'spans':['30%']}
        self.assertEqual(live.to_event(minimum,'My usual minimum is 30%.',live.DemoEngine())['payload']['minimum'],30)
    def test_unrelated_request_has_a_clear_bounded_reply(self):
        r=self.send('Book my flight','unresolved',reason='unsupported')
        self.assertIn('four fictional products',r['chat'][-1]['text'])
        self.assertIsNone(r['state']['recommended'])
    def test_vercel_needs_an_explicit_signing_secret(self):
        with patch.dict(os.environ,{'VERCEL':'1','GROQ_API_KEY':'test','GROQ_FREE_TIER_CONFIRMED':'1','DEMO_SESSION_SECRET':''}):
            self.assertFalse(live.config()['available'])
            with self.assertRaises(live.LiveError):live.signing_key()
            result=live.live_request({'mode':'live','action':{'type':'start'}})
            self.assertFalse(result['live']['available']);self.assertIsNone(result['session_token'])

if __name__=='__main__':unittest.main()
