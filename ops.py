"""Poppy "operations" extension, version 1, as I read the draft at personalagentprotocol.org on 9 October 2026.

A Company proposes an operation instead of performing an action. A Personal Agent confirms one revision, saying how it
was approved ("user" or "standing_permission"). The Company performs it at most once.

This file is the Company side, written to follow the draft literally. It is a sandbox: no network, no real company.
Where the draft is silent I have NOT added protections; that is the point of the tests.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable, Optional

FINAL = {"succeeded", "failed", "cancelled", "expired"}


@dataclass
class Operation:
    operation_id: str
    revision: int
    state: str                      # proposed | in_progress | succeeded | failed | cancelled | expired
    summary: str                    # written by the Company: "the terms in plain language"
    terms: Optional[dict]           # optional JSON version; "the Company defines its keys"
    expires_at: int
    user_approval_required: bool = False
    url: Optional[str] = None
    confirmation: Optional[dict] = None
    result: Optional[dict] = None
    in_response_to: Optional[str] = None      # NOT in the draft; used only by the proposed fix

    def public(self) -> dict:
        return copy.deepcopy(self.__dict__)


class Company:
    def __init__(self, name: str, domain: str, clock: Callable[[], int]):
        self.name, self.domain, self.clock = name, domain, clock
        self.ops: dict[str, Operation] = {}
        self.history: dict[tuple, dict] = {}   # (operation_id, revision) -> the revision as issued. Held by the Company only.
        self.log: list[dict] = []              # what the draft gives a Company as its record of a confirmation
        self.performed: list[dict] = []        # what the Company did, in its own words
        self.truth: dict[str, int] = {}        # TEST ONLY: what the customer is really charged if an operation runs (the bank statement)
        self.perform_hook: Optional[Callable[[Operation], dict]] = None   # lets a test make the Company do something else

    # -- proposing ------------------------------------------------------------------------------
    def propose(self, operation_id: str, summary: str, terms: Optional[dict] = None, ttl: int = 900, **kw) -> dict:
        if operation_id in self.ops:           # "SHOULD return the existing operation instead of proposing a new one"
            return self.ops[operation_id].public()
        op = Operation(operation_id, 1, "proposed", summary, copy.deepcopy(terms), self.clock() + ttl, **kw)
        self.ops[operation_id] = op
        self.history[(operation_id, 1)] = op.public()
        return op.public()

    def revise(self, operation_id: str, summary: str, terms: Optional[dict] = None, ttl: int = 900) -> dict:
        op = self.ops[operation_id]
        assert op.state == "proposed"
        op.revision += 1                       # "Each revision is fixed once issued"; only the latest can be confirmed
        op.summary, op.terms, op.expires_at = summary, copy.deepcopy(terms), self.clock() + ttl
        self.history[(operation_id, op.revision)] = op.public()
        return op.public()

    # -- confirming -----------------------------------------------------------------------------
    def confirm(self, operation_id: str, revision: int, approved_by: str, client_id: str, **extension) -> tuple[int, dict]:
        op = self.ops.get(operation_id)
        if op is None:
            return 404, {"error": "operation_not_found"}
        self._expire(op)
        if op.state != "proposed":
            return 200, op.public()            # already confirmed, final or expired: returned unchanged, so a retry is safe
        if revision != op.revision:
            return 409, {"error": "terms_changed", "operation": op.public()}
        if approved_by not in ("user", "standing_permission"):
            return 400, {"error": "invalid_request"}
        if approved_by == "standing_permission" and op.user_approval_required:
            return 403, {"error": "user_approval_required"}
        refused = self.check_extension(op, approved_by, client_id, extension)
        if refused:
            return 403, {"error": refused}
        op.confirmation = {"revision": revision, "approved_by": approved_by, "confirmed_at": self.clock()}
        self.log.append({"client_id": client_id, "operation_id": operation_id, **op.confirmation})
        op.state = "in_progress"
        done = (self.perform_hook or self._perform)(op)      # "MUST perform only what the confirmed revision describes"
        self.performed.append({"operation_id": operation_id, **done})
        op.state = "succeeded"
        op.result = {"summary": f"Done: {op.summary}", "data": {"reference": f"REF-{len(self.performed):05d}"}}
        self.after_perform(op, done)
        return 200, op.public()

    def check_extension(self, op, approved_by, client_id, extension) -> Optional[str]:
        return None                            # the draft: `approved_by` "works on trust"

    def after_perform(self, op, done) -> None:
        pass

    @staticmethod
    def _perform(op: Operation) -> dict:
        return {"did": copy.deepcopy(op.terms) if op.terms is not None else {"as_described": op.summary}}

    # -- reading and cancelling -----------------------------------------------------------------
    def get(self, operation_id: str) -> tuple[int, dict]:
        op = self.ops.get(operation_id)
        if op is None:
            return 404, {"error": "operation_not_found"}
        self._expire(op)
        return 200, op.public()

    def cancel(self, operation_id: str) -> tuple[int, dict]:
        op = self.ops.get(operation_id)
        if op is None:
            return 404, {"error": "operation_not_found"}
        if op.state == "proposed":
            op.state = "cancelled"
        return 200, op.public()

    def _expire(self, op: Operation) -> None:
        if op.state == "proposed" and self.clock() >= op.expires_at:
            op.state = "expired"
