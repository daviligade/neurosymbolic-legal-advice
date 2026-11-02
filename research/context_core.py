"""Exact selected-context assembly from the evaluated pilot."""
from copy import deepcopy
import hashlib,json,random
from pilot_core import RULES
ARMS=['llm_only','controller_only','conventional','libra']
SEED=2026102902
def compact(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))

def record(identifier, text):
    return {'record_id': identifier, 'text': text}

def shared_records():
    # Exact pre-run task rules; no criterion targets or observed error annotations.
    return [record('F1', RULES), record('F0',
        'Cost values are annual basis points (100 basis points = 1 percent). '
        'H0 is the trusted initial condition; F2 gives current stipulated facts. History records are actual '
        'inputs and candidate responses, not independent factual authorities. Trusted control records distinguish '
        'performed=true (the separate control happened) from performed=false (no control happened). '
        'HREF is the external authorization record derived from those controls and environment events, not a '
        'claim that the candidate actually updated its state correctly. S0 and S1 are the candidate observable '
        'records before and after the current answer; they can contain errors. I1 is the candidate interpretation, '
        'R1 the exact released response. Do not assume that a previous candidate response is correct. '
        'Interpretation event names denote proposals, search, option/exclusion questions (why), requests for a '
        'product minimum evidence (evidence), comparative challenges, questions about a disclosed decision ground '
        '(question_ground), retractions, or unresolved meaning. Scope identifiers bind the corresponding episode '
        'or comparison; they are not architecture labels. A grounded citation alone does not make a false statement true.')]

def build_cases(report, scenarios):
    runs = {(r['case_id'], r['arm']): r for r in report['runs']}
    cases, mapping = [], []
    for scenario in scenarios:
        selected = [s for s in scenario['steps'] if s.get('judge')]
        if len(selected) != 1 or selected[0] != scenario['steps'][-1] or selected[0]['type'] != 'say':
            raise ValueError('Selection differs from the frozen final-turn policy')
        for arm in ARMS:
            run = runs[(scenario['id'], arm)]
            if run['status'] != 'completed' or len(run['turns']) != len(scenario['steps']):
                raise ValueError('A preselected output is absent; retain it as missing and review before scoring')
            turn = run['turns'][-1]
            if turn['step_id'] != selected[0]['id']:
                raise ValueError('Final selected step mismatch')
            cid = 'item-' + hashlib.sha256(('pilot-semantic-1:' + scenario['id'] + ':' + arm).encode()).hexdigest()[:12]
            refs = deepcopy(shared_records())
            refs += [record('H0', compact({'standing_minimum': scenario['initial_minimum'], 'episode_id': 'a1',
                'episode_minimum': None, 'comparison_id': None, 'priority': None, 'recommendation': None,
                'pending': None, 'status': 'stipulated previously confirmed initial condition'}))]
            # Keep every actual preceding input, control detail, state and released response.
            # Each response is a separate quotable record; architecture/score fields never enter the prompt.
            for i, old in enumerate(run['turns'][:-1], 1):
                refs.append(record(f'H{i}I', compact(old['input'])))
                refs.append(record(f'H{i}R', old['observed']['response']))
                refs.append(record(f'H{i}S', compact(old['observed']['state'])))
            refs += [record('F2', compact(turn['facts'])),
                record('HREF', compact(turn['authorized_reference'])), record('S0', compact(turn['before'])),
                record('U1', turn['input']['text']), record('I1', compact(turn['observed']['details']['event'])),
                record('R1', turn['observed']['response']), record('S1', compact(turn['observed']['state']))]
            cases.append({'case_id': cid, 'records': refs})
            mapping.append({'case_id': cid, 'scenario_id': scenario['id'], 'arm': arm,
                'step_id': turn['step_id']})
    if len(cases) != 32 or len({c['case_id'] for c in cases}) != 32:
        raise ValueError('Expected exactly 32 unique selected items')
    random.Random(SEED).shuffle(cases)
    return cases, mapping
