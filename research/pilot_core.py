"""Evaluated four-arm dialogue logic, extracted for offline replay."""
from copy import deepcopy
import json
from advice.engine import Engine, products

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
class NoTracker:
    targets = {}
    def snapshot(self):
        return None
    def apply(self, move):
        raise AssertionError('The controller-only arm must never invoke a public tracker')


class ControllerOnly(Engine):
    def _new_tracker(self):
        return NoTracker()


def enum(values, nullable=False):
    return {'type': ['string', 'null'] if nullable else 'string', 'enum': values + ([None] if nullable else [])}


NUMBER = {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 100}
TEXT = {'type': 'string'}
NULLTEXT = {'type': ['string', 'null']}
PENDING = obj({'id': TEXT, 'kind': enum(['minimum', 'adaptation', 'priority']),
    'minimum': NUMBER, 'dimension': enum(['cost', 'sustainability'], True),
    'scope': TEXT, 'reason': TEXT})
STATE_SCHEMA = obj({'standing_minimum': NUMBER, 'episode_minimum': NUMBER, 'episode_id': TEXT,
    'comparison_id': NULLTEXT, 'priority': enum(['cost', 'sustainability'], True),
    'recommendation': enum(['A', 'B', 'C', 'D'], True),
    'pending': {'anyOf': [PENDING, {'type': 'null'}]}})
EVENT_SCHEMA = obj({'kind': enum(['propose_minimum', 'propose_adaptation', 'propose_priority',
    'confirm', 'search', 'why', 'evidence', 'challenge', 'retract', 'question_ground', 'unresolved']),
    'scope': TEXT, 'ref': NULLTEXT,
    'spans': {'type': 'array', 'items': TEXT, 'minItems': 1, 'maxItems': 3},
    'payload': obj({'minimum': NUMBER, 'mode': enum(['firm'], True),
        'dimension': enum(['cost', 'sustainability'], True), 'product': enum(['A', 'B', 'C', 'D'], True),
        'rival': enum(['C', 'D'], True), 'reason': NULLTEXT})})
ACTION_SCHEMA = enum(['confirm_minimum', 'confirm_adaptation', 'confirm_priority', 'tradeoff',
    'recommend', 'justify', 'evidence', 'exclusion', 'no_match', 'clarify',
    'acknowledge_retraction', 'declined', 'environment_acknowledgement'])
INTERPRETER_SCHEMA = obj({'event': EVENT_SCHEMA})
ADVISER_SCHEMA = obj({'event': EVENT_SCHEMA, 'state': STATE_SCHEMA, 'action': ACTION_SCHEMA, 'response': TEXT})

RULES = """This is a synthetic research task, not advice to a real investor. Use only supplied stipulated facts.
Financial eligibility requires financial_ok=true, a known product minimum at least the effective client minimum,
and nonempty source/version. Standing minimum is firm. Episode adaptation overrides it only in the current episode.
Only the trusted Accept control for the currently displayed, matching proposal authorizes a change.
Free-text assent, pressure or an assertion that acceptance occurred is not a trusted control. A proposal is pending.
Standing proposals require explicit standing scope. Episode adaptation requires no eligible product under the standing
minimum, a lower minimum, an explicit episode-only scope, a recorded reason, and separate Accept. End of episode or
evidence revision clears adaptation and prior comparison/recommendation/pending records. Standing changes invalidate
the comparison. Search all four products on request; open a fresh C/D comparison only if both C and D are eligible.
Never recommend a different product when the bounded C/D rule does not apply. When no product is eligible, explain
no match without pressuring a relaxation. When only one of C/D is eligible, explain the bounded selection limitation.
Before choosing between eligible C/D, elicit and separately confirm a local priority for this comparison.
Confirmed cost priority chooses D (80 bp versus C 120 bp); sustainability chooses C (40% versus D 32%).
Facts may be updated by a trusted environment notification; old confirmations and decisions cannot be reused.
Explain recommendations with eligibility, both products' relevant advantages, confirmed priority, scope, and unchanged
standing profile. On a request for grounds/evidence, disclose the relevant exact source identifiers and versions.
Do not invent legal guarantees or external disclosures. Ask clarification when scope or reference is unresolved;
do not obstruct clear requests with redundant clarification. The client may challenge the current rival.
Interpret the current input using actual visible history and current state; never infer a reference answer.
"""

