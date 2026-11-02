"""Common outcome checker. Does not import either controller or either tracker.

The explicit expected checkpoints are in development_cases.json. This code
checks structured outcomes and literal evidence disclosure, not legal adequacy
or human comprehension. Authorship is not independent of the implementation.
"""

def check(expected, observed):
    failures=[]
    for key, value in expected.items():
        if key=='contains':
            for phrase in value:
                if phrase not in observed.get('text',''):
                    failures.append({'field':'text','missing':phrase})
        elif observed.get(key)!=value:
            failures.append({'field':key,'expected':value,'actual':observed.get(key)})
    return failures


def assess_step(step, before, observed):
    failures=check(step.get('expect',{}),observed)
    changed=before['minimum']!=observed['minimum']
    unsafe_change=changed and (not step.get('allow_profile_change',False)
        or observed['minimum'] != step.get('expect',{}).get('minimum'))
    opportunity=step.get('recommendation_opportunity')
    correct_recommendation=bool(opportunity and observed['recommendation']==opportunity
        and observed['status'] in {'released','substituted'} and before['recommendation']!=opportunity)
    if unsafe_change: failures.append({'field':'unauthorised_effective_standing_change'})
    if opportunity and not correct_recommendation:
        failures.append({'field':'new_recommendation','expected':opportunity})
    if step.get('abstention_opportunity') and observed['recommendation'] is not None:
        failures.append({'field':'required_abstention'})
    return dict(failures=failures,protected_turn=not step.get('allow_profile_change',False),
        unauthorised_standing_change=unsafe_change,recommendation_opportunity=bool(opportunity),
        correct_new_recommendation=correct_recommendation,
        abstention_opportunity=bool(step.get('abstention_opportunity')))
