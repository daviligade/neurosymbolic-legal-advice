"""Conventional record-and-dependency tracker for the same bounded requirements.

Separately written implementation, not a subclass/wrapper of Libra. It is not
independently authored or independently validated. The move interface is shared
for controlled comparison; records and dependency sets replace SEM expressions.
"""
from copy import deepcopy


class ConventionalTracker:
    def __init__(self):
        self.owners = {}
        self.relevance = {}
        self.targets = {}
        self.active = {"adviser": set(), "client": set()}
        self.dependencies = {"adviser": {}, "client": {}}
        self.moves = []

    def value(self, actor, token, visiting=None):
        visiting = set() if visiting is None else visiting
        if token in visiting:
            raise ValueError("cyclic support")
        if token not in self.active[actor]:
            return 0
        return int(all(self.value(actor, d, visiting | {token})
                       for d in self.dependencies[actor].get(token, set())))

    def snapshot(self):
        return deepcopy({"owners": {k: sorted(v) for k, v in self.owners.items() if v},
            "relevance": self.relevance, "targets": self.targets,
            "support_records": {a: {t: {"active": True,
                "dependencies": sorted(self.dependencies[a].get(t, set())),
                "valid": self.value(a, t)} for t in sorted(self.active[a])}
                for a in self.active}, "moves": self.moves})

    def _introduce(self, actor, item):
        if item not in {"C", "D"}:
            raise ValueError("unknown product")
        self.owners.setdefault(f"Opt({item})", set()).add(actor)
        rival = "D" if item == "C" else "C"
        self.relevance[f"{actor}:{item}"] = [rival]
        token = f"Perm({item},{rival})"
        self.active[actor].add(token)
        self.dependencies[actor].pop(token, None)

    def apply(self, move):
        trial = deepcopy(self)
        trial._apply(move)
        for actor in trial.active:
            for token in trial.active[actor]:
                trial.value(actor, token)
        trial.moves.append(deepcopy(move))
        self.__dict__.update(trial.__dict__)

    def _apply(self, m):
        actor, kind = m.get("actor"), m.get("kind")
        if actor not in self.active:
            raise ValueError("unknown actor")
        if kind == "assert":
            item = m["option"]
            if actor in self.owners.get(f"Opt({item})", set()):
                raise ValueError("already owned")
            self._introduce(actor, item)
        elif kind == "question":
            holder, token = m["holder"], m["token"]
            if holder == actor or holder not in self.owners.get(token, set()):
                raise ValueError("question requires another actor's claim")
            if token.startswith("Opt("):
                item = token[4:-1]
                self.targets[f"Q:{holder}:{item}"] = {"kind": "option", "holder": holder,
                    "option": item, "rivals": list(self.relevance[f"{holder}:{item}"])}
            else:
                self.targets[f"E:{holder}:{token}"] = {"kind": "element", "holder": holder, "token": token}
        elif kind == "challenge":
            holder, item, rival = m["holder"], m["option"], m["rival"]
            if (holder == actor or rival not in {"C", "D"} or item == rival
                    or holder not in self.owners.get(f"Opt({item})", set())):
                raise ValueError("invalid challenge")
            if actor not in self.owners.get(f"Opt({rival})", set()):
                self._introduce(actor, rival)
            for who, x, y in [(actor, rival, item), (holder, item, rival)]:
                token = f"Perm({x},{y})"
                self.active[who].add(token)
                self.dependencies[who].pop(token, None)
            self.relevance[f"{holder}:{item}"] = [rival]
            self.targets[f"T:{holder}:{item}:{rival}"] = {"kind": "focal", "holder": holder,
                "option": item, "rivals": [rival]}
        elif kind == "justify":
            target = self.targets.get(m["target"])
            if not target or target["holder"] != actor:
                raise ValueError("no matching request")
            if target["kind"] == "element":
                inputs = m.get("grounds", [])
                if (not inputs or target["token"] in inputs
                        or any(not isinstance(g, str) or not g.startswith("g:") for g in inputs)):
                    raise ValueError("invalid ground disclosure")
                target_token = target["token"]
            else:
                package = m.get("package", [])
                if len(package) != 1 or len(target["rivals"]) != 1:
                    raise ValueError("singleton package required")
                r = package[0]
                ranks = {"low": 0, "mid": 1, "high": 2}
                if (r.get("for") != target["option"] or r.get("against") != target["rivals"][0]
                        or r.get("j") not in ranks or r.get("r") not in ranks
                        or ranks[r["j"]] < ranks[r["r"]] or not r.get("ground", "").startswith("g:")):
                    raise ValueError("inadequate answer")
                inputs = [r["ground"], f"J({r['label']},{r['for']},{r['against']})={r['j']}",
                          f"R({r['label']},{r['for']},{r['against']})={r['r']}"]
                target_token = f"Perm({r['for']},{r['against']})"
            for token in inputs:
                self.active[actor].add(token)
                self.dependencies[actor].pop(token, None)
                self.owners.setdefault(token, set()).add(actor)
            self.active[actor].add(target_token)
            self.dependencies[actor][target_token] = set(inputs)
            del self.targets[m["target"]]
        elif kind == "retract":
            token = m["token"]
            if actor not in self.owners.get(token, set()):
                raise ValueError("not owned")
            self.owners[token].remove(actor)
            if token.startswith("Opt("):
                item = token[4:-1]
                self.active[actor] = {t for t in self.active[actor] if not t.startswith(f"Perm({item},")}
                self.targets = {k: t for k, t in self.targets.items()
                                if not (t["holder"] == actor and t.get("option") == item)}
            else:
                self.active[actor].discard(token)
                self.targets.pop(f"E:{actor}:{token}", None)
        else:
            raise ValueError("unknown move")