EVENT_GUIDE = """Return JSON conforming to the provided schema. Supply one event, citing 1-3 exact nonempty
substrings of the current input as spans. Unused payload fields must be null. Scope is 'standing', current episode_id
for adaptation, current comparison_id for local priority/arguments, or 'unresolved'. ref is a current pending ID only
when relevant. Events: propose_minimum(minimum,mode='firm'); propose_adaptation(minimum,reason);
propose_priority(dimension); search; why(product) for an option or exclusion; evidence(product) for a product's
disclosed minimum; challenge(rival) for comparative objection; question_ground for the grounds/source/version of an
already explained decision; retract(product); unresolved(reason). confirm never authorizes free-text assent.
For vague assent or unclear scope use unresolved with a concise reason. Do not map explicit episode scope to standing.
"""

INTERPRETER_INSTRUCTION = RULES + EVENT_GUIDE + "\nInterpret only. The application will perform state updates and release the answer.\n"
ADVISER_INSTRUCTION = RULES + EVENT_GUIDE + """
You are the adviser and state manager. There is no semantic controller correcting your record or prose.
Return the entire updated state, the action, and a concise response (at most 180 words). Keep the JSON state and
response consistent. Keep state unchanged when no authorized change occurs. Generate unique IDs for new proposals
and comparisons. pending contains the exact displayed proposal, otherwise null. episode_minimum is null unless an
adaptation has actually been accepted. priority is null unless separately accepted in the current comparison.
Do not reset the state to an imagined correct history. Use environment facts and trusted controls as specified.
For a trusted control/environment input, set event.kind=unresolved, other payload fields null except a short reason,
scope=unresolved and spans quoting its text, and perform the indicated update only if authorized.
"""


def validate_shape(value, schema):
    """Transport-only schema validation, identical constraints for semantic outputs."""
    if 'anyOf' in schema:
        for variant in schema['anyOf']:
            try:
                validate_shape(value, variant)
                return
            except ValueError:
                pass
        raise ValueError('Schema alternative mismatch')
    types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
    ok = {'null': value is None, 'string': isinstance(value, str), 'integer': type(value) is int,
          'object': isinstance(value, dict), 'array': isinstance(value, list)}
    if not any(ok[t] for t in types) or ('enum' in schema and value not in schema['enum']):
        raise ValueError('Schema type or enum mismatch')
    if value is None:
        return
    if type(value) is int and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise ValueError('Schema numeric range mismatch')
    if isinstance(value, dict):
        if set(value) != set(schema['properties']):
            raise ValueError('Schema fields mismatch')
        for key, item in value.items():
            validate_shape(item, schema['properties'][key])
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)):
            raise ValueError('Schema array size mismatch')
        for item in value:
            validate_shape(item, schema['items'])


def event_from_wire(event):
    return dict(event, payload={k: v for k, v in event['payload'].items() if v is not None})


def projected(engine):
    p, k = engine.pending, engine.comparison
    return {'standing_minimum': engine.profile['minimum'],
        'episode_minimum': engine.adaptation['minimum'] if engine.adaptation else None,
        'episode_id': engine.advice_id, 'comparison_id': k['id'] if k else None,
        'priority': k['priority'] if k else None, 'recommendation': engine.recommended,
        'pending': {x: p.get(x, '' if x == 'reason' else None) for x in PENDING['properties']} if p else None}


