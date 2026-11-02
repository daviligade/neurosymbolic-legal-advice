"""Offline aggregation of three-provider judgments; never calls any API."""
from collections import Counter
import json
from pathlib import Path

RUBRIC=json.loads(Path(__file__).with_name('judge_rubric.json').read_text())
PROVIDERS=set(RUBRIC['providers'])
CRITERIA=set(RUBRIC['criteria'])
LABELS=set(RUBRIC['verdicts'])


def majority(labels):
    counts=Counter(labels)
    for label in ['pass','fail']:
        if counts[label]>len(labels)/2:
            return label
    if counts['not_applicable']==len(labels):
        return 'not_applicable'
    return 'unresolved'


def aggregate(records):
    if len(records)!=3 or {r.get('provider') for r in records}!=PROVIDERS:
        raise ValueError('exactly one separate judgment from each configured provider is required')
    if len({r.get('case_id') for r in records})!=1 or not records[0].get('case_id'):
        raise ValueError('all judgments must refer to one named case')
    for r in records:
        if not r.get('model_id') or set(r.get('criteria',{}))!=CRITERIA:
            raise ValueError('versioned model and all rubric criteria required')
        for item in r['criteria'].values():
            if item.get('verdict') not in LABELS or not isinstance(item.get('evidence'),list) or not isinstance(item.get('reason'),str):
                raise ValueError('invalid criterion judgment')
    combined={}
    for criterion in sorted(CRITERIA):
        votes={r['provider']:r['criteria'][criterion]['verdict'] for r in records}
        combined[criterion]={'votes':votes,'majority':majority(list(votes.values())),
            'unanimous':len(set(votes.values()))==1,
            'leave_one_provider_out':{p:majority([v for q,v in votes.items() if q!=p]) for p in sorted(PROVIDERS)}}
    return {'case_id':records[0]['case_id'],'criteria':combined,
        'interpretation':'Model agreement only; not independent human validation or a truth certificate.'}
