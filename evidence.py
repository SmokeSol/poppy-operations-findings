"""Four small extensions that close the gaps the draft leaves open. Names would start with a domain you control,
as the draft requires for anyone but the protocol itself (for example "yourdomain.example/approval-proof").

  typed-terms      a few reserved keys for money, time and commitment. They govern; the summary must not contradict them.
  approval-proof   two signatures. The Company signs each revision, so the terms it offered cannot be changed afterwards;
                   the User's own key signs the hash of that exact revision (a passkey in real life; Ed25519 here).
  signed-grant     a standing permission as a signed object with limits, a running total and an end date.
  receipt          the Company signs what it did.

Sandbox only. Keys live in memory.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops import Company, Operation

RESERVED = {"pay_now_minor", "currency", "recurring_minor", "recurring_period", "commitment_months", "exit_fee_minor",
            "refund_minor", "effective_on", "action"}


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def terms_hash(company_domain: str, operation_id: str, revision: int, terms: dict) -> str:
    return hashlib.sha256(canon({"company": company_domain, "operation_id": operation_id, "revision": revision, "terms": terms})).hexdigest()


def verify(public_key, signature: bytes, message: bytes) -> bool:
    try:
        public_key.verify(signature, message)
        return True
    except (InvalidSignature, TypeError, ValueError):
        return False


def typed_view(terms: Optional[dict]) -> Optional[dict]:
    """What the terms mean for the customer, read by code. None if the terms cannot be read safely."""
    if not isinstance(terms, dict) or "pay_now_minor" not in terms or "currency" not in terms:
        return None
    for k in terms:
        if k.endswith("_minor") and k not in RESERVED:
            return None                    # a money-shaped key outside the vocabulary: refuse rather than guess
    for k in RESERVED & set(terms):
        if k.endswith("_minor") and not (isinstance(terms[k], int) and not isinstance(terms[k], bool) and 0 <= terms[k] <= 10_000_000):
            return None
    return {"pay": terms["pay_now_minor"], "refund": terms.get("refund_minor", 0), "recurring": terms.get("recurring_minor", 0),
            "months": terms.get("commitment_months", 0), "exit_fee": terms.get("exit_fee_minor", 0), "currency": terms["currency"],
            "action": terms.get("action", "")}


def consequence(view: dict) -> list[str]:
    """Written by the agent from typed fields. No Company text."""
    m = lambda v: f"{v // 100}.{v % 100:02d} {view['currency']}"      # noqa: E731
    lines = [f"YOU PAY {m(view['pay'])} now" if view["pay"] else "You pay nothing now"]
    if view["refund"]:
        lines.append(f"You receive {m(view['refund'])}")
    if view["recurring"]:
        lines.append(f"ADDS {m(view['recurring'])} EVERY MONTH")
    if view["months"]:
        lines.append(f"LOCKS YOU IN for {view['months']} months")
    if view["exit_fee"]:
        lines.append(f"Leaving early costs {m(view['exit_fee'])}")
    return lines


class ExtendedCompany(Company):
    """A Company that supports the extensions and refuses to act without them."""

    def __init__(self, name, domain, clock):
        super().__init__(name, domain, clock)
        self.key = Ed25519PrivateKey.generate()
        self.user_keys: dict[str, object] = {}       # account -> the User's public key, registered at sign-in
        self.grant_spent: dict[str, int] = {}        # grant id -> running total
        self.receipts: dict[str, dict] = {}

    def sign_revision(self, op: dict) -> dict:
        h = terms_hash(self.domain, op["operation_id"], op["revision"], op["terms"])
        return {"terms_hash": h, "signature": self.key.sign(h.encode()), "public_key": self.key.public_key()}

    def check_extension(self, op: Operation, approved_by, client_id, ext) -> Optional[str]:
        view = typed_view(op.terms)
        if view is None:
            return "typed_terms_required"
        h = terms_hash(self.domain, op.operation_id, op.revision, op.terms)
        account = ext.get("account")
        user_key = self.user_keys.get(account)
        if user_key is None:
            return "approval_proof_required"
        if approved_by == "user":
            if not verify(user_key, ext.get("approval_proof", b""), h.encode()):
                return "approval_proof_required"
            return None
        grant = ext.get("grant")
        if not grant or not verify(user_key, ext.get("grant_signature", b""), canon(grant)):
            return "grant_required"
        spent = self.grant_spent.get(grant["id"], 0)
        covered = (grant["company"] == self.domain and grant["account"] == account and grant["action"] == view["action"]
                   and self.clock() < grant["until"] and view["recurring"] == 0 and view["months"] == 0 and view["exit_fee"] == 0
                   and view["pay"] <= grant["max_pay_minor"] and spent + view["pay"] <= grant["max_total_minor"])
        if not covered:
            return "grant_does_not_cover"
        self.grant_spent[grant["id"]] = spent + view["pay"]
        return None

    def after_perform(self, op: Operation, done: dict) -> None:
        body = {"operation_id": op.operation_id, "revision": op.revision, "did_hash": hashlib.sha256(canon(done["did"])).hexdigest(),
                "terms_hash": terms_hash(self.domain, op.operation_id, op.revision, op.terms), "at": self.clock()}
        self.receipts[op.operation_id] = {"body": body, "signature": self.key.sign(canon(body)), "public_key": self.key.public_key()}
