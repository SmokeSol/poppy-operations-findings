"""Two Personal Agents and a simulated User.

BaselineAgent follows the draft's MUSTs literally and adds nothing. HardenedAgent uses the extensions in evidence.py.

The User is not a model. Each test states in plain data what a reasonable person would understand from the text they
are shown ("reads_as"), and the User decides on that. For the hardened agent the User decides on the typed terms
themselves, because that is what the agent shows.
"""
from __future__ import annotations

from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evidence import canon, consequence, terms_hash, typed_view, verify


class User:
    def __init__(self, account: str, max_pay_minor: int = 0):
        self.account, self.max_pay_minor = account, max_pay_minor
        self.key = Ed25519PrivateKey.generate()        # stands in for a passkey bound to the Company's site
        self.asked = 0
        self.shown: list = []

    def decide(self, believes: dict, shown) -> bool:
        self.asked += 1
        self.shown.append(shown)
        return believes.get("pay", 0) <= self.max_pay_minor and not believes.get("recurring") and not believes.get("months")


class BaselineAgent:
    """The draft, read literally: show the Company's name and summary, or use a standing permission; then confirm."""

    def __init__(self, client_id: str, user: User, permission: Optional[dict] = None, careful: bool = True, reconfirm_blindly: bool = False):
        self.client_id, self.user, self.permission = client_id, user, permission
        self.careful = careful                         # careful = refuse a standing permission if any term key is unfamiliar
        self.reconfirm_blindly = reconfirm_blindly     # a bug the draft warns against, kept here as a conformance target
        self.known_keys = {"action", "cost_minor", "item"}

    def covered(self, op: dict) -> bool:
        p, t = self.permission, op.get("terms") or {}
        if not p or op.get("user_approval_required") or t.get("action") != p["action"]:
            return False
        if self.careful and set(t) - self.known_keys:
            return False                               # "MUST cover ... every term": an unfamiliar key cannot be covered
        return t.get("cost_minor", 10**9) <= p["max_cost_minor"]

    def handle(self, company, op: dict, reads_as: dict, attempts: int = 3):
        for _ in range(attempts):
            if self.covered(op):
                how = "standing_permission"
            else:
                if not self.user.decide(reads_as.get(op["revision"], {}), {"company": company.name, "summary": op["summary"]}):
                    return "declined", op
                how = "user"
            status, body = company.confirm(op["operation_id"], op["revision"], how, self.client_id)
            if status == 409:                          # terms_changed: "the Personal Agent needs a new approval for it"
                op = body["operation"]
                if self.reconfirm_blindly:
                    status, body = company.confirm(op["operation_id"], op["revision"], how, self.client_id)
                    return ("confirmed" if status == 200 else body.get("error")), body
                continue
            return ("confirmed" if status == 200 else body.get("error")), body
        return "gave_up", op


class HardenedAgent:
    """Uses typed terms, keeps the Company's signed revision, proves the User's approval, and budgets interruptions."""

    def __init__(self, client_id: str, user: User, grant: Optional[dict] = None, asks_per_company: int = 3):
        self.client_id, self.user, self.grant = client_id, user, grant
        self.grant_signature = user.key.sign(canon(grant)) if grant else None
        self.requested: set = set()                    # ids of things this agent actually asked a Company to do
        self.asks: dict = {}
        self.asks_per_company = asks_per_company
        self.folded = 0
        self.kept: dict = {}                           # operation_id -> the Company's signed revision (evidence for later)

    def handle(self, company, op: dict, reads_as: dict = None, attempts: int = 3):
        for _ in range(attempts):
            view = typed_view(op.get("terms"))
            if view is None:
                return "refused_untyped_terms", op
            signed = company.sign_revision(op)
            if not verify(signed["public_key"], signed["signature"], terms_hash(company.domain, op["operation_id"], op["revision"], op["terms"]).encode()):
                return "refused_bad_signature", op
            self.kept[op["operation_id"]] = signed
            ext = {"account": self.user.account}
            g = self.grant
            if g and not op.get("user_approval_required") and g["action"] == view["action"] and view["pay"] <= g["max_pay_minor"] \
                    and not (view["recurring"] or view["months"] or view["exit_fee"]):
                how, ext["grant"], ext["grant_signature"] = "standing_permission", g, self.grant_signature
            else:
                if op.get("in_response_to") not in self.requested:          # nobody asked for this: it does not get to interrupt
                    used = self.asks.get(company.domain, 0)
                    if used >= self.asks_per_company:
                        self.folded += 1
                        return "folded", op
                    self.asks[company.domain] = used + 1
                if not self.user.decide({"pay": view["pay"], "recurring": view["recurring"], "months": view["months"]},
                                        {"company": company.name, "lines": consequence(view)}):
                    return "declined", op
                how = "user"
                ext["approval_proof"] = self.user.key.sign(signed["terms_hash"].encode())
            status, body = company.confirm(op["operation_id"], op["revision"], how, self.client_id, **ext)
            if status == 409:
                op = body["operation"]
                continue
            if status == 403 and body.get("error") == "grant_does_not_cover" and how == "standing_permission":
                self.grant = None                      # the Company says the grant is used up: fall back to asking the User
                continue
            return ("confirmed" if status == 200 else body.get("error")), body
        return "gave_up", op