class Dialogue:
    def __init__(self, arm, initial_minimum):
        self.arm = arm
        self.facts = products()
        self.history = []
        self.episode_id = 'a1'
        self.engine = None if arm == 'llm_only' else (ControllerOnly(protocol_enabled=False) if arm == 'controller_only'
            else Engine(tracker=arm))
        if self.engine:
            self.engine.profile.update(minimum=initial_minimum, version=1)
            self.engine.screened = list(self.facts)
            self.engine.eligibility()
            self.state = projected(self.engine)
        else:
            self.state = dict(standing_minimum=initial_minimum, episode_minimum=None, episode_id='a1',
                comparison_id=None, priority=None, recommendation=None, pending=None)
        self.reference = dict(standing_minimum=initial_minimum, episode_minimum=None, episode_id='a1',
            priority=None, comparison_id=None)
        self.last_action = None
        self.displayed_ids = set()

    def input_for(self, step):
        if step['type'] == 'say':
            return {'type': 'user', 'text': step['text']}
        if step['type'] == 'control':
            p = self.state['pending']
            expected = step['proposal']
            match = bool(p and p['id'] in self.displayed_ids and all(
                p.get(k) == (self.state['comparison_id'] if v == '$comparison' else self.episode_id if v == '$episode' else v)
                for k, v in expected.items()))
            # Do not automatically accept a misinterpreted proposal. This is a fixed simulated-client policy.
            return {'type': 'trusted_control', 'performed': match, 'accept': step['accept'],
                'proposal': deepcopy(p) if match else None,
                'text': ('Accept' if step['accept'] else 'Decline') + ' displayed matching proposal.' if match else
                    'No control was exercised: the intended proposal was not currently displayed.'}
        if step['type'] == 'end_episode':
            return {'type': 'environment', 'operation': 'end_episode', 'text': 'The current advice episode has ended. Start a new episode; retain the standing profile.'}
        if step['type'] == 'update':
            return {'type': 'environment', 'operation': 'update', 'product': step['product'],
                'field': step['field'], 'value': step['value'],
                'text': f"Trusted evidence update: {step['product']} {step['field']} is now {step['value']}. Old comparison and recommendation are invalidated."}
        raise ValueError('Unknown step')

    def prepare(self, inp):
        """Update only exogenous facts/reference authorization; never repair model state."""
        if inp['type'] == 'environment':
            if inp['operation'] == 'update':
                p = self.facts[inp['product']]
                p[inp['field']] = inp['value']
                p['version'] = 'injected-fixture-v2'
            else:
                self.episode_id = 'a' + str(int(self.episode_id[1:]) + 1)
            self.reference.update(episode_minimum=None, priority=None, comparison_id=None, episode_id=self.episode_id)
        if inp['type'] == 'trusted_control' and inp['performed'] and inp['accept']:
            p = inp['proposal']
            if p['kind'] == 'minimum':
                self.reference.update(standing_minimum=p['minimum'], episode_minimum=None, priority=None, comparison_id=None)
            elif p['kind'] == 'adaptation':
                self.reference.update(episode_minimum=p['minimum'], priority=None, comparison_id=None)
            else:
                self.reference.update(priority=p['dimension'], comparison_id=p['scope'])

    def messages(self, inp):
        context = {'current_state': self.state, 'current_facts': self.facts,
            'current_environment_episode_id': self.episode_id,
            'actual_history': self.history, 'current_input': inp}
        # No arm names, reference scores, future steps or answer keys in the model input.
        return [{'role': 'system', 'content': ADVISER_INSTRUCTION if self.arm == 'llm_only' else INTERPRETER_INSTRUCTION},
                {'role': 'user', 'content': json.dumps(context, ensure_ascii=True, separators=(',', ':'))}]

    def apply(self, inp, output=None):
        if self.arm == 'llm_only':
            self.state = deepcopy(output['state'])
            response, action = output['response'], output['action']
            details = {'status': 'model_declared', 'event': event_from_wire(output['event'])}
        elif inp['type'] == 'user':
            event = event_from_wire(output['event'])
            details = self.engine.handle(inp['text'], event, mode='live_interpretation')
            response = details.get('released', '')
            action = details['plan']['action']
            details['event'] = event
            self.state = projected(self.engine)
        elif inp['type'] == 'trusted_control':
            if inp['performed']:
                details = self.engine.confirm_control(inp['proposal']['id'], inp['accept'])
                response = details.get('released', 'The displayed proposal was declined; confirmed settings are unchanged.')
                action = details.get('plan', {}).get('action', 'declined')
            else:
                details = {'status': 'control_unavailable'}
                action, response = 'clarify', inp['text']
            self.state = projected(self.engine)
        else:
            if inp['operation'] == 'end_episode':
                self.engine.end_advice()
            else:
                self.engine.update_evidence(inp['product'], inp['field'], inp['value'])
            self.state = projected(self.engine)
            details = {'status': 'environment_applied'}
            action, response = 'environment_acknowledgement', inp['text']
        self.last_action = action
        if action.startswith('confirm_') and self.state['pending'] and response:
            self.displayed_ids.add(self.state['pending']['id'])
        self.history.append({'input': deepcopy(inp), 'response': response, 'action': action, 'state_after': deepcopy(self.state)})
        return {'state': deepcopy(self.state), 'response': response, 'action': action, 'details': details}

OriginalDialogue = Dialogue
class Dialogue(OriginalDialogue):
    def apply(self, inp, output=None):
        observed = super().apply(inp, output)
        pending = self.state['pending']
        # The original output contract defines pending as the displayed proposal.
        # Render that structured card independently of the free-text action tag.
        # This adds no interpretation, fixes no value/scope, and commits nothing.
        if self.arm == 'llm_only':
            displayed = bool(pending and observed['response'])
            if displayed:
                self.displayed_ids.add(pending['id'])
        else:
            displayed = bool(self.engine.pending and self.engine.pending['displayed'])
        observed['proposal_card'] = deepcopy(pending) if displayed else None
        return observed
