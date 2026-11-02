const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let data = null, actions = [], preset = 'start', tracker = 'libra', busy = false;
let liveState = null, liveActions = [];
const msg = key => ({type:'message',key});
const experiment = key => ({type:'experiment',key});
function buttons(container, choices) {
  container.replaceChildren();
  choices.forEach(([label, action, secondary = false]) => {
    const button = document.createElement('button'); button.type = 'button';
    button.className = secondary ? 'secondary' : 'primary'; button.textContent = label;
    button.disabled = busy || (data?.action_count ?? actions.length) >= (data?.max_actions ?? Infinity); button.onclick = () => preset === 'live' ? sendLive(action) : send([...actions, action]); container.append(button);
  });
}
async function sendLive(action = {type:'start'}) {
  if (busy) return;
  busy = true; $('error').textContent = '';
  document.querySelectorAll('button,select,textarea').forEach(el => el.disabled = true);
  $('status').textContent = action.type === 'message' ? 'Interpreting…' : 'Checking…';
  try {
    const response = await fetch('/api/demo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'live',session_token:liveState?.session_token,action})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'The live conversation could not complete this action.');
    liveState = result; liveActions = action.type === 'start' ? [] : [...liveActions,action];
    data = result; preset = 'live'; tracker = 'libra'; actions = liveActions;
    if (action.type === 'message' || action.type === 'start') $('live-message').value = '';
  } catch (error) {
    $('error').textContent = error.message === 'Failed to fetch' ? 'Connection interrupted. Your previous conversation is unchanged. Please try again.' : error.message;
  } finally {
    busy = false; document.querySelectorAll('button,select,textarea').forEach(el => el.disabled = false);
    if (data) render();
  }
}
function openLive() {
  if (!liveState) return sendLive();
  data = liveState; actions = liveActions; preset = 'live'; tracker = 'libra'; $('error').textContent = ''; render();
}
async function send(nextActions = actions, nextPreset = preset, nextTracker = tracker) {
  if (busy) return;
  busy = true; $('error').textContent = '';
  document.querySelectorAll('button,select').forEach(el => el.disabled = true);
  $('status').textContent = 'Checking…';
  try {
    const response = await fetch('/api/demo', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({preset:nextPreset,tracker:nextTracker,actions:nextActions})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'The demonstration could not complete this action.');
    data = result; actions = nextActions; preset = nextPreset; tracker = nextTracker;
  } catch (error) {
    $('error').textContent = error.message === 'Failed to fetch' ? 'Connection interrupted. Please try this action again.' : error.message;
  } finally {
    busy = false; document.querySelectorAll('button,select').forEach(el => el.disabled = false);
    if (data) render();
    else {
      $('status').textContent = 'Connection needed';
      const retry = document.createElement('button'); retry.className = 'primary'; retry.textContent = 'Try again';
      retry.onclick = () => send(); $('actions').replaceChildren(retry);
    }
  }
}
function record(label, value, cls = '') {return `<div class="record"><span>${escapeHtml(label)}</span><strong class="${cls}">${escapeHtml(value)}</strong></div>`;}
function targetText(t) {return t.kind === 'element' ? 'The adviser still owes the evidence for the decision.' : `The adviser still owes an explanation of ${t.option}${t.rivals?.length ? ' compared with ' + t.rivals.join(', ') : ''}.`;}
function liveSuggestions(s) {
  const say = (label, text, secondary = false) => [label,{type:'message',text},secondary];
  if (s.pending || !data.live.available || data.messages_remaining <= 0) return [];
  if (s.profile.minimum === null) return [];
  if (s.screened.length < 4) return [say('Check the remaining products','Please check the remaining products while keeping my confirmed minimum.')];
  if (s.recommended) return [say('Explain this choice','Please explain the current recommendation.',true),say('Show the supporting evidence','Which evidence and confirmation support this decision?',true)];
  if (s.comparison && !s.comparison.priority) return [say('Prefer lower cost','For this comparison, I prefer lower annual cost.'),say('Prefer higher sustainable share','For this comparison, I prefer the higher sustainable share.',true)];
  if (s.eligible.includes('C') && s.eligible.includes('D')) return [say('Compare C and D','Please compare the products using my confirmed minimum.')];
  if (!s.eligible.length && s.profile.minimum > 30 && !s.adaptation) return [say('Propose 30% for this conversation','No product meets my usual minimum. For this conversation only, I propose lowering it to 30%.',true)];
  return [];
}
function noticeText(s, targets) {
  const last = actions.at(-1), pending = s.pending, rival = s.basis?.rival, selected = s.basis?.selected;
  if (preset === 'live' && !data.live.available) return data.live.message;
  if (preset === 'live' && !actions.length) return 'Start with your own words, such as “I want at least 30% sustainable investments.” You can then compare products and ask why a choice was made.';
  if (preset === 'live' && data.last_result?.plan?.action === 'clarify') return 'Your message did not change any confirmed preference. Read the reply below for the next step.';
  if (last?.key === 'text_accept') return 'The typed “accept” did not confirm anything. Use the separate confirmation button to make this change.';
  if (pending) return pending.kind === 'adaptation'
    ? `Nothing has changed yet. Accepting ${pending.minimum}% applies only to this conversation; your usual ${s.profile.minimum}% minimum stays recorded.`
    : pending.kind === 'priority' ? 'Your preference is still a proposal. Confirm it to let the adviser choose between C and D.'
    : 'Your minimum is only a proposal. It becomes a rule for the search after you confirm it.';
  if (targets.length) return last?.key === 'retract'
    ? `You stopped supporting ${rival}, but your question is still unanswered. The adviser must still explain why ${selected} was chosen.`
    : `Try withdrawing your support for ${rival}. Notice that the adviser still owes you the explanation you asked for.`;
  if (last?.key === 'resume') return 'The full explanation has now been delivered. The record no longer lists an unanswered question.';
  if (last?.key === 'end_episode') return `This conversation has ended. Your usual ${s.profile.minimum}% minimum still applies, and any temporary change has expired.`;
  if (last?.type === 'confirmation' && !last.accept) return 'You declined the proposal. Your confirmed preferences have stayed the same.';
  if (s.recommended) return s.recommended === 'D'
    ? 'D meets your minimum and costs less than C. It was selected only after you confirmed that lower cost mattered more for this comparison.'
    : 'C meets your minimum and has a higher sustainable share than D. It was selected only after you confirmed that this mattered more for this comparison.';
  if (preset === 'recovery') return s.facts.D.minimum === 20
    ? 'D no longer meets your minimum, so the adviser has withdrawn its recommendation. Restore the example data to try the decision again.'
    : 'Restoring D’s data does not restore the old recommendation. Compare the products and confirm a new priority.';
  if (s.comparison) return 'Both C and D meet the minimum. C offers a higher sustainable share; D has a lower annual cost. Choose which matters more.';
  if (s.profile.minimum !== null) return s.eligible.length === 0 && s.screened.length === 4
    ? 'None of the four products meets your minimum. You can propose a temporary change or keep your usual requirement.'
    : `Your ${s.profile.minimum}% minimum is confirmed. Continue the search to find products that meet it.`;
  return 'Start by proposing a 30% minimum. This means accepting only products with a disclosed sustainable share of at least 30%.';
}
function render() {
  const s = data.state, p = s.pending, k = s.comparison, targets = Object.values(s.libra.targets);
  const live = preset === 'live';
  const ended = live && actions.at(-1)?.key === 'end_episode';
  $('reset').textContent = live ? 'Start a new conversation ↺' : 'Start this example again ↺';
  document.querySelector('.dialogue').classList.toggle('is-live',live);
  document.querySelectorAll('[data-preset]').forEach(b => b.setAttribute('aria-pressed',String(b.dataset.preset === preset)));
  $('tracker').value = tracker;
  $('tracker').disabled = live;
  $('live-form').hidden = !live;
  $('live-send').disabled = live && (!data.live.available || data.messages_remaining <= 0 || data.action_count >= data.max_actions);
  $('live-message').disabled = $('live-send').disabled;
  $('live-allowance').textContent = live ? `${data.messages_remaining} of 12 live messages remaining` : '';
  $('model-details').textContent = live ? `Interpreter: ${data.live.model}, hosted by ${data.live.provider}. ${data.model_calls} model calls in this conversation. Confirmations make no model calls. This model is used for the demonstration; the paper’s model results remain separate.` : 'Prepared interpretations; no model calls. The interface uses visitor-facing templates over the evaluated runtime.';
  $('dialogue-title').textContent = data.presets[preset].title;
  $('guide').textContent = data.presets[preset].description;
  $('notice-title').textContent = actions.length ? 'What happened' : 'What to try';
  $('notice').textContent = noticeText(s, targets);
  const stateName = ended ? 'Conversation ended' : p ? 'Your confirmation needed' : targets.length ? 'Explanation still owed' : s.recommended ? 'Choice recorded' : preset === 'recovery' && s.facts.D.minimum === 20 ? 'Choice suspended' : s.screened.length === 4 && !s.eligible.length ? 'No matching product' : 'Ready';
  $('status').textContent = stateName; $('status').className = 'status' + (targets.length ? ' held' : '');
  $('chat').innerHTML = data.chat.length ? data.chat.map(m => {
    const ended = m.speaker === 'experiment' && m.text.startsWith('Advice episode closed.');
    const isControl = m.mode === 'structured_control';
    const role = isControl ? 'control' : m.speaker;
    const label = ended ? 'Conversation closed' : isControl || role === 'control' ? 'Your confirmation' : role === 'client' ? live ? 'You' : 'You · example message' : role === 'adviser' ? 'Adviser · checked reply' : 'Example data changed';
    const text = ended ? 'This conversation has ended. Any temporary minimum has expired; your usual minimum is retained.' : isControl && m.text === 'Accept displayed proposal' ? 'I confirm this change.' : m.text;
    return `<article class="message ${escapeHtml(role)}"><div class="who">${label}</div><p>${escapeHtml(text)}</p></article>`;
  }).join('') : `<div class="empty"><p>Your conversation will appear here after you ${live ? 'send' : 'choose'} a message.</p></div>`;
  $('chat').scrollTop = $('chat').scrollHeight;
  $('confirmation').replaceChildren();
  if (p) {
    const what = p.kind === 'priority' ? (p.dimension === 'cost' ? 'Prefer D’s lower cost' : 'Prefer C’s higher sustainability minimum') : `${p.minimum}% minimum`;
    const scope = p.kind === 'minimum' ? 'This becomes your usual requirement for future conversations too.' : p.kind === 'adaptation' ? `This conversation only. Your usual ${s.profile.minimum}% minimum stays the same.` : 'This comparison only. Your usual minimum stays the same.';
    const card = document.createElement('div'); card.className = 'confirmation';
    card.innerHTML = `<h3>Make this change?</h3><p><b>${escapeHtml(what)}</b></p><p class="scope">${escapeHtml(scope)}</p><div class="action-buttons"></div>`;
    $('confirmation').append(card);
    buttons(card.querySelector('.action-buttons'), [
      ['Confirm this change',{type:'confirmation',proposal_id:p.id,accept:true}],
      ['Decline',{type:'confirmation',proposal_id:p.id,accept:false},true]
    ]);
  }
  let choices = [], note = 'Messages and replies are prepared examples. No live AI is running.';
  if (actions.length >= data.max_actions) { note = 'This exploration is complete. Start the example again to continue.'; }
  else if (p) {note = 'Use Confirm this change or Decline above. A proposed change alone does not take effect.';}
  else if (targets.length) {
    choices = [['Show the full explanation', experiment('resume')]];
    const rival = s.basis?.rival;
    if (rival && s.libra.owners[`Opt(${rival})`]?.includes('client')) choices.unshift([`Withdraw my support for ${rival}`, msg('retract'),true]);
    note = 'Watch “Explanations still owed” in the record as you try these actions.';
  } else if (s.profile.minimum === null) { choices = [['Propose a 30% minimum',msg('minimum_30')]]; }
  else if (!k) {
    if (preset === 'recovery' && s.facts.D.minimum === 20) {
      choices = [['Restore D’s sustainable share to 32%',experiment('restore_d')]];
      note = 'This changes the fictional product data so you can try a fresh comparison.';
    } else if (s.screened.length < 4 || s.eligible.length) { choices = [['Search all four products',msg('search')]]; }
    else if (s.profile.minimum > 30 && !s.adaptation) {
      choices = [['Propose 30% for this conversation',msg('adapt_30')],['Keep my usual minimum',experiment('end_episode'),true]];
      note = 'A temporary change is optional. It takes effect only if you confirm it.';
    } else choices = [['Propose a new usual minimum',msg('minimum_30')]];
  } else if (!k.priority) {
    choices = [['Prefer lower cost',msg('cost')],['Prefer higher sustainability',msg('sustainability'),true]];
    note = 'C: 40% sustainable share, 1.20% annual cost. D: 32% sustainable share, 0.80% annual cost.';
  } else if (s.recommended) {
    choices = [['Explain this choice',msg('why')],['Show the supporting evidence',msg('grounds'),true]];
    if (s.adaptation) choices.push(['End this conversation',experiment('end_episode'),true]);
    note = s.adaptation ? 'End the conversation to see the temporary minimum expire.' : 'You can ask how the adviser reached this choice, or try another scenario above.';
  }
  if (live) {
    choices = liveSuggestions(s);
    note = !data.live.available ? 'The live model connection is not enabled. You can explore all four guided examples.' : data.messages_remaining <= 0 ? 'This conversation has reached its free-message limit. You can still confirm a pending proposal or start a new conversation.' : p ? 'Check the displayed proposal. Use its confirmation buttons to accept or decline.' : ended ? 'You can start another conversation using your usual minimum, or reset the demo to begin with a new profile.' : choices.length ? 'Send a suggested message, or write your own below. Both go to the live model for interpretation.' : 'Write your message below. The model interprets your request; the rules determine the response.';
  }
  buttons($('actions'),choices); $('next-label').textContent = p ? 'YOUR CHOICE IS REQUIRED' : live ? 'CONTINUE THE CONVERSATION' : 'YOUR NEXT STEP'; $('action-note').textContent = note;
  $('session-controls').hidden = !live || s.profile.minimum === null || ended;
  $('end-live-confirm').hidden = true;
  if (live && !data.live.available) {
    const retry = document.createElement('button'); retry.className = 'secondary'; retry.textContent = 'Check connection'; retry.onclick = () => sendLive(); $('actions').append(retry);
  }
  $('summary').innerHTML = record('Your usual minimum',s.profile.minimum === null ? 'Not confirmed' : `${s.profile.minimum}%`) +
    record('Temporary minimum',s.adaptation ? `${s.adaptation.minimum}% · this conversation` : 'None') +
    record('Your confirmed priority',k?.priority === 'cost' ? 'Lower cost' : k?.priority === 'sustainability' ? 'Sustainability' : 'None') +
    record('Adviser’s choice',s.recommended || 'None',s.recommended ? 'selected' : '');
  $('products').innerHTML = s.screened.length === 4 ? `<div class="product-pair">${['C','D'].map(id => {
    const f = s.facts[id],eligible = s.eligible.includes(id);
    return `<div class="product ${s.recommended === id ? 'chosen' : ''} ${eligible ? '' : 'excluded'}"><strong>${id}</strong><p>${f.minimum}% sustainable share*</p><p>${(f.cost_basis_points/100).toFixed(2)}% annual cost</p><em>${s.recommended === id ? 'Recommended' : eligible ? 'Meets your minimum' : 'Below your minimum'}</em></div>`;
  }).join('')}</div><p class="note">*Disclosed minimum share, not an observed allocation. In this example, C and D otherwise meet the financial requirements. A and B were also checked.</p>` : '';
  $('obligations').innerHTML = targets.length ? `<div class="owed"><b>Explanations still owed: ${targets.length}</b>${targets.map(t => `<p>${escapeHtml(targetText(t))}</p>`).join('')}</div>` : '<p class="clear-note">Explanations still owed: 0</p>';
  const extras = [['Propose a standing 50% minimum',msg('minimum_50'),true]];
  if (p) extras.push(['Try a text-only “accept”',msg('text_accept'),true]);
  if (s.recommended) {
    extras.push(['Hold an incomplete challenge answer',msg('challenge_held'),true],['Change D’s evidence to 20%',experiment('lower_d'),true]);
    extras.push(['Withdraw the supporting ground',experiment('withdraw_support'),true]);
  }
  if (s.profile.minimum !== null) extras.push(['End the advice episode',experiment('end_episode'),true]);
  buttons($('extra-actions'),!live && actions.length < data.max_actions ? extras : []);
  const held = data.held_candidate; $('held').hidden = !held;
  $('held-content').innerHTML = held ? `<p>This earlier draft deliberately omitted a required comparison clause and was held. It is an injected test, not an observed LLM error.</p><blockquote>${escapeHtml(held.candidate)}</blockquote><p>Failed checks: ${held.checks.filter(c => !c.passed).map(c => escapeHtml(c.check)).join(', ')}.</p>` : '';
  $('history').textContent = JSON.stringify({state:s,history:data.history,raw_dialogue:data.raw_chat,interpretations:data.interpretations},null,2);
}
document.querySelectorAll('[data-preset]').forEach(b => b.onclick = () => b.dataset.preset === 'live' ? openLive() : send([],b.dataset.preset));
$('reset').onclick = () => preset === 'live' ? sendLive() : send([]);
$('tracker').onchange = event => send(actions,preset,event.target.value);
$('live-form').onsubmit = event => {event.preventDefault(); if (!$('live-send').disabled && $('live-message').value.trim()) sendLive({type:'message',text:$('live-message').value.trim()});};
$('end-live').onclick = () => {$('end-live-confirm').hidden = false;};
$('end-live-cancel').onclick = () => {$('end-live-confirm').hidden = true;};
$('end-live-yes').onclick = () => {if (!busy) sendLive(experiment('end_episode'));};
$('export').onclick = () => {
  if (!data) return;
  const trace = {demo:'LIBRA-ADVICE',mode:data.mode,model_calls:data.model_calls,preset,tracker,actions,state:data.state,chat:data.chat,raw_chat:data.raw_chat,history:data.history,interpretations:data.interpretations};
  const url = URL.createObjectURL(new Blob([JSON.stringify(trace,null,2)],{type:'application/json'}));
  const a = document.createElement('a');a.href=url;a.download='libra-advice-trace.json';a.click();setTimeout(() => URL.revokeObjectURL(url),1000);
};
send();
