"""Libra public transitions and Boolean SEMs (COMMA 2026, Defs 4.1-4.13).

Bounded runtime of the published comparative-deliberation protocol.
Published reference: https://doi.org/10.3233/FAIA260810. This bounded code is not
a proved refinement of the complete published formalism.

This runtime implements five locutions. Package balancing is the paper's bounded
singleton policy, not a general aggregation theory. Client profiles are external
application records, not unchangeable exogenous Libra grounds.
"""
from copy import deepcopy


class ProtocolError(ValueError):
    pass


def option(x):
    return f"Opt({x})"


def perm(x, y):
    return f"Perm({x},{y})"


class Libra:
    def __init__(self, options=("C", "D")):
        self.options = list(options)
        self.owners = {}
        self.relevance = {}
        self.targets = {}
        self.models = {"adviser": {}, "client": {}}
        self.moves = []

    def snapshot(self):
        return deepcopy({
            "live": sorted(x for x in self.options if self.owners.get(option(x))),
            "owners": {k: sorted(v) for k, v in sorted(self.owners.items()) if v},
            "relevance": self.relevance, "targets": self.targets,
            "models": self.models,
            "values": {a: {v: self.value(a, v) for v in model}
                       for a, model in self.models.items()},
            "moves": self.moves,
        })

    def value(self, actor, variable, visiting=None):
        visiting = set() if visiting is None else visiting
        if variable in visiting:
            raise ProtocolError("cyclic SEM equation")
        expr = self.models[actor].get(variable)
        if expr is None:
            raise ProtocolError(f"undefined SEM variable: {variable}")
        if "constant" in expr:
            return expr["constant"]
        vals = [self.value(actor, p, visiting | {variable}) for p in expr["all"]]
        return int(all(vals))

    def _own(self, token, actor):
        self.owners.setdefault(token, set()).add(actor)

    def _relkey(self, actor, x):
        return f"{actor}:{x}"

    def _introduce(self, actor, x):
        if x not in self.options:
            raise ProtocolError("unknown option")
        self._own(option(x), actor)
        rivals = [y for y in self.options if y != x]
        self.relevance[self._relkey(actor, x)] = rivals
        for y in rivals:
            self.models[actor][perm(x, y)] = {"constant": 1}

    def apply(self, move):
        """Validate a complete transition on a copy; failures leave state untouched."""
        trial = deepcopy(self)
        trial._apply(move)
        for a, model in trial.models.items():
            for v in model:
                trial.value(a, v)
        trial.moves.append(deepcopy(move))
        self.__dict__.update(trial.__dict__)

    def _apply(self, m):
        kind, actor = m.get("kind"), m.get("actor")
        if actor not in self.models:
            raise ProtocolError("unknown participant")
        if kind == "assert":
            x = m["option"]
            if actor in self.owners.get(option(x), set()):
                raise ProtocolError("participant already owns option")
            self._introduce(actor, x)
        elif kind == "question":
            holder, token = m["holder"], m["token"]
            if actor == holder or holder not in self.owners.get(token, set()):
                raise ProtocolError("question requires another participant's owned token")
            if token.startswith("Opt("):
                x = token[4:-1]
                tid = f"Q:{holder}:{x}"
                self.targets[tid] = {"kind": "option", "holder": holder,
                    "option": x, "rivals": list(self.relevance[self._relkey(holder, x)])}
            else:
                tid = f"E:{holder}:{token}"
                self.targets[tid] = {"kind": "element", "holder": holder, "token": token}
        elif kind == "challenge":
            holder, x, y = m["holder"], m["option"], m["rival"]
            if actor == holder or x == y or y not in self.options:
                raise ProtocolError("invalid challenger or rival")
            if holder not in self.owners.get(option(x), set()):
                raise ProtocolError("challenged option is not owned by holder")
            if actor not in self.owners.get(option(y), set()):
                self._introduce(actor, y)
            self.models[actor][perm(y, x)] = {"constant": 1}
            key = self._relkey(holder, x)
            self.relevance[key] = sorted(set(self.relevance[key]) | {y})
            self.models[holder][perm(x, y)] = {"constant": 1}
            self.targets[f"T:{holder}:{x}:{y}"] = {"kind": "focal", "holder": holder,
                                                    "option": x, "rivals": [y]}
        elif kind == "justify":
            tid = m["target"]
            target = self.targets.get(tid)
            if not target or target["holder"] != actor:
                raise ProtocolError("justification requires an outstanding target")
            if target["kind"] == "element":
                grounds = m.get("grounds", [])
                if not grounds or target["token"] in grounds:
                    raise ProtocolError("nonempty, non-circular grounds required")
                for g in grounds:
                    if not isinstance(g, str) or not g.startswith("g:"):
                        raise ProtocolError("element answers require ground atoms")
                    self.models[actor][g] = {"constant": 1}
                    self._own(g, actor)
                self.models[actor][target["token"]] = {"all": list(grounds)}
            else:
                package = m.get("package", [])
                # The current application has a single relevant rival and a singleton package.
                if len(package) != 1 or len(target["rivals"]) != 1:
                    raise ProtocolError("bounded implementation requires singleton package")
                r = package[0]
                weights = {"low": 0, "mid": 1, "high": 2}
                if (r.get("for") != target["option"] or
                        r.get("against") != target["rivals"][0] or
                        r.get("j") not in weights or r.get("r") not in weights or
                        weights[r["r"]] > weights[r["j"]]):
                    raise ProtocolError("package does not answer target under Bal")
                if not r.get("ground", "").startswith("g:"):
                    raise ProtocolError("ground atom required")
                atoms = [r["ground"], f"J({r['label']},{r['for']},{r['against']})={r['j']}",
                         f"R({r['label']},{r['for']},{r['against']})={r['r']}"]
                for atom in atoms:
                    self.models[actor][atom] = {"constant": 1}
                    self._own(atom, actor)
                self.models[actor][perm(r["for"], r["against"])] = {"all": atoms}
            del self.targets[tid]
        elif kind == "retract":
            token = m["token"]
            if actor not in self.owners.get(token, set()):
                raise ProtocolError("retraction requires ownership")
            self.owners[token].remove(actor)
            if token.startswith("Opt("):
                x = token[4:-1]
                for y in self.options:
                    v = perm(x, y)
                    if v in self.models[actor]:
                        self.models[actor][v] = {"constant": 0}
                self.targets = {k: t for k, t in self.targets.items()
                                if not (t["holder"] == actor and t.get("option") == x)}
            else:
                self.models[actor][token] = {"constant": 0}
                self.targets.pop(f"E:{actor}:{token}", None)
        else:
            raise ProtocolError("unknown Libra locution")
