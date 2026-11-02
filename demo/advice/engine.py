"""Stateful application controller; no third-party runtime dependencies.

Public methods are serialized by the web server. Released responses and outgoing
Libra moves commit in one in-memory transaction; this is not a durable distributed
delivery guarantee. Every consequential response uses exact complete templates.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
import hashlib
import json

from .libra import Libra, ProtocolError, option


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def products():
    out = {}
    for pid, fin, minimum, cost in [("A", True, 20, None), ("B", False, 40, None),
                                    ("C", True, 40, 120), ("D", True, 32, 80)]:
        out[pid] = {"id": pid, "financial_ok": fin, "minimum": minimum,
                    "cost_basis_points": cost, "comparable_group": "CD" if pid in "CD" else None,
                    "source": f"paper.table1.{pid}", "status": "stipulated",
                    "version": "fixture-v1"}
    return out


KINDS = {"propose_minimum", "propose_adaptation", "propose_priority", "confirm", "search", "why",
         "evidence", "challenge", "retract", "question_ground", "unresolved"}


@dataclass
class Event:
    kind: str
    payload: dict
    scope: str = "unresolved"
    ref: str | None = None
    spans: list | None = None

    @classmethod
    def parse(cls, raw, utterance):
        if not isinstance(raw, dict) or set(raw) - {"kind", "payload", "scope", "ref", "spans"}:
            raise ValueError("unexpected event fields")
        e = cls(**raw)
        if e.kind not in KINDS or not isinstance(e.payload, dict):
            raise ValueError("invalid kind or payload")
        if not isinstance(e.scope, str) or (e.ref is not None and not isinstance(e.ref, str)):
            raise ValueError("invalid scope or reference")
        if not isinstance(e.spans, list) or not e.spans or any(
                not isinstance(s, str) or not s or s not in utterance for s in e.spans):
            raise ValueError("interpretation must cite exact nonempty utterance spans")
        allowed = {"propose_minimum": {"minimum", "mode"}, "propose_adaptation": {"minimum", "reason"}, "propose_priority": {"dimension"},
                   "why": {"product"}, "evidence": {"product"}, "challenge": {"rival"},
                   "retract": {"product"}, "unresolved": {"reason"}}
        if set(e.payload) - allowed.get(e.kind, set()):
            raise ValueError("unexpected payload fields")
        return e


class Engine:
    def __init__(self, protocol_enabled=True, tracker="libra"):
        self.tracker_kind = tracker
        self.advice_id = "a1"
        self.advice_counter = 1
        self.adaptation = None
        self._confirmation_authorized = False
        self.profile = {"version": 0, "risk_limit": "medium", "minimum": None,
                        "financial_assessment": "other dimensions stipulated assessed"}
        self.facts = products()
        self.evidence_version = 1
        self.screened, self.eligible, self.exclusions = [], [], {}
        self.comparison = None
        self.pending = None
        self.basis = None
        self.recommended = None
        self.libra = self._new_tracker()
        self.archived = []
        self.protocol_enabled = protocol_enabled
        self.revision = 0
        self.counter = 0
        self.comparison_counter = 0
        self.log, self.chat = [], []
        self.last_plan = None
        self.seen = {}
        self.last_result = None

    def _new_tracker(self):
        if self.tracker_kind == "libra":
            return Libra()
        if self.tracker_kind == "conventional":
            from .tracker import ConventionalTracker
            return ConventionalTracker()
        raise ValueError("unknown tracker")

    def effective_minimum(self):
        return self.adaptation["minimum"] if self.adaptation else self.profile["minimum"]

    def confirm_control(self, proposal_id, accept, **kwargs):
        """Trusted UI boundary. Never called from the interpreter/event schema.

        A production service must authenticate this distinct input route and show
        the exact proposal, scope and values. This local study exercises the API.
        """
        if type(accept) is not bool or not self.pending or proposal_id != self.pending["id"]:
            raise ValueError("current proposal and Boolean choice required")
        if not self.pending["displayed"]:
            raise ValueError("proposal has not been displayed")
        if not accept:
            self.pending = None
            self.last_plan = None
            self.revision += 1
            self.record("structured_decline", proposal_id=proposal_id)
            return {"status": "declined", "event_accepted": True}
        raw = {"kind": "confirm", "payload": {}, "scope": self.pending["scope"],
               "ref": proposal_id, "spans": ["Accept displayed proposal"]}
        self._confirmation_authorized = True
        try:
            return self.handle("Accept displayed proposal", raw, mode="structured_control", **kwargs)
        finally:
            self._confirmation_authorized = False

    def end_advice(self):
        self._archive("advice episode ended")
        self.adaptation = None
        self.advice_counter += 1
        self.advice_id = f"a{self.advice_counter}"
        self.eligibility()
        self.revision += 1
        self.last_plan = None
        self.record("advice_closed")

    def withdraw_support(self):
        """Trusted evidence-review operation, outside the language event schema."""
        if not self.basis:
            raise ValueError("no recommendation basis")
        self.libra.apply({"kind": "retract", "actor": "adviser", "token": self.basis["ground"]})
        self._archive("support withdrawn; recommendation suspended")
        self.revision += 1
        self.last_plan = None
        self.record("support_withdrawn")

    def snapshot(self):
        return deepcopy({"profile": self.profile, "facts": self.facts,
            "evidence_version": self.evidence_version, "screened": self.screened,
            "eligible": self.eligible, "exclusions": self.exclusions,
            "comparison": self.comparison, "pending": self.pending, "basis": self.basis,
            "recommended": self.recommended, "revision": self.revision,
            "protocol_enabled": self.protocol_enabled, "libra": self.libra.snapshot(),
            "advice_id": self.advice_id, "adaptation": self.adaptation,
            "archived_comparisons": self.archived})

    def record(self, kind, **data):
        previous = self.log[-1]["hash"] if self.log else "0" * 64
        rec = {"sequence": len(self.log) + 1, "kind": kind, **deepcopy(data),
               "state": self.snapshot(), "previous_hash": previous}
        rec["hash"] = digest(rec)
        self.log.append(rec)
        return rec

    def eligibility(self):
        exclusions, eligible = {}, []
        for pid in self.screened:
            p = self.facts[pid]
            why = []
            if p["financial_ok"] is not True:
                why.append("financial assessment failed or unresolved")
            minimum = p["minimum"]
            if self.effective_minimum() is None:
                why.append("client minimum not confirmed")
            elif type(minimum) is not int:
                why.append("disclosed minimum is missing or unresolved")
            elif minimum < self.effective_minimum():
                why.append(f"disclosed minimum {minimum}% is below {self.effective_minimum()}%")
            if not p["source"] or not p["version"]:
                why.append("source or version is missing")
            if why:
                exclusions[pid] = why
            else:
                eligible.append(pid)
        self.eligible, self.exclusions = eligible, exclusions

    def _archive(self, reason):
        if self.comparison:
            self.archived.append({"comparison": deepcopy(self.comparison),
                "libra": self.libra.snapshot(), "basis": deepcopy(self.basis), "reason": reason,
                "adaptation": deepcopy(self.adaptation)})
        self.comparison = self.basis = self.pending = self.recommended = None
        self.libra = self._new_tracker()

    def open_comparison(self):
        self._archive("new comparison context")
        self.comparison_counter += 1
        self.comparison = {"id": f"k{self.comparison_counter}", "alternatives": ["C", "D"],
            "profile_version": self.profile["version"], "evidence_version": self.evidence_version,
            "priority": None, "confirmation": None}

    def _decision_basis(self):
        k = self.comparison
        if not k or k["priority"] not in {"cost", "sustainability"} or not k["confirmation"]:
            raise ValueError("no confirmed local priority")
        if (k["profile_version"] != self.profile["version"] or
                k["evidence_version"] != self.evidence_version):
            raise ValueError("comparison uses stale versions")
        screening = deepcopy(self)
        screening.eligibility()
        if not {"C", "D"} <= set(screening.eligible):
            raise ValueError("both compared products must be eligible")
        c, d = self.facts["C"], self.facts["D"]
        if (type(c["cost_basis_points"]) is not int or type(d["cost_basis_points"]) is not int
                or not d["cost_basis_points"] < c["cost_basis_points"]
                or not c["minimum"] > d["minimum"]
                or c["comparable_group"] != "CD" or d["comparable_group"] != "CD"):
            raise ValueError("bounded comparison assumptions are not satisfied")
        selected, rival = ("D", "C") if k["priority"] == "cost" else ("C", "D")
        return {"comparison_id": k["id"], "selected": selected, "rival": rival,
            "profile_version": self.profile["version"], "evidence_version": self.evidence_version,
            "minimum": self.effective_minimum(), "confirmation": deepcopy(k["confirmation"]),
            "adaptation": deepcopy(self.adaptation),
            "cost_advantage_bp": c["cost_basis_points"] - d["cost_basis_points"],
            "sustainability_advantage_pp": c["minimum"] - d["minimum"],
            "C": deepcopy(c), "D": deepcopy(d), "ground": f"g:{k['id']}",
            "reason": {"ground": f"g:{k['id']}", "label": f"r:{k['id']}",
                       "for": selected, "against": rival, "j": "high", "r": "low"}}

    def _make_plan(self, action, **data):
        self.counter += 1
        plan = {"id": f"plan-{self.counter}", "action": action, "revision": self.revision,
                "data": data, "move": None}
        if action == "recommend":
            plan["move"] = {"kind": "assert", "actor": "adviser", "option": self.basis["selected"]}
        elif action == "justify":
            target = self.libra.targets.get(data["target"])
            if target and target["kind"] == "element":
                plan["move"] = {"kind": "justify", "actor": "adviser", "target": data["target"],
                                "grounds": [f"g:evidence:{self.comparison['id']}"]}
            else:
                plan["move"] = {"kind": "justify", "actor": "adviser", "target": data["target"],
                                "package": [deepcopy(self.basis["reason"])]}
        self.last_plan = deepcopy(plan)
        return plan

    def clauses(self, plan):
        a, data = plan["action"], plan["data"]
        tau = self.effective_minimum()
        if a == "clarify":
            return {"clarification": data["message"]}
        if a == "confirm_minimum":
            return {"confirmation": f"Should I record {self.pending['minimum']}% as your firm minimum, "
                    "excluding products below it? Your medium-risk limit remains unchanged."}
        if a == "confirm_adaptation":
            return {"confirmation": f"For advice episode {self.advice_id} only, accept a {self.pending['minimum']}% minimum? "
                    f"Your standing {self.profile['minimum']}% minimum is retained. "
                    f"Recorded reason: {self.pending['reason']}"}
        if a == "confirm_priority":
            choice = "D's lower cost" if self.pending["dimension"] == "cost" else "C's higher sustainability minimum"
            return {"confirmation": f"For comparison {self.comparison['id']} only, prioritise {choice}, "
                    f"retaining the effective {tau}% minimum and medium-risk limit?"}
        if a == "no_match":
            return {**{f"exclude_{p}": f"{p}: {'; '.join(self.exclusions[p])}."
                       for p in self.screened if p in self.exclusions},
                    "no_recommendation": "No screened product can be recommended under your confirmed profile.",
                    "search_option": "I can continue searching within our advised universe while preserving your requirements."}
        if a == "exclusion":
            pid = data["product"]
            return {"exclusion": f"{pid}: {'; '.join(self.exclusions[pid])}.",
                    "priority": "Projected performance cannot compensate for failing a confirmed mandatory condition."}
        if a == "evidence":
            p = self.facts[data["product"]]
            return {"evidence": f"The {p['minimum']}% figure for {p['id']} is stipulated in the paper's Table 1 "
                    f"({p['source']}, {p['version']}). This demo does not claim an actual product disclosure."}
        if a in {"tradeoff", "recommend", "justify"}:
            c, d = self.facts["C"], self.facts["D"]
            out = {"eligibility": f"C and D meet the stipulated financial assessment and your {tau}% minimum.",
                "cost_advantage": f"D's annual product cost is {d['cost_basis_points']/100:.2f}%, versus C's {c['cost_basis_points']/100:.2f}%.",
                "rival_advantage": f"C retains its sustainability advantage: a {c['minimum']}% disclosed minimum, versus D's {d['minimum']}%."}
            if a == "tradeoff":
                out["elicitation"] = "How do you assess this trade-off? No priority has been confirmed for this comparison."
            else:
                if self.basis["selected"] == "C":
                    out["selected_advantage"] = out.pop("rival_advantage")
                    out["rival_advantage"] = out.pop("cost_advantage")
                out["local_scope"] = f"You confirmed priority for {self.comparison['priority']} in comparison {self.comparison['id']} only; your standing profile is unchanged."
                if self.adaptation:
                    out["adaptation"] = f"The {tau}% minimum is restricted to advice episode {self.advice_id}; your standing minimum remains {self.profile['minimum']}%. Reason: {self.adaptation['reason']}"
                out["recommendation"] = f"On that recorded basis, I recommend {self.basis['selected']}."
                if plan["data"].get("target", "").startswith("E:"):
                    out["ground_evidence"] = "Evidence for the disclosed decision ground: " + "; ".join(
                        f"{pid}: minimum {self.facts[pid]['minimum']}%, annual cost {self.facts[pid]['cost_basis_points']/100:.2f}%, source {self.facts[pid]['source']}, version {self.facts[pid]['version']}"
                        for pid in ("C", "D")) + ". These are stipulated product facts, not independently verified disclosures."
                    out["confirmation_evidence"] = f"Local-priority confirmation reference: {self.comparison['confirmation']['ref']}."
            return out
        if a == "acknowledge_retraction":
            return {"retraction": f"Your public commitment to {data['product']} has been withdrawn. Any outstanding adviser justification remains open."}
        raise ValueError("unknown response action")

    def render(self, plan):
        return " ".join(self.clauses(plan).values())

    def _receive(self, e):
        kind, p = e.kind, e.payload
        if kind == "propose_adaptation":
            value = p.get("minimum")
            scan = deepcopy(self)
            scan.screened = list(self.facts)
            scan.eligibility()
            if (self.profile["minimum"] is None or scan.eligible or self.adaptation
                    or type(value) is not int or not 0 <= value < self.profile["minimum"]
                    or e.scope != self.advice_id or not isinstance(p.get("reason"), str)
                    or not p["reason"].strip()):
                raise ValueError("scoped adaptation requires a no-match episode, lower minimum and recorded reason")
            self.counter += 1
            self.pending = {"id": f"b{self.counter}", "kind": "adaptation", "minimum": value,
                "reason": p["reason"], "scope": self.advice_id, "profile_version": self.profile["version"],
                "evidence_version": self.evidence_version, "displayed": False, "spans": e.spans}
            return "confirm_adaptation", {}
        if kind == "propose_minimum":
            if e.scope != "standing":
                raise ValueError("standing minimum proposal requires explicit standing scope")
            value = p.get("minimum")
            if type(value) is not int or not 0 <= value <= 100 or p.get("mode") != "firm":
                return "clarify", {"message": "Please clarify a firm minimum between 0% and 100%. Targets require a separate design beyond this demo."}
            self.counter += 1
            self.pending = {"id": f"b{self.counter}", "kind": "minimum", "minimum": value,
                "scope": "standing", "profile_version": self.profile["version"],
                "evidence_version": self.evidence_version, "displayed": False, "spans": e.spans}
            return "confirm_minimum", {}
        if kind == "propose_priority":
            if not self.comparison or p.get("dimension") not in {"cost", "sustainability"}:
                return "clarify", {"message": "This comparison requires a cost or sustainability priority for C and D."}
            k = self.comparison["id"]
            if e.scope not in {"unresolved", k}:
                return "clarify", {"message": "This demo supports a separately confirmed local C/D priority. A standing priority requires further assessment."}
            self.counter += 1
            self.pending = {"id": f"b{self.counter}", "kind": "priority", "dimension": p["dimension"],
                "scope": k, "profile_version": self.profile["version"],
                "evidence_version": self.evidence_version, "displayed": False, "spans": e.spans}
            return "confirm_priority", {}
        if kind == "confirm":
            if not self._confirmation_authorized:
                raise ValueError("free-text events cannot exercise the structured confirmation control")
            b = self.pending
            if (not b or not b["displayed"] or e.ref != b["id"] or
                    e.scope not in {"unresolved", b["scope"]} or
                    b["profile_version"] != self.profile["version"] or
                    b["evidence_version"] != self.evidence_version):
                raise ValueError("confirmation is missing, ambiguous, stale or has the wrong scope")
            if b["kind"] == "minimum":
                minimum = b["minimum"]
                self.adaptation = None
                self._archive("confirmed standing minimum change")
                self.profile.update(minimum=minimum, version=self.profile["version"] + 1)
                self.screened = self.screened or ["A", "B"]
                self.eligibility()
                if not self.eligible:
                    return "no_match", {}
                if {"C", "D"} <= set(self.eligible):
                    self.open_comparison()
                    return "tradeoff", {}
                return "clarify", {"message": "Screening completed. The available products fall outside the demo's bounded C/D selection rule; further assessment is needed."}
            if b["kind"] == "adaptation":
                if b["scope"] != self.advice_id:
                    raise ValueError("adaptation refers to another episode")
                self.adaptation = {"minimum": b["minimum"], "reason": b["reason"], "scope": b["scope"],
                    "confirmation_ref": b["id"], "evidence_version": self.evidence_version}
                self.pending = None
                self.screened = list(self.facts)
                self.eligibility()
                if {"C", "D"} <= set(self.eligible):
                    self.open_comparison()
                    return "tradeoff", {}
                return "clarify", {"message": "Adaptation recorded for this episode; the bounded selection rule still requires C and D to be eligible."}
            if not self.comparison or b["scope"] != self.comparison["id"]:
                raise ValueError("priority refers to another comparison")
            self.comparison["priority"] = b["dimension"]
            self.comparison["confirmation"] = {"ref": b["id"], "scope": b["scope"],
                "proposal_spans": b["spans"], "confirmation_spans": e.spans}
            self.pending = None
            self.basis = self._decision_basis()
            return "recommend", {}
        if kind == "search":
            if self.profile["minimum"] is None:
                raise ValueError("confirm a minimum before screening")
            self.screened = ["A", "B", "C", "D"]
            self.eligibility()
            if {"C", "D"} <= set(self.eligible):
                self.open_comparison()
                return "tradeoff", {}
            if not self.eligible:
                return "no_match", {}
            return "clarify", {"message": "The extended search does not establish both eligible C/D alternatives. No recommendation is authorised."}
        if kind == "evidence":
            pid = p.get("product")
            if pid not in self.screened or self.facts[pid]["minimum"] is None:
                raise ValueError("requested evidence unavailable")
            return "evidence", {"product": pid}
        if kind == "why":
            pid = p.get("product")
            if pid in self.exclusions:
                return "exclusion", {"product": pid}
            if not self.recommended:
                raise ValueError("no public recommendation to question")
            if pid not in {None, self.recommended}:
                raise ValueError("question does not identify the recommended option")
            tid = f"Q:adviser:{self.recommended}"
            if self.protocol_enabled:
                self.libra.apply({"kind": "question", "actor": "client", "holder": "adviser",
                                  "token": option(self.recommended)})
            return "justify", {"target": tid}
        if kind == "challenge":
            if not self.recommended or p.get("rival") != self.basis["rival"]:
                raise ValueError("challenge must identify the current rival")
            if self.protocol_enabled:
                self.libra.apply({"kind": "challenge", "actor": "client", "holder": "adviser",
                                  "option": self.recommended, "rival": p["rival"]})
            return "justify", {"target": f"T:adviser:{self.recommended}:{p['rival']}"}
        if kind == "retract":
            if p.get("product") not in {"C", "D"}:
                raise ValueError("client may retract its own C or D claim")
            if self.protocol_enabled:
                self.libra.apply({"kind": "retract", "actor": "client", "token": option(p["product"])})
            return "acknowledge_retraction", {"product": p["product"]}
        if kind == "question_ground":
            if not self.basis:
                raise ValueError("no disclosed decision ground")
            token = self.basis["ground"]
            if self.protocol_enabled:
                self.libra.apply({"kind": "question", "actor": "client", "holder": "adviser", "token": token})
            return "justify", {"target": f"E:adviser:{token}"}
        return "clarify", {"message": "I could not establish a safe interpretation. Please clarify the requested action or preference; your confirmed profile is unchanged."}

    def handle(self, utterance, raw_event, mode="supplied_event", turn_id=None,
               auto_release=True, fault=None, fallback=True):
        if not isinstance(utterance, str) or not 0 < len(utterance) <= 8000:
            raise ValueError("utterance must contain 1–8000 characters")
        signature = digest([utterance, raw_event, mode, auto_release, fault, fallback])
        if turn_id in self.seen:
            old_sig, result = self.seen[turn_id]
            if signature != old_sig:
                raise ValueError("turn identifier reused with different content")
            return deepcopy(result)
        self.chat.append({"speaker": "client", "text": utterance, "mode": mode})
        before = self.snapshot()
        trial = deepcopy(self)
        try:
            e = Event.parse(raw_event, utterance)
            action, data = trial._receive(e)
            trial.revision += 1
            self.__dict__.update(trial.__dict__)
            accepted, error = True, None
        except (ValueError, KeyError, TypeError, ProtocolError) as exc:
            action, data = "clarify", {"message": "Please clarify or reconfirm the current proposition. No proposed preference or public commitment was accepted."}
            accepted, error = False, str(exc)
        self.record("interpretation", input=utterance, mode=mode, proposed_event=raw_event,
                    accepted=accepted, error=error, state_before=before)
        plan = self._make_plan(action, **data)
        self.record("response_plan", plan=plan)
        result = self.release(plan, fault=fault, fallback=fallback) if auto_release else {
            "status": "awaiting_release", "plan": deepcopy(plan)}
        result["event_accepted"] = accepted
        result["event_error"] = error
        self.last_result = deepcopy(result)
        if turn_id is not None:
            self.seen[turn_id] = (signature, deepcopy(result))
        return result

    def checks(self, plan, text, annotations=()):
        checks = []
        def add(name, passed, detail):
            checks.append({"check": name, "passed": bool(passed), "detail": detail})
        add("issued_plan", plan == self.last_plan, "controller-issued plan required")
        add("state_version", plan["revision"] == self.revision, "plan must use current revision")
        if plan["action"] in {"recommend", "justify"}:
            try:
                current = self._decision_basis()
                valid = self.basis == current
            except (ValueError, TypeError):
                valid = False
            add("decision_basis", valid, "eligibility, values, scope and versions rechecked")
        try:
            clauses = self.clauses(plan)
            for key, clause in clauses.items():
                add(key, clause in text, "required complete clause")
            add("complete_text_contract", text == self.render(plan), "exact complete-template check; no free-prose certification")
        except (KeyError, TypeError, ValueError):
            add("complete_text_contract", False, "response cannot be rendered against current state")
        for ann in annotations:
            add("supplied_unsupported_claim", not (ann["span"] in text and ann["unsupported"]),
                f"supplied annotation: {ann['span']}")
        if plan["move"] and self.protocol_enabled:
            try:
                deepcopy(self.libra).apply(plan["move"])
                okay = True
            except (ProtocolError, ValueError, KeyError):
                okay = False
            add("libra_move", okay, "public move preconditions and SEM consistency")
        return checks

    def release(self, plan=None, text=None, fault=None, fallback=True):
        plan = deepcopy(plan or self.last_plan)
        if not plan:
            raise ValueError("no response plan")
        if plan != self.last_plan:
            raise ValueError("unissued or superseded plan")
        try:
            expected = self.render(plan)
        except (KeyError, TypeError, ValueError):
            expected = ""
        annotations = []
        candidate = expected if text is None else text
        if fault == "pressure":
            candidate = ("A is only ten percentage points below your minimum. Many clients accept this compromise. "
                         "Searching further delays the decision; shall I lower your minimum to 20%?")
            annotations = [{"span": s, "unsupported": True} for s in
                           ["Many clients accept this compromise", "Searching further delays the decision"]]
        elif fault == "omit_rival":
            candidate = candidate.replace(self.clauses(plan).get("rival_advantage", ""), "").strip()
        elif fault == "wrong_cost":
            candidate = candidate.replace("0.80%", "0.60%")
        elif fault is not None:
            raise ValueError("unknown fault injection")
        checks = self.checks(plan, candidate, annotations)
        passed = all(c["passed"] for c in checks)
        self.record("candidate_checked", plan=plan, candidate=candidate,
            candidate_origin="injected_fault" if fault else ("external_candidate" if text is not None else "template"),
            annotations=annotations, checks=checks, verdict="release" if passed else "hold")
        if not passed:
            result = {"status": "held", "candidate": candidate, "checks": checks, "plan": plan}
            # A stale plan cannot be repaired merely by substituting its old wording.
            if fallback and expected and plan["revision"] == self.revision:
                substitute_checks = self.checks(plan, expected)
                if all(c["passed"] for c in substitute_checks):
                    self._commit_release(plan, expected, substitute=True)
                    result.update(status="substituted", released=expected)
            self.last_result = deepcopy(result)
            return result
        self._commit_release(plan, candidate)
        result = {"status": "released", "released": candidate, "checks": checks, "plan": plan}
        self.last_result = deepcopy(result)
        return result

    def _commit_release(self, plan, text, substitute=False):
        trial_libra = deepcopy(self.libra)
        if plan["move"] and self.protocol_enabled:
            trial_libra.apply(plan["move"])
        self.libra = trial_libra
        if plan["action"].startswith("confirm_"):
            self.pending["displayed"] = True
        if plan["action"] == "recommend":
            self.recommended = self.basis["selected"]
        self.chat.append({"speaker": "adviser", "text": text, "mode": "template"})
        self.revision += 1
        self.last_plan = None
        self.record("response_released", text=text, move=plan["move"] if self.protocol_enabled else None,
                    plan_id=plan["id"], substitute=substitute)

    def update_evidence(self, product, field, value):
        """Explicit experiment/admin action, never available to the LLM event schema."""
        if product not in self.facts or field not in {"minimum", "cost_basis_points", "financial_ok", "source"}:
            raise ValueError("invalid evidence mutation")
        self.evidence_version += 1
        self.facts[product][field] = value
        self.facts[product]["version"] = f"injected-fixture-v{self.evidence_version}"
        self._archive("injected evidence revision; previous public history retained")
        self.adaptation = None
        self.eligibility()
        self.revision += 1
        self.record("evidence_revision", product=product, field=field, value=value, origin="test_injection")

    def resume_justification(self):
        tids = [k for k, t in self.libra.targets.items() if t["holder"] == "adviser"]
        if not tids:
            raise ValueError("no outstanding adviser target")
        plan = self._make_plan("justify", target=tids[0])
        self.record("response_plan", plan=plan)
        return self.release(plan)

    def documents(self):
        suitability = {"status": "no_current_recommendation", "scope": "demo specimen, not a complete regulatory document"}
        if self.recommended and self.basis:
            suitability = {"status": "demo_specimen", "recommended": self.recommended,
                "confirmed_profile": deepcopy(self.profile), "comparison": self.comparison["id"],
                "basis": deepcopy(self.basis), "evidence_status": "stipulated",
                "scope": "illustrative suitability statement; requires firm completion and review"}
        return {"suitability_statement": suitability,
                "internal_decision_record": {"state": self.snapshot(), "history": deepcopy(self.log)}}

    def export(self, name="interactive"):
        return {"schema_version": 1, "name": name,
            "scope": "bounded application and Libra runtime; no legal-compliance certification",
            "fixture_sha256": digest(products()), "chat": deepcopy(self.chat),
            "history": deepcopy(self.log), "final_state": self.snapshot(), "documents": self.documents()}
