"""Bounded differential exploration of tracker requirements, not a proof of Libra."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import json
import sys
sys.dont_write_bytecode=True
from advice.libra import Libra
from advice.tracker import ConventionalTracker


def projection(t):
    owners={k:sorted(v) for k,v in t.owners.items() if v}
    supports={}
    for token, actors in owners.items():
        for actor in actors:
            if token.startswith('Opt('):
                item=token[4:-1]; rival='C' if item=='D' else 'D'
                supports[actor+':'+token]=t.value(actor,f'Perm({item},{rival})')
            else: supports[actor+':'+token]=t.value(actor,token)
    return {'ownership':owners,'relevance':t.relevance,'requests':t.targets,'support_validity':supports}


def main():
    tested=0; transitions=0; rejected=0; mismatches=[]
    for selected,rival in [('D','C'),('C','D')]:
        reason={'ground':'g:decision','label':'r:decision','for':selected,'against':rival,'j':'high','r':'low'}
        moves=[
            {'kind':'question','actor':'client','holder':'adviser','token':f'Opt({selected})'},
            {'kind':'challenge','actor':'client','holder':'adviser','option':selected,'rival':rival},
            {'kind':'retract','actor':'client','token':f'Opt({rival})'},
            {'kind':'justify','actor':'adviser','target':f'Q:adviser:{selected}','package':[reason]},
            {'kind':'justify','actor':'adviser','target':f'T:adviser:{selected}:{rival}','package':[reason]},
            {'kind':'question','actor':'client','holder':'adviser','token':'g:decision'},
            {'kind':'justify','actor':'adviser','target':'E:adviser:g:decision','grounds':['g:evidence']},
            {'kind':'retract','actor':'adviser','token':'g:decision'}]
        for length in range(1,5):
            for sequence in product(range(len(moves)),repeat=length):
                trackers=[Libra(),ConventionalTracker()]
                for t in trackers: t.apply({'kind':'assert','actor':'adviser','option':selected})
                tested+=1
                for index in sequence:
                    verdict=[]
                    for t in trackers:
                        before=deepcopy(t.snapshot())
                        try: t.apply(moves[index]); verdict.append(True)
                        except (ValueError,KeyError,TypeError):
                            assert t.snapshot()==before,'rejection changed tracker state'
                            verdict.append(False)
                    transitions+=1
                    rejected+=not verdict[0]
                    if verdict[0]!=verdict[1] or projection(trackers[0])!=projection(trackers[1]):
                        mismatches.append({'selected':selected,'sequence':sequence,'move':index})
                        break
    out={'kind':'bounded differential exploration','initial_states':2,'alphabet_size':8,
         'max_sequence_length':4,'sequences':tested,'paired_transition_checks':transitions,
         'rejected_transitions_per_tracker':rejected,'mismatches':mismatches,
         'limits':'Specified alphabet and depth only; shared author and specification; no proof of general equivalence.'}
    (Path(__file__).parent/'results'/'bounded_results.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2)); return bool(mismatches)

if __name__=='__main__': raise SystemExit(main())
