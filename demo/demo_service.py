"""Stateless, bounded guided examples over the demonstration adapter.

Every request reconstructs a fresh synthetic interaction. No shared sessions,
credentials, model calls, user accounts, database or arbitrary code execution.
"""
from copy import deepcopy
from demo_engine import DemoEngine as Engine, visible_chat

MAX_ACTIONS = 32
PRESETS = {
    'start': {'title': 'Choose a product', 'description': 'First set the minimum sustainable share you want. Then compare the products and choose what matters most to you.'},
    'explanation': {'title': 'Ask for an explanation', 'description': 'Prepared example: D was chosen for lower cost. You suggested C instead. We deliberately paused an incomplete answer to your question.'},
    'adaptation': {'title': 'Try a temporary change', 'description': 'Prepared example: your usual minimum is 50%, which no product meets. You have proposed using 30% just for this conversation.'},
    'recovery': {'title': 'Change the facts', 'description': "Prepared example: D was chosen, but its disclosed sustainable share has fallen to 20%, below your 30% minimum. That recommendation is now suspended."},
    'sustainability': {'title': 'The other choice: C', 'description': 'This scripted example selects C after a confirmed sustainability priority. Both selection directions use the same confirmation and release controls.'},
}


def message(e, text, kind, payload=None, scope='unresolved', ref=None, **opts):
    return e.handle(text, {'kind': kind, 'payload': payload or {}, 'scope': scope,
                          'ref': ref, 'spans': [text]}, mode='supplied_event', **opts)


def supplied(e, key):
    if key.startswith('minimum_'):
        value = {'minimum_30': 30, 'minimum_40': 40, 'minimum_50': 50}[key]
        return message(e, f'I propose a standing minimum of {value}%.', 'propose_minimum',
                       {'minimum': value, 'mode': 'firm'}, 'standing')
    if key == 'search':
        return message(e, 'Search all four products while keeping my confirmed minimum.', 'search')
    if key in {'cost', 'sustainability'}:
        text = 'For this comparison, I prefer lower cost.' if key == 'cost' else 'For this comparison, I prefer the higher sustainability minimum.'
        return message(e, text, 'propose_priority', {'dimension': key},
                       e.comparison['id'] if e.comparison else 'unresolved')
    if key == 'adapt_30':
        return message(e, 'For this episode only, I propose a 30% minimum because no product meets my standing requirement.',
                       'propose_adaptation', {'minimum': 30, 'reason': 'No product meets the standing minimum; this adaptation is limited to this episode.'}, e.advice_id)
    if key in {'why', 'why_held'}:
        return message(e, 'Please explain the current recommendation.', 'why',
                       {'product': e.recommended}, **({'fault': 'omit_rival', 'fallback': False} if key.endswith('held') else {}))
    if key in {'challenge', 'challenge_held'}:
        rival = e.basis['rival'] if e.basis else 'C'
        return message(e, f'I advance {rival} as the alternative. Please explain the choice.', 'challenge',
                       {'rival': rival}, **({'fault': 'omit_rival', 'fallback': False} if key.endswith('held') else {}))
    if key == 'retract':
        rival = e.basis['rival'] if e.basis else 'C'
        return message(e, f'I withdraw my endorsement of {rival}.', 'retract', {'product': rival})
    if key == 'grounds':
        return message(e, 'Which evidence and confirmation support this decision?', 'question_ground')
    if key == 'text_accept':
        # A deliberately incorrect interpretation tests the confirmation boundary.
        return message(e, 'Yes, accept it.', 'confirm', scope=e.pending['scope'] if e.pending else 'unresolved',
                       ref=e.pending['id'] if e.pending else None)
    raise ValueError('Unknown scripted message')


MESSAGE_KEYS = {'minimum_30', 'minimum_40', 'minimum_50', 'search', 'cost', 'sustainability',
                'adapt_30', 'why', 'why_held', 'challenge', 'challenge_held', 'retract', 'grounds', 'text_accept'}
EXPERIMENT_KEYS = {'restore_d', 'lower_d', 'withdraw_support', 'end_episode', 'resume'}


