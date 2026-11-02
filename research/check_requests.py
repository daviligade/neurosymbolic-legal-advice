"""Compare request persistence using four existing cases, without model calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'demo'))
from advice.engine import Engine
from pilot_core import ControllerOnly
from run_study import execute_step, observe
from outcomes import assess_step


def evaluate():
    cases = [case for case in json.loads((ROOT / 'development_cases.json').read_text())['cases']
             if case['family'] in {'interrupted_challenge', 'overlapping_requests'}]
    if len(cases) != 4:
        raise ValueError('Expected two request patterns with two preference variants each.')
    factories = {
        'controller_only': lambda: ControllerOnly(protocol_enabled=False),
        'conventional': lambda: Engine(tracker='conventional'),
        'libra': lambda: Engine(tracker='libra'),
    }
    summaries, runs = {}, []
    for arm, create in factories.items():
        arm_runs = []
        for case in cases:
            engine, context, rows = create(), {}, []
            for index, step in enumerate(case['steps'], 1):
                before = observe(engine)
                try:
                    result = execute_step(engine, step, context)
                except (ValueError, KeyError, TypeError) as error:
                    result = {'status': 'rejected', 'event_accepted': False,
                              'error': str(error)}
                observed = observe(engine, result)
                assessment = assess_step(step, before, observed)
                error = result.get('error') or result.get('event_error')
                # Removal may affect request records and resumption, not other checks.
                allowed = {'targets'} if arm == 'controller_only' else set()
                if arm == 'controller_only' and step['op'] == 'resume':
                    allowed.add('status')
                    if error != 'no outstanding adviser target':
                        raise ValueError('Unexpected result from resumption without a tracker.')
                elif error:
                    raise ValueError(f'Unexpected error in {arm}, {case["id"]}: {error}')
                if any(f['field'] not in allowed for f in assessment['failures']):
                    raise ValueError(f'Unexpected checkpoint failure in {arm}, {case["id"]}.')
                rows.append({'step': index, 'input': deepcopy(step), 'observed': observed,
                             'assessment': assessment, 'error': error})
            arm_runs.append({'case': case['id'], 'arm': arm, 'steps': rows,
                             'all_checkpoints_met': all(not r['assessment']['failures'] for r in rows)})
        rows = [row for run in arm_runs for row in run['steps']]
        selections = [r for r in rows if r['input'].get('recommendation_opportunity')]
        incomplete = [r for r in rows if r['input'].get('fault') == 'omit_rival']
        resumed = [r for r in rows if r['input']['op'] == 'resume']
        summaries[arm] = {
            'cases': len(arm_runs),
            'cases_meeting_all_checkpoints': sum(r['all_checkpoints_met'] for r in arm_runs),
            'initial_selections_correct': sum(r['assessment']['correct_new_recommendation'] for r in selections),
            'initial_selection_opportunities': len(selections),
            'incomplete_replies_held': sum(r['observed']['status'] == 'held' for r in incomplete),
            'incomplete_reply_checks': len(incomplete),
            'resumption_attempts': len(resumed),
            'resumptions_releasing_answer': sum(r['observed']['status'] == 'released' for r in resumed),
        }
        runs.extend(arm_runs)
    return {
        'method': 'Additional deterministic comparison using four existing cases and unchanged controller and reply rules.',
        'scope': 'Explicit pending-request records and resumption through the application interface; no reconstruction from transcript text.',
        'new_model_calls': 0, 'summary': summaries, 'runs': runs,
    }


def main():
    report = evaluate()
    expected = json.loads((ROOT / 'data/reported_results.json').read_text())['request_tracking']
    if report['summary'] != expected:
        raise ValueError('Request-tracking results differ from the reported values.')
    output = ROOT / 'results'
    output.mkdir(exist_ok=True)
    (output / 'request_results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('VERIFIED: four existing cases per configuration; explanations resumed: '
          'controller only 0/6, Alternative 6/6, Libra 6/6. No model calls.')


if __name__ == '__main__':
    main()
