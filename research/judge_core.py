"""Executed exact-evidence validation and post-hoc repair rules; offline only."""
from copy import deepcopy
from collections import Counter
from judge_panel import aggregate

ARMS = ['llm_only','controller_only','conventional','libra']
PROVIDERS = ['openai','anthropic','google']
class JudgmentError(ValueError):
    pass

def validate_judgments(payload, cases, rubric):
    if not isinstance(payload, dict) or set(payload) != {"assessments"} or not isinstance(payload["assessments"], list):
        raise JudgmentError("Wrong top-level response")
    references = {c["case_id"]: {r["record_id"]: r["text"] for r in c["records"]} for c in cases}
    rows = {}
    for row in payload["assessments"]:
        if not isinstance(row, dict) or set(row) != {"case_id", "criteria"}:
            raise JudgmentError("Invalid assessment fields")
        identifier = row["case_id"]
        if not isinstance(identifier, str) or identifier not in references or identifier in rows:
            raise JudgmentError("Unknown or repeated case")
        if not isinstance(row["criteria"], dict) or set(row["criteria"]) != set(rubric["criteria"]):
            raise JudgmentError("Missing or unexpected criteria")
        for item in row["criteria"].values():
            if not isinstance(item, dict) or set(item) != {"verdict", "evidence", "reason"}:
                raise JudgmentError("Invalid criterion fields")
            if item["verdict"] not in rubric["verdicts"] or not isinstance(item["reason"], str) or not item["reason"].strip():
                raise JudgmentError("Invalid verdict or missing reason")
            if not isinstance(item["evidence"], list) or len(item["evidence"]) > 2:
                raise JudgmentError("Invalid evidence list")
            if item["verdict"] != "not_applicable" and not item["evidence"]:
                raise JudgmentError("Applicable verdict lacks evidence")
            for evidence in item["evidence"]:
                if not isinstance(evidence, dict) or set(evidence) != {"record_id", "quote"}:
                    raise JudgmentError("Invalid quote fields")
                ref, quote = evidence["record_id"], evidence["quote"]
                if not isinstance(ref, str) or ref not in references[identifier] or not isinstance(quote, str) or not quote.strip() or quote not in references[identifier][ref]:
                    raise JudgmentError("Evidence quote is not an exact substring of its cited record")
        rows[identifier] = row
    if set(rows) != set(references):
        raise JudgmentError("Missing assessments")
    return rows
def invalid_criteria(row, case):
    refs = {r['record_id']: r['text'] for r in case['records']}
    return [k for k, v in row['criteria'].items() if any(
        q['record_id'] not in refs or q['quote'] not in refs[q['record_id']] for q in v['evidence'])]

def validate_repair(payload, job, rubric):
    cid = job['record']['case_id']
    targets = job['record']['target_criteria']
    if not isinstance(payload, dict) or set(payload) != {'case_id', 'repairs'} or payload['case_id'] != cid:
        raise JudgmentError('Unexpected repair fields or item')
    if not isinstance(payload['repairs'], dict) or set(payload['repairs']) != set(targets):
        raise JudgmentError('Missing or extra repair criterion')
    derived = deepcopy(job['original_row']['assessment'])
    unsupported = []
    refs = {r['record_id']: r['text'] for r in job['case']['records']}
    for criterion, repair in payload['repairs'].items():
        if not isinstance(repair, dict) or set(repair) != {'support', 'evidence', 'note'} or not isinstance(repair['note'], str):
            raise JudgmentError('Invalid repair structure')
        evidence = repair['evidence']
        if not isinstance(evidence, list) or len(evidence) > 2:
            raise JudgmentError('Invalid evidence list')
        if repair['support'] == 'cannot_support':
            if evidence:
                raise JudgmentError('Unsupported decision must not supply evidence')
            unsupported.append(criterion)
            continue
        if repair['support'] != 'supported_by_source' or not evidence:
            raise JudgmentError('Missing support or exact evidence')
        for q in evidence:
            if not isinstance(q, dict) or set(q) != {'record_id', 'quote'}:
                raise JudgmentError('Invalid quote fields')
            if q['record_id'] not in refs or not isinstance(q['quote'], str) or not q['quote'].strip() or q['quote'] not in refs[q['record_id']]:
                raise JudgmentError('New quotation is not an exact source substring')
        derived['criteria'][criterion]['evidence'] = deepcopy(evidence)
    if unsupported:
        return None, unsupported
    validate_judgments({'assessments': [derived]}, [job['case']], rubric)
    # Only evidence in the selected invalid criteria may differ.
    restored = deepcopy(derived)
    for c in targets:
        restored['criteria'][c]['evidence'] = job['original_row']['assessment']['criteria'][c]['evidence']
    if restored != job['original_row']['assessment']:
        raise AssertionError('A verdict, reason or unrelated field changed')
    return derived, []
def check_envelope(payload, expected_ids):
    if not isinstance(payload, dict) or set(payload) != {'assessments'} or not isinstance(payload['assessments'], list):
        raise ValueError('Wrong response envelope')
    rows = payload['assessments']
    if any(not isinstance(r, dict) or set(r) != {'case_id', 'criteria'} or not isinstance(r['case_id'], str) for r in rows):
        raise ValueError('Malformed assessment envelope')
    ids = [r['case_id'] for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise ValueError('Missing, duplicated or unexpected item IDs')
    return rows

def summarize(data, assessed):
    mapping = {m['case_id']: m for m in data['item_mapping']}
    items = []
    for cid, m in mapping.items():
        rows = [r for r in assessed if r['case_id'] == cid and r['valid']]
        votes = [dict(r['assessment'], provider=r['provider'], model_id=r['returned_model']) for r in rows]
        items.append(dict(case_id=cid, scenario_id=m['scenario_id'], arm=m['arm'],
                          individual=votes, missing_providers=[p for p in PROVIDERS if not any(r['provider'] == p for r in rows)],
                          panel=aggregate(votes) if len(votes) == 3 else None))
    counts = {}
    for arm in ARMS:
        selected = [r for r in items if r['arm'] == arm]
        counts[arm] = {'complete_panels': sum(r['panel'] is not None for r in selected),
                       'scheduled_items': len(selected), 'criteria': {}}
        for criterion in data['rubric']['criteria']:
            cells = [r['panel']['criteria'][criterion] for r in selected if r['panel']]
            counts[arm]['criteria'][criterion] = {
                'individual_counts': {p: dict(Counter(v['criteria'][criterion]['verdict'] for r in selected for v in r['individual'] if v['provider'] == p)) for p in PROVIDERS},
                'majority_counts': dict(Counter(c['majority'] for c in cells)),
                'unanimous_cells': sum(c['unanimous'] for c in cells)}
    return {'items': items, 'counts_by_arm': counts,
            'complete_panels': sum(r['panel'] is not None for r in items),
            'valid_provider_item_assessments': sum(r['valid'] for r in assessed),
            'provider_item_counts': dict(Counter(r['provider'] for r in assessed if r['valid'])),
            'jointly_complete_scenarios': [sid for sid in sorted({r['scenario_id'] for r in items}) if
                all(r['panel'] is not None for r in items if r['scenario_id'] == sid)]}
