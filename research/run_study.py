"""Continuous supplied-event study: no network/model calls and no human labels."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import platform
import sys
sys.dont_write_bytecode=True
from advice.engine import Engine
from outcomes import assess_step

ROOT=Path(__file__).resolve().parent


def observe(e,result=None):
    r=result or {}
    return {'minimum':e.profile['minimum'],'effective_minimum':e.effective_minimum(),
        'recommendation':e.recommended,'eligible':sorted(e.eligible),'adaptation':deepcopy(e.adaptation),
        'pending':deepcopy(e.pending),'targets':sorted(e.libra.targets),
        'status':r.get('status'),'accepted':r.get('event_accepted',True),'text':r.get('released','')}


def resolve(e,value):
    return {'$comparison':e.comparison['id'] if e.comparison else 'missing-comparison',
            '$advice':e.advice_id,'$pending':e.pending['id'] if e.pending else 'missing-pending'}.get(value,value)


def execute_step(e,s,context):
    op=s['op']
    opts={k:s[k] for k in ['auto_release','fault','fallback'] if k in s}
    if op=='event':
        event=deepcopy(s['event']); event['scope']=resolve(e,event.get('scope','unresolved'))
        event.update(ref=resolve(e,s.get('ref')),spans=[s['utterance']])
        return e.handle(s['utterance'],event,mode='injected_event' if s.get('injected') else 'specified_event',**opts)
    if op=='control':
        if s.get('accept'):
            wanted={k:resolve(e,v) if isinstance(v,str) else v for k,v in s.get('expected_proposal',{}).items()}
            if not e.pending or any(e.pending.get(k)!=v for k,v in wanted.items()):
                return {'status':'user_did_not_accept_unintended_proposal','event_accepted':False}
        return e.confirm_control(e.pending['id'] if e.pending else None,s['accept'],**opts)
    if op=='save_pending': context['old_pending']=e.pending['id']; return {'status':'saved'}
    if op=='stale_control': return e.confirm_control(context['old_pending'],True,**opts)
    if op=='resume': return e.resume_justification()
    if op=='release': return e.release(**opts)
    if op=='evidence': e.update_evidence(s['product'],s['field'],s['value'])
    elif op=='withdraw_support': e.withdraw_support()
    elif op=='end_advice': e.end_advice()
    else: raise ValueError('unknown study operation')
    return {'status':'applied'}


def run_case(case,tracker):
    e=Engine(tracker=tracker); rows=[]; context={}
    for index,s in enumerate(case['steps']):
        before=observe(e)
        try: result=execute_step(e,s,context)
        except (ValueError,KeyError,TypeError) as exc:
            result={'status':'rejected','event_accepted':False,'error':str(exc)}
        out=observe(e,result); score=assess_step(s,before,out)
        rows.append({'step':index+1,'operation':s['op'],'observed':out,'assessment':score,
                     'error':result.get('error') or result.get('event_error')})
    return {'id':case['id'],'family':case['family'],'tracker':tracker,'steps':rows,
            'completed':all(not r['assessment']['failures'] for r in rows)}


def summary(rows):
    steps=[s for r in rows for s in r['steps']]
    count=lambda k:sum(s['assessment'][k] for s in steps)
    return dict(dialogues=len(rows),families=len({r['family'] for r in rows}),
        completed=sum(r['completed'] for r in rows),transitions=len(steps),
        protected_turns=count('protected_turn'),unauthorised_standing_changes=count('unauthorised_standing_change'),
        recommendation_opportunities=count('recommendation_opportunity'),
        correct_new_recommendations=count('correct_new_recommendation'),
        abstention_opportunities=count('abstention_opportunity'))


def main():
    spec=json.loads((ROOT/'development_cases.json').read_text())
    results={t:[run_case(c,t) for c in spec['cases']] for t in ['libra','conventional']}
    disagreement=[]
    for a,b in zip(results['libra'],results['conventional']):
        # Shared external projection, not equality of internal state or equations.
        for x,y in zip(a['steps'],b['steps']):
            if x['observed']!=y['observed']: disagreement.append([a['id'],x['step']])
    manifest={'study':'continuous supplied-event development comparison','human_validated':False,
        'new_model_calls':0,'python':platform.python_version(),'source_sha256':{
            str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.rglob('*')) if p.is_file() and p.suffix in {'.py','.json'} and 'results' not in p.parts}}
    out={'manifest':manifest,'summary':{t:summary(rows) for t,rows in results.items()},
         'paired_outcome_disagreements':disagreement,'results':results}
    (ROOT/'results'/'development_results.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({'summary':out['summary'],'disagreements':disagreement},indent=2))
    for t,rows in results.items():
        for r in rows:
            if not r['completed']:
                print(t,r['id'],[(s['step'],s['assessment']['failures'],s['error']) for s in r['steps'] if s['assessment']['failures']])
    return int(bool(disagreement) or any(not r['completed'] for rows in results.values() for r in rows))

if __name__=='__main__': raise SystemExit(main())