def apply_action(e, action):
    if not isinstance(action, dict) or not isinstance(action.get('type'), str):
        raise ValueError('Each action must have a type')
    kind = action['type']
    if kind == 'message':
        if set(action) != {'type', 'key'} or action['key'] not in MESSAGE_KEYS:
            raise ValueError('Choose an available scripted message')
        return supplied(e, action['key'])
    if kind == 'confirmation':
        if set(action) != {'type', 'proposal_id', 'accept'} or type(action['accept']) is not bool:
            raise ValueError('A separate acceptance or decline is required')
        if not isinstance(action['proposal_id'], str) or len(action['proposal_id']) > 32:
            raise ValueError('Invalid proposal reference')
        result = e.confirm_control(action['proposal_id'], action['accept'])
        if not action['accept']:
            e.chat.append({'speaker': 'control', 'text': 'Displayed proposal declined. Confirmed preferences are unchanged.', 'mode': 'structured_control'})
        e.last_result = deepcopy(result)
        return result
    if kind == 'experiment':
        if set(action) != {'type', 'key'} or action['key'] not in EXPERIMENT_KEYS:
            raise ValueError('Unknown experiment control')
        key = action['key']
        if key == 'resume':
            return e.resume_justification()
        if key == 'withdraw_support':
            e.withdraw_support(); text = 'Supporting ground withdrawn. The recommendation is suspended and its history retained.'
        elif key == 'end_episode':
            e.end_advice(); text = 'Advice episode closed. Any temporary adaptation has expired; the standing minimum is retained.'
        else:
            value = 32 if key == 'restore_d' else 20
            e.update_evidence('D', 'minimum', value)
            text = f"Scripted evidence update: D's minimum is now {value}%. Previous comparison and recommendation records are archived."
        e.chat.append({'speaker': 'experiment', 'text': text, 'mode': 'test_injection'})
        e.last_result = {'status': 'applied'}
        return e.last_result
    raise ValueError('Unknown action type')


def setup(preset, tracker):
    e = Engine(tracker=tracker)
    if preset == 'start':
        return e
    def accept_fixture():
        # Fictional fixture consent is never inferred from language.
        return e.confirm_control(e.pending['id'], True)
    supplied(e, 'minimum_50' if preset == 'adaptation' else 'minimum_30')
    accept_fixture(); supplied(e, 'search')
    if preset == 'adaptation':
        supplied(e, 'adapt_30'); return e
    supplied(e, 'sustainability' if preset == 'sustainability' else 'cost')
    accept_fixture()
    if preset == 'explanation':
        supplied(e, 'challenge_held')
    elif preset == 'recovery':
        apply_action(e, {'type': 'experiment', 'key': 'lower_d'})
    return e


def result_for(e, preset, tracker, action_count):
    held = next((r for r in reversed(e.log) if r['kind'] == 'candidate_checked' and r['verdict'] == 'hold'), None)
    return {'demo': 'LIBRA-ADVICE', 'mode': 'scripted_interpretations', 'model_calls': 0,
            'preset': preset, 'presets': PRESETS, 'tracker': tracker,
            'action_count': action_count, 'max_actions': MAX_ACTIONS,
            'state': e.snapshot(), 'effective_minimum': e.effective_minimum(),
            'chat': visible_chat(e.chat), 'raw_chat':e.chat, 'last_result': e.last_result, 'held_candidate': held,
            'history': e.log, 'has_plan': bool(e.last_plan),
            'source': 'Evaluated runtime with a separate demonstration adapter; see ENGINE_PROVENANCE.json'}


def run_request(body):
    if not isinstance(body, dict) or set(body) - {'preset', 'tracker', 'actions'}:
        raise ValueError('Invalid demonstration request')
    preset, tracker, actions = body.get('preset', 'start'), body.get('tracker', 'libra'), body.get('actions', [])
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError('Unknown example')
    if tracker not in ('libra', 'conventional'):
        raise ValueError('Unknown tracker')
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise ValueError(f'An exploration supports at most {MAX_ACTIONS} actions. Start a new example to continue.')
    e = setup(preset, tracker)
    for action in actions:
        apply_action(e, action)
    return result_for(e,preset,tracker,len(actions))
