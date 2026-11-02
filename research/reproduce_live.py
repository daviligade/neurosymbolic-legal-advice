"""Offline reproduction of saved trajectories and original/post-hoc judge analyses."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from pilot_core import Dialogue, OriginalDialogue, ADVISER_SCHEMA, INTERPRETER_SCHEMA, validate_shape
from pilot_score import score_step, summary
from context_core import build_cases
from judge_core import JudgmentError, validate_judgments, validate_repair, invalid_criteria, check_envelope, summarize, PROVIDERS, ARMS
from judge_panel import aggregate
ROOT=Path(__file__).resolve().parent

def read(name):return json.loads((ROOT/'data'/name).read_text())
def require(value,message):
    if not value:raise ValueError(message)
def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for v in value.values():yield from strings(v)
    elif isinstance(value,list):
        for v in value:yield from strings(v)

def replay(name,corrected):
    saved=read(name);cases=read('scenarios.json')['cases'];runs=[]
    requests={r['id']:r for r in saved['requests']};used=[]
    require(len(requests)==131,'Wrong pilot request count')
    require(len(saved['runs'])==32 and len({(r['case_id'],r['arm']) for r in saved['runs']})==32,'Pilot coverage differs')
    for source in saved['runs']:
        case=next(c for c in cases if c['id']==source['case_id'])
        d=(Dialogue if corrected else OriginalDialogue)(source['arm'],case['initial_minimum'])
        run={'case_id':source['case_id'],'arm':source['arm'],'status':'completed','turns':[]}
        require(len(source['turns'])==len(case['steps']),'Missing pilot steps')
        for step,old in zip(case['steps'],source['turns']):
            before=deepcopy(d.state);inp=d.input_for(step);d.prepare(inp)
            row={'step_id':step['id'],'input':inp,'before':before,'authorized_reference':deepcopy(d.reference),'facts':deepcopy(d.facts)}
            output=None
            if source['arm']=='llm_only' or inp['type']=='user':
                req=requests[old['request_key']];used.append(req['id']);result=req['result']
                require(req['request_body']['messages']==d.messages(inp),'Recorded prompt context differs')
                output=json.loads(result['raw_text'])
                require(output==result['output']==old['model_output'],'Raw model output differs')
                validate_shape(output,ADVISER_SCHEMA if source['arm']=='llm_only' else INTERPRETER_SCHEMA)
                row.update(request_key=req['id'],generation_status=result['status'],model_output=output)
            observed=d.apply(inp,output);row['observed']=observed
            row['score']=score_step(step,inp,before,observed,d.reference,d.facts)
            require(row==old,'A recorded trajectory cannot be reproduced')
            run['turns'].append(row)
        runs.append(run)
    require(set(used)==set(requests) and len(used)==131,'Unused or duplicated pilot requests')
    analysed=summary(cases,runs);require(analysed==saved['reported_analysis'],'Pilot aggregate differs')
    return {'runs':runs,'analysis':analysed}

def judge_analysis(corrected):
    data=read('judge_inputs.json');responses=read('judge_responses.json')['requests']
    rebuilt,mapping=build_cases(corrected,read('scenarios.json')['cases'])
    require(rebuilt==data['cases'],'Judge records differ from replayed trajectories')
    for m in mapping:m.pop('source',None)
    require(mapping==data['item_mapping'],'Blinding map differs')
    primary=[];item=[];case_lookup={c['case_id']:c for c in data['cases']}
    require(len(responses)==39 and len({(r['batch_id'],r['provider']) for r in responses})==39,'Judge request coverage differs')
    for r in responses:
        batch=next(b for b in data['batches'] if b['batch_id']==r['batch_id'])
        require(batch['prompt'] in set(strings(r['request_body'])),'Judge prompt differs')
        payload=json.loads(r['result']['raw_text']);rows=check_envelope(payload,{c['case_id'] for c in batch['cases']})
        try:validate_judgments(payload,batch['cases'],data['rubric']);batch_valid=True
        except JudgmentError:batch_valid=False
        require(batch_valid==(r['status']=='valid_judgments'),'Original batch status differs')
        for row in rows:
            try:validate_judgments({'assessments':[row]},[case_lookup[row['case_id']]],data['rubric']);valid=True
            except JudgmentError:valid=False
            base={'case_id':row['case_id'],'provider':r['provider'],'returned_model':r['result']['returned_model'],'assessment':row}
            primary.append(dict(base,valid=batch_valid));item.append(dict(base,valid=valid))
    primary_result=summarize(data,primary);item_result=summarize(data,item)
    recovered=deepcopy(item);repair_data=read('evidence_recovery.json');repairs=repair_data['requests']
    require(len(repair_data['initial_rejected_request'])==1 and repair_data['initial_rejected_request'][0]['status']=='http_error','Missing rejected request')
    needed={(r['case_id'],r['provider']) for r in item if not r['valid']}
    require(len(repairs)==7 and {(r['case_id'],r['provider']) for r in repairs}==needed,'Repair selection differs')
    failures=[]
    for r in repairs:
        original=next(x for x in recovered if x['case_id']==r['case_id'] and x['provider']==r['provider'])
        case=case_lookup[r['case_id']];targets=invalid_criteria(original['assessment'],case)
        require(targets==r['target_criteria'],'Recovery selected different criteria')
        job={'record':{'case_id':r['case_id'],'target_criteria':targets},'original_row':original,'case':case}
        try:
            derived,unsupported=validate_repair(json.loads(r['result']['raw_text']),job,data['rubric'])
            if derived:original.update(assessment=derived,valid=True)
            else:failures.append({'case_id':r['case_id'],'provider':r['provider'],'unsupported':unsupported})
        except JudgmentError as error:failures.append({'case_id':r['case_id'],'provider':r['provider'],'validation_error':str(error)})
    result=summarize(data,recovered)
    for row in recovered:
        prior=next(x for x in item if x['case_id']==row['case_id'] and x['provider']==row['provider'])
        for c in data['rubric']['criteria']:
            for field in ['verdict','reason']:require(row['assessment']['criteria'][c][field]==prior['assessment']['criteria'][c][field],'Original decision changed')
    complete=[r for r in result['items'] if r['panel']];cells=[c for row in complete for c in row['panel']['criteria'].values()];paired=result['jointly_complete_scenarios']
    return {'primary_complete_panels':primary_result['complete_panels'],'item_level_complete_panels':item_result['complete_panels'],
      'recovered_complete_panels':result['complete_panels'],'valid_provider_item_assessments':result['valid_provider_item_assessments'],
      'counts_by_arm':result['counts_by_arm'],'jointly_complete_scenarios':paired,
      'paired_evidence_majorities':{a:dict(Counter(r['panel']['criteria']['evidence_faithfulness']['majority'] for r in complete if r['arm']==a and r['scenario_id'] in paired)) for a in ARMS},
      'criterion_cells':len(cells),'unanimous_cells':sum(c['unanimous'] for c in cells),'majority_counts':dict(Counter(c['majority'] for c in cells)),
      'leave_one_provider_out_changed_cells':{p:sum(c['leave_one_provider_out'][p]!=c['majority'] for c in cells) for p in PROVIDERS},
      'remaining_exclusions':failures,'original_verdicts_and_reasons_unchanged':True}

def calibration():
    data=read('calibration.json');rubric=read('judge_inputs.json')['rubric'];key=data['answer_key'];out={};votes={}
    for r in data['requests']:
        rows=validate_judgments(json.loads(r['result']['raw_text']),data['cases'],rubric);checks=0
        for cid,target in key['targets'].items():
            for c,accepted in target['expected'].items():
                checks+=1;require(rows[cid]['criteria'][c]['verdict'] in accepted,'Calibration target differs')
        for a,b in key['invariance_pairs']:require(all(rows[a]['criteria'][c]['verdict']==rows[b]['criteria'][c]['verdict'] for c in rubric['criteria']),'Calibration invariance differs')
        out[r['provider']]={'target_matches':checks,'stable_paraphrase_pairs':len(key['invariance_pairs'])}
        votes[r['provider']]={cid:dict(row,provider=r['provider'],model_id=r['result']['returned_model']) for cid,row in rows.items()}
    require(set(out)==set(PROVIDERS),'Calibration provider missing')
    panels=[aggregate([votes[p][c['case_id']] for p in PROVIDERS]) for c in data['cases']];cells=[v for panel in panels for v in panel['criteria'].values()]
    return {'providers':out,'unanimous_cells':sum(c['unanimous'] for c in cells),'majority_counts':dict(Counter(c['majority'] for c in cells))}

def main():
    initial=replay('pilot_initial.json',False);corrected=replay('pilot_corrected.json',True)
    result=judge_analysis(corrected);expected=read('reported_results.json')
    for k in result:
        if k in expected:require(result[k]==expected[k],'Reported '+k+' differs')
    sensitivity=metric_sensitivity(corrected,read('scenarios.json')['cases'])
    require(sensitivity==expected['recommendation_metric_sensitivity'],'Metric sensitivity differs')
    output={'initial_pilot':initial['analysis'],'corrected_pilot':corrected['analysis'],'calibration':calibration(),
            'judges':result,'recommendation_sensitivity':sensitivity,'new_model_calls':0}
    (ROOT/'results').mkdir(exist_ok=True);(ROOT/'results/live_results.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    print('VERIFIED: 64 trajectories, 262 saved generations, calibration, 39 judge batches, 7 evidence follow-ups.')
    print('Complete panels: 22 original, 26 item-level, 31 recovered. Valid judgments: 95/96. Original decisions unchanged.')
    return output


def metric_sensitivity(report, cases):
    rows = []
    case_map = {c['id']: c for c in cases}
    for run in report['runs']:
        specs = {s['id']: s for s in case_map[run['case_id']]['steps']}
        for i, turn in enumerate(run['turns']):
            expected = specs[turn['step_id']].get('recommendation')
            if not expected:
                continue
            def eligible_record(t):
                return (t['observed']['state']['recommendation'] == expected and
                        not t['score']['active_recommendation_ineligible'])
            immediate = (eligible_record(turn) and
                         turn['before']['recommendation'] != expected)
            window = [turn]
            for later in run['turns'][i + 1:]:
                if specs[later['step_id']]['type'] in ('evidence', 'end_episode'):
                    break
                window.append(later)
            eventual = any(eligible_record(t) and t['before']['recommendation'] != expected for t in window)
            rows.append({'arm': run['arm'], 'scenario_id': run['case_id'],
                         'step_id': turn['step_id'], 'product': expected,
                         'frozen_strict': turn['score']['required_recommendation_completed'],
                         'posthoc_state_at_opportunity': immediate,
                         'posthoc_state_before_environment': eventual})
    return {'definitions': 'Strict frozen action+new eligible record; post-hoc remove action label; post-hoc allow later new eligible record before evidence/episode change. These are overlapping descriptive checks, not additional samples.',
            'opportunities': rows,
            'counts': {a: {k: sum(r[k] for r in rows if r['arm'] == a)
                          for k in ['frozen_strict', 'posthoc_state_at_opportunity', 'posthoc_state_before_environment']}
                       for a in ARMS}}

if __name__=='__main__':main()
