"""Visitor-facing templates and compound evidence requests for the demonstration.

The evaluated runtime in advice stays unchanged. This adapter uses its release
checks and ordinary protocol moves, with a separately tested presentation layer.
"""
from advice.engine import Engine, option


class DemoEngine(Engine):
    def conversation_guidance(self, reason):
        """Keep social replies grounded in the current confirmation state."""
        if self.pending:
            if self.pending['kind'] == 'priority':
                choice = 'D’s lower annual cost' if self.pending['dimension'] == 'cost' else 'C’s higher sustainable share'
                proposal = f'Your preference for {choice} in this comparison'
            elif self.pending['kind'] == 'adaptation':
                proposal = f"Your proposed {self.pending['minimum']}% minimum for this conversation only"
            else:
                proposal = f"Your proposed usual minimum of {self.pending['minimum']}%"
            return (('You’re welcome. ' if reason == 'acknowledgment' else '')
                    + proposal + ' is still waiting for confirmation. Select “Confirm this change” to apply it, or “Decline” to keep your current settings.')
        if self.recommended:
            next_step = f'You can ask why {self.recommended} was recommended or see the evidence behind the choice.'
        elif self.comparison:
            next_step = 'You can choose which matters more for this comparison: lower annual cost or a higher sustainable share.'
        elif self.profile['minimum'] is not None:
            if len(self.screened) < 4:
                next_step = f"Your {self.effective_minimum()}% minimum is recorded. I can check the remaining products while keeping it."
            else:
                next_step = 'You can ask about the products or propose a different minimum.'
        else:
            next_step = 'Tell me the minimum sustainable share you want. For example: “I want at least 30% sustainable investments.”'
        if reason == 'acknowledgment':
            return 'You’re welcome. ' + next_step
        if reason == 'confirmation_control':
            return 'There is no proposal waiting for confirmation. ' + next_step
        if self.profile['minimum'] is not None:
            return next_step
        return 'You can set a sustainable-investment minimum, compare the four fictional products, or ask about a recommendation. ' + next_step

    def withdraw_support(self):
        if self.basis and 'adviser' not in self.libra.owners.get(self.basis['ground'],set()):
            self._archive('support withdrawn before ground introduction; recommendation suspended')
            self.revision += 1
            self.last_plan = None
            self.record('support_withdrawn',public_ground_introduced=False)
            return
        return super().withdraw_support()

    def _receive(self, event):
        if event.kind=='unresolved':
            reason = event.payload.get('reason')
            if reason in {'greeting', 'acknowledgment', 'confirmation_control'}:
                return 'clarify', {'message': self.conversation_guidance(reason), 'visitor_guidance': True}
            messages={
                'unsupported':'I can discuss only the four fictional products in this demo. You can set a minimum, compare cost and sustainability, or ask about the reasons and evidence for a choice.',
                'ambiguous':'Please make one request at a time and say whether a preference is your usual requirement or applies only to this conversation.'}
            if event.payload.get('reason') in messages:
                return 'clarify',{'message':messages[event.payload['reason']],'visitor_guidance':True}
        if event.kind == 'question_ground' and self.basis and self.recommended:
            token = self.basis['ground']
            if self.protocol_enabled and 'adviser' not in self.libra.owners.get(token, set()):
                # Asking for a decision's evidence also requests its justification.
                # Establish that justification through the normal public moves before
                # questioning the ground. The encompassing handle() uses a trial copy.
                target = f'Q:adviser:{self.recommended}'
                self.libra.apply({'kind':'question','actor':'client','holder':'adviser',
                                 'token':option(self.recommended)})
                self.record('evidence_request_expanded', steps=['option_question','checked_justification','ground_question'])
                prelude = self.release(self._make_plan('justify',target=target))
                if prelude['status'] not in {'released','substituted'}:
                    raise ValueError('Decision explanation could not be released')
                self.chat[-1]['mode'] = 'evidence_prelude'
        return super()._receive(event)

    def clauses(self, plan):
        out = super().clauses(plan)
        action, data = plan['action'], plan['data']
        minimum = self.effective_minimum()
        if action == 'clarify':
            if data.get('visitor_guidance'):return {'clarification':data['message']}
            if self.pending:
                return {'clarification':'There is a proposal waiting for your decision. Use Confirm this change or Decline to respond; a typed message cannot confirm it.'}
            if not self.recommended and not self.basis:
                return {'clarification':'There is no current recommendation to explain yet. Set and confirm your minimum, then compare the products and confirm a priority.'}
            return {'clarification':'I could not apply that request in the current conversation. Please say whether you want to change a preference, compare products, or ask about the current choice. Your confirmed preferences are unchanged.'}
        if action == 'confirm_minimum':
            return {'confirmation':f"Should I use at least {self.pending['minimum']}% sustainable investments as your usual minimum? Products below it will be excluded. Your medium-risk limit stays the same."}
        if action == 'confirm_adaptation':
            return {'confirmation':f"Use a {self.pending['minimum']}% minimum for this conversation only? Your usual {self.profile['minimum']}% minimum stays recorded and will apply again when this conversation ends. No product meets it in this example."}
        if action == 'confirm_priority':
            choice = 'D’s lower annual cost' if self.pending['dimension']=='cost' else 'C’s higher sustainable share'
            return {'confirmation':f'Prefer {choice} for this comparison? Your {minimum}% minimum and medium-risk limit stay the same.'}
        if action == 'no_match':
            count=len(self.screened)
            out={'screening':f"Of the {'two products checked so far' if count==2 else 'four products checked'}, none meets all your requirements."}
            for product in self.screened:
                if product not in self.exclusions:continue
                fact=self.facts[product]
                if fact['financial_ok'] is not True:
                    out['exclude_'+product]=f'{product} does not meet the assumed financial requirements.'
                elif isinstance(fact['minimum'],int) and minimum is not None and fact['minimum'] < minimum:
                    out['exclude_'+product]=f"{product} has a {fact['minimum']}% sustainable share, below your {minimum}% minimum."
                else:out['exclude_'+product]=f'{product} cannot be selected because the required information is incomplete.'
            out['next']='I can check the remaining two products while keeping your requirements.' if count==2 else 'You can keep your usual minimum, or propose a lower minimum for this conversation only.'
            return out
        if action == 'evidence':
            product=data['product'];fact=self.facts[product]
            return {'evidence':f"{product}’s {fact['minimum']}% sustainable share comes from the fictional product table supplied with this demo. It is a disclosed minimum in the example, not an observed investment allocation or a verified real-world disclosure."}
        if action in {'tradeoff','recommend','justify'}:
            out['eligibility']=f'Both C and D meet your {minimum}% minimum and the financial requirements assumed in this example.'
            if action=='tradeoff':
                out['elicitation']='Which matters more for this comparison: lower annual cost or a higher sustainable share? Your choice will need confirmation.'
            else:
                priority='lower annual cost' if self.comparison['priority']=='cost' else 'a higher sustainable share'
                out['local_scope']=f'You confirmed that {priority} matters more for this comparison only. Your usual minimum is unchanged.'
                out['recommendation']=f"That is why I recommend {self.basis['selected']}."
                if self.adaptation:
                    out['adaptation']=f"The {minimum}% minimum applies only to this conversation. Your usual {self.profile['minimum']}% minimum returns when it ends."
                if data.get('target','').startswith('E:'):
                    out['ground_evidence']='These figures come from the fictional product table supplied with this demo. They are example data, not independently verified disclosures about real investments.'
                    out['confirmation_evidence']=f'Your separate confirmation of {priority} is recorded in this conversation. The source identifiers and confirmation record are available under “Inspect the research details”.'
        if action=='acknowledge_retraction':
            return {'retraction':f"You no longer support {data['product']} as the alternative. Any explanation you previously requested is still owed until it is answered."}
        return out


def visible_chat(chat):
    """One evidence answer includes the released justification and disclosure.

    Keep a prelude visible when the final answer was held; never hide an unanswered
    request. Full texts and both protocol moves remain in the research trace.
    """
    return [m for i,m in enumerate(chat) if not (m.get('mode')=='evidence_prelude'
            and i+1<len(chat) and chat[i+1]['speaker']=='adviser')]
