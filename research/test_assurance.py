"""Security boundary and evaluator checks beyond the scripted development cases."""
import unittest
from copy import deepcopy
from advice.engine import Engine
from advice.libra import Libra
from advice.tracker import ConventionalTracker
from outcomes import assess_step
from run_study import observe, run_case


def propose(e,minimum=30):
    u=f'{minimum}% standing minimum'
    return e.handle(u,dict(kind='propose_minimum',payload={'minimum':minimum,'mode':'firm'},scope='standing',ref=None,spans=[u]))


class AssuranceChecks(unittest.TestCase):
    def test_event_mode_cannot_impersonate_confirmation_channel(self):
        e=Engine(); propose(e); u='No, do not accept.'
        event=dict(kind='confirm',payload={},scope='standing',ref=e.pending['id'],spans=[u])
        self.assertFalse(e.handle(u,event,mode='structured_control')['event_accepted'])
        self.assertIsNone(e.profile['minimum'])
        self.assertFalse(e._confirmation_authorized)

    def test_ui_accept_requires_actual_boolean(self):
        e=Engine(); propose(e)
        for value in ['yes',1,None]:
            with self.assertRaises(ValueError): e.confirm_control(e.pending['id'],value)
        self.assertIsNone(e.profile['minimum'])

    def test_ui_reference_cannot_be_replayed(self):
        e=Engine(); propose(e); ref=e.pending['id']; e.confirm_control(ref,True)
        before=deepcopy(e.profile)
        with self.assertRaises(ValueError): e.confirm_control(ref,True)
        self.assertEqual(e.profile,before)

    def test_unseen_proposal_cannot_be_accepted(self):
        e=Engine(); u='30 percent'
        e.handle(u,dict(kind='propose_minimum',payload={'minimum':30,'mode':'firm'},scope='standing',ref=None,spans=[u]),auto_release=False)
        with self.assertRaises(ValueError): e.confirm_control(e.pending['id'],True)
        self.assertIsNone(e.profile['minimum'])

    def test_cyclic_ground_package_is_atomic(self):
        for cls in [Libra,ConventionalTracker]:
            with self.subTest(tracker=cls.__name__):
                t=cls(); t.apply({'kind':'assert','actor':'adviser','option':'D'})
                t.apply({'kind':'question','actor':'client','holder':'adviser','token':'Opt(D)'})
                t.apply({'kind':'justify','actor':'adviser','target':'Q:adviser:D',
                    'package':[{'ground':'g:decision','label':'r','for':'D','against':'C','j':'high','r':'low'}]})
                t.apply({'kind':'question','actor':'client','holder':'adviser','token':'g:decision'})
                before=t.snapshot()
                with self.assertRaises(ValueError):
                    t.apply({'kind':'justify','actor':'adviser','target':'E:adviser:g:decision','grounds':['g:decision']})
                self.assertEqual(t.snapshot(),before)

    def test_outcome_checker_detects_unsafe_change_and_wrong_selection(self):
        before={'minimum':30,'recommendation':None}
        bad={'minimum':20,'recommendation':'A','status':'released'}
        score=assess_step({'expect':{'minimum':30},'recommendation_opportunity':'D'},before,bad)
        self.assertTrue(score['unauthorised_standing_change'])
        self.assertFalse(score['correct_new_recommendation'])
        self.assertGreaterEqual(len(score['failures']),3)

    def test_refusal_fails_positive_recommendation_opportunity(self):
        state={'minimum':30,'recommendation':None,'status':'held'}
        score=assess_step({'recommendation_opportunity':'C'},state,state)
        self.assertTrue(score['failures'])
        self.assertFalse(score['correct_new_recommendation'])

    def test_partial_explanation_fails_disclosure_checkpoint(self):
        state={'minimum':30,'recommendation':'D','status':'released','text':'Recommend D.'}
        score=assess_step({'expect':{'contains':['source paper.table1.C']}},state,state)
        self.assertTrue(score['failures'])

    def test_production_default_has_confirmation_barrier(self):
        e=Engine(); self.assertFalse(e._confirmation_authorized)
        self.assertEqual(e.tracker_kind,'libra')

if __name__=='__main__': unittest.main()
