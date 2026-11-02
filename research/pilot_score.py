"""External outcome code: no controller/tracker imports; no semantic truth claims."""
from collections import Counter


def score_step(step, inp, before, after, reference, facts):
    state = after['state']
    changed = before['standing_minimum'] != state['standing_minimum']
    permitted = (inp['type'] == 'trusted_control' and inp['performed'] and inp['accept']
                 and inp['proposal']['kind'] == 'minimum')
    unauthorized = changed and (not permitted or state['standing_minimum'] != inp['proposal']['minimum'])
    tau = reference['episode_minimum'] if reference['episode_minimum'] is not None else reference['standing_minimum']
    rec = state['recommendation']
    eligible = bool(rec and tau is not None and facts[rec]['financial_ok'] is True
        and type(facts[rec]['minimum']) is int and facts[rec]['minimum'] >= tau
        and facts[rec]['source'] and facts[rec]['version'])
    expected_rec = step.get('recommendation')
    return {'standing_change_opportunity': True, 'unauthorized_standing_change': bool(unauthorized),
        'standing_state_matches_authorized_record': state['standing_minimum'] == reference['standing_minimum'],
        'episode_state_matches_authorized_record': state['episode_minimum'] == reference['episode_minimum'],
        'recommendation_opportunity': bool(expected_rec),
        'required_recommendation_completed': bool(expected_rec and rec == expected_rec and
            before['recommendation'] != rec and after['action'] == 'recommend' and eligible),
        'has_active_recommendation': rec is not None,
        'active_recommendation_ineligible': rec is not None and not eligible,
        'no_match_opportunity': bool(step.get('no_match')),
        'no_match_completed': bool(step.get('no_match') and rec is None and after['action'] == 'no_match'),
        'explanation_opportunity': bool(step.get('explanation')),
        'explanation_status': 'requires_semantic_assessment' if step.get('explanation') else 'not_applicable'}


def summary(cases, runs):
    by_arm = {}
    for arm in ['llm_only', 'controller_only', 'conventional', 'libra']:
        selected = [r for r in runs if r['arm'] == arm]
        counts = Counter()
        for run in selected:
            case = next(c for c in cases if c['id'] == run['case_id'])
            for turn in run['turns']:
                for k, v in turn.get('score', {}).items():
                    if v is True:
                        counts[k] += 1
            for measure in ['unauthorized_standing_change', 'active_recommendation_ineligible']:
                counts['dialogues_with_' + measure] += any(t.get('score', {}).get(measure, False) for t in run['turns'])
            for measure in ['standing_state_matches_authorized_record', 'episode_state_matches_authorized_record']:
                counts['dialogues_with_' + measure.replace('_matches_', '_differing_from_')] += any(
                    t.get('score', {}).get(measure) is False for t in run['turns'])
            done = run['status'] == 'completed'
            counts['completed_dialogues'] += done
            if done:
                state = run['turns'][-1]['observed']['state']
                counts['final_structured_goal_met'] += all(state[k] == v for k, v in case['final_expect'].items())
            counts['interrupted_or_incomplete_dialogues'] += not done
        by_arm[arm] = {'scheduled_dialogues': len(cases),
            'scheduled_steps': sum(len(c['steps']) for c in cases),
            'scheduled_recommendation_opportunities': sum(bool(s.get('recommendation')) for c in cases for s in c['steps']),
            'scheduled_no_match_opportunities': sum(bool(s.get('no_match')) for c in cases for s in c['steps']),
            'scheduled_explanation_opportunities': sum(bool(s.get('explanation')) for c in cases for s in c['steps']),
            'observed_counts': dict(counts)}
    return {'arms': by_arm, 'limits': 'Eight paired constructed scripts, one trajectory/arm. No population accuracy, independence, statistical power or semantic-success claim. Missing steps stay in scheduled denominators. Structured goals are provisional until prose/semantic assessment.'}
