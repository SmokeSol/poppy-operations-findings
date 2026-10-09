#!/usr/bin/env python3
"""Findings on the Poppy operations extension (draft read on 9 October 2026), each as a test that runs.

Left column: a Company and a Personal Agent that follow the draft literally.
Right column: the same flow with the extensions in evidence.py.

    python3 run_findings.py
"""
from __future__ import annotations

import copy
import json

from agents import BaselineAgent, HardenedAgent, User
from evidence import ExtendedCompany, terms_hash, verify
from ops import Company

NOW = [1_791_500_000]
clock = lambda: NOW[0]                                    # noqa: E731
GBP = lambda v: f"{v // 100}.{v % 100:02d}"               # noqa: E731
RESULTS = []


def charged(company) -> int:
    """Ground truth: what the customer was actually charged. In real life this is the bank statement."""
    return sum(company.truth.get(p["operation_id"], 0) for p in company.performed)


def world(extended: bool, **user_kw):
    company = (ExtendedCompany if extended else Company)("Kestrel Outfitters", "kestrel.example", clock)
    user = User("acct-7f3a", **user_kw)
    if extended:
        company.user_keys[user.account] = user.key.public_key()
    return company, user


def record(finding, draft, fixed, harm_draft, harm_fixed):
    RESULTS.append(dict(finding=finding, draft=draft, with_extensions=fixed, harm_in_draft=harm_draft, harm_with_extensions=harm_fixed))


# ----------------------------------------------------------------------------------------------- 1
def f1_two_readings():
    """The summary says one thing and the terms another. The draft does not say which governs."""
    summary = "Exchange your jacket for size M. No extra cost."
    out = []
    for extended in (False, True):
        company, user = world(extended)
        # draft: the Company chooses its own keys.  extensions: the same facts in the reserved vocabulary.
        terms = ({"action": "exchange", "item": "JKT-M", "pay_now_minor": 1700, "currency": "GBP"} if extended
                 else {"sku": "JKT-M", "price_delta": "12.00", "fees": {"restock": "5.00"}})
        op = company.propose("exc_1", summary, terms, in_response_to="req-1")
        company.truth["exc_1"] = 1700
        if extended:
            agent = HardenedAgent("https://agent.example/id", user)
            agent.requested.add("req-1")
            status, _ = agent.handle(company, op)
        else:
            status, _ = BaselineAgent("https://agent.example/id", user, careful=True).handle(company, op, {1: {"pay": 0}})
        out.append((status, charged(company), user.shown[-1]))
    (s0, c0, shown0), (s1, c1, shown1) = out
    record("1  Summary and terms disagree", f"user sees \"{shown0['summary']}\" and approves; charged {GBP(c0)}",
           f"user sees {shown1['lines']} and declines; charged {GBP(c1)}", c0 > 0, c1 > 0)
    return c0 == 1700 and c1 == 0


# ----------------------------------------------------------------------------------------------- 2
def f2_approve_means_pay():
    """'Confirm to receive your refund' on an operation that charges. Nothing in the draft types the direction of money."""
    out = []
    for extended in (False, True):
        company, user = world(extended)
        # draft: the Company's own keys.  extensions: the same facts in the reserved vocabulary.
        terms = ({"action": "refund", "pay_now_minor": 4500, "currency": "GBP"} if extended
                 else {"type": "refund_adjustment", "amount": "45.00", "dir": "D"})
        op = company.propose("ref_1", "Confirm to receive your 45.00 refund.", terms, in_response_to="req-2")
        company.truth["ref_1"] = 4500
        if extended:
            agent = HardenedAgent("https://agent.example/id", user)
            agent.requested.add("req-2")
            agent.handle(company, op)
        else:
            BaselineAgent("https://agent.example/id", user).handle(company, op, {1: {"pay": 0, "refund": 4500}})
        out.append((charged(company), user.shown[-1]))
    record("2  'Approve' that means 'pay'", f"user approves a 'refund'; charged {GBP(out[0][0])}",
           f"user sees {out[1][1]['lines']} and declines; charged {GBP(out[1][0])}", out[0][0] > 0, out[1][0] > 0)
    return out[0][0] == 4500 and out[1][0] == 0


# ----------------------------------------------------------------------------------------------- 3
def arbitrate(e: dict) -> str:
    """A neutral third party. It believes only what it can check: signatures and the bank statement.
    Under the draft the agent's confirm call is bound to its session key, so THAT the agent confirmed this operation can be
    shown. What the revision said, and whether the User approved it, cannot."""
    if not e["performed"]:
        return "nothing happened"
    proof_ok = bool(e.get("user_key") and e.get("approval_proof") and verify(e["user_key"], e["approval_proof"], e["terms_hash"].encode()))
    offer_ok = bool(e.get("signed_revision") and verify(e["signed_revision"]["public_key"], e["signed_revision"]["signature"],
                                                        e["signed_revision"]["terms_hash"].encode()))
    if not offer_ok and not proof_ok:
        if e["user_says_approved"] and e["bank_charge"] == e["user_expected_charge"]:
            return "no dispute"
        return "CANNOT TELL: the agent's call is provable; the terms and the user's approval are not"
    if offer_ok and e["bank_charge"] != e["signed_pay"]:
        return "company at fault: it charged other than the terms it signed"
    if proof_ok and not e["user_says_approved"]:
        return "user's denial refuted: their key signed these exact terms"
    return "no fault: offer, approval and charge all match"


def f3_who_can_prove_what():
    """Run four disputes. Under the draft the checkable evidence is the same in all of them."""
    terms = {"action": "exchange", "item": "JKT-M", "pay_now_minor": 0, "currency": "GBP"}
    verdicts = {False: {}, True: {}}
    for extended in (False, True):
        for case in ("honest", "agent confirmed without asking", "company charged something else", "user falsely denies approving"):
            company, user = world(extended)
            op = company.propose("exc_9", "Exchange your jacket for size M. No extra cost.", terms, in_response_to="r")
            if case == "company charged something else":
                company.truth["exc_9"] = 1700                      # the terms say 0.00; the customer's bank statement says 17.00
            e = dict(user_says_approved=case not in ("agent confirmed without asking", "user falsely denies approving"),
                     user_expected_charge=0, performed=False, terms_hash=terms_hash(company.domain, "exc_9", 1, terms))
            if extended:
                signed = company.sign_revision(op)
                e.update(signed_revision=signed, signed_pay=terms["pay_now_minor"], user_key=user.key.public_key())
                proof = b"" if case == "agent confirmed without asking" else user.key.sign(signed["terms_hash"].encode())
                status, _ = company.confirm("exc_9", 1, "user", "https://agent.example/id", account=user.account, approval_proof=proof)
                e["approval_proof"] = proof
            else:
                status, _ = company.confirm("exc_9", 1, "user", "https://agent.example/id")
            e["performed"] = bool(company.performed)
            e["bank_charge"] = charged(company)
            verdicts[extended][case] = "blocked: confirm refused without the user's proof" if (extended and status == 403) else arbitrate(e)
    for case in verdicts[False]:
        record(f"3  Dispute: {case}", verdicts[False][case], verdicts[True][case],
               case != "honest" and verdicts[False][case].startswith("CANNOT"), verdicts[True][case].startswith("CANNOT"))
    return (sum(v.startswith("CANNOT") for v in verdicts[False].values()) == 3 and not any(v.startswith("CANNOT") for v in verdicts[True].values()))


# ----------------------------------------------------------------------------------------------- 4
def f4_standing_permission():
    """'Exchange if it costs under 20' has no shape in the draft: no running total, no end date, and the keys are the Company's."""
    # (a) the same small charge, fifty times
    company, user = world(False, max_pay_minor=0)
    agent = BaselineAgent("https://agent.example/id", user, permission={"action": "exchange", "max_cost_minor": 2000})
    for i in range(50):
        agent.handle(company, company.propose(f"exc_{i}", "Exchange for another size. 19.99.", {"action": "exchange", "item": "X", "cost_minor": 1999}), {})
        company.truth[f"exc_{i}"] = 1999
    drained, asked_draft = charged(company), user.asked
    company2, user2 = world(True, max_pay_minor=0)
    grant = {"id": "g1", "company": company2.domain, "account": user2.account, "action": "exchange", "max_pay_minor": 2000,
             "max_total_minor": 2000, "until": NOW[0] + 30 * 86400}
    agent2 = HardenedAgent("https://agent.example/id", user2, grant=grant, asks_per_company=3)
    for i in range(50):
        company2.truth[f"exc_{i}"] = 1999
        agent2.handle(company2, company2.propose(f"exc_{i}", "Exchange for another size. 19.99.",
                                                 {"action": "exchange", "pay_now_minor": 1999, "currency": "GBP"}))
    record("4a Standing permission, 50 small charges", f"all 50 confirmed without the user; charged {GBP(drained)}; user asked {asked_draft} times",
           f"1 covered by the signed grant; charged {GBP(charged(company2))}; user asked {user2.asked} times, {agent2.folded} folded",
           drained > 2000, charged(company2) > 2000)
    # (b) an extra key the permission never mentioned
    rows = {}
    for label, careful in (("careless", False), ("careful", True)):
        c, u = world(False)
        a = BaselineAgent("https://agent.example/id", u, permission={"action": "exchange", "max_cost_minor": 2000}, careful=careful)
        status, _ = a.handle(c, c.propose("exc_k", "Exchange for size M, 19.99, with Kestrel Care.",
                                          {"action": "exchange", "item": "M", "cost_minor": 1999, "care_plan_monthly_minor": 999}),
                             {1: {"pay": 1999, "recurring": 999}})
        rows[label] = (status, u.asked)
    c, u = world(True)
    a = HardenedAgent("https://agent.example/id", u, grant=dict(grant, company=c.domain, account=u.account, id="g2"))
    a.requested.add("r")
    status, _ = a.handle(c, c.propose("exc_k", "Exchange for size M, 19.99, with Kestrel Care.",
                                      {"action": "exchange", "pay_now_minor": 1999, "recurring_minor": 999, "currency": "GBP"}, in_response_to="r"))
    record("4b Standing permission, an unfamiliar key adds a monthly fee",
           f"careless agent: {rows['careless'][0]} without asking; careful agent: cannot use the permission at all, asks the user ({rows['careful'][0]})",
           f"{status}; user was shown {u.shown[-1]['lines']}", rows["careless"][0] == "confirmed", status == "confirmed")
    return drained == 99_950 and charged(company2) == 1999 and rows["careless"][0] == "confirmed" and status == "declined"


# ----------------------------------------------------------------------------------------------- 5
def f5_unrequested_proposals():
    """A Company Agent can propose operations in conversation that nobody asked for. The draft sets no budget."""
    company, user = world(False)
    agent = BaselineAgent("https://agent.example/id", user)
    for i in range(1000):
        agent.handle(company, company.propose(f"up_{i}", f"Upgrade to Plus for 5.00 a month (offer {i}).", {"action": "upgrade", "cost_minor": 500}),
                     {1: {"pay": 500, "recurring": 500}})
    company2, user2 = world(True)
    agent2 = HardenedAgent("https://agent.example/id", user2)
    for i in range(1000):
        agent2.handle(company2, company2.propose(f"up_{i}", f"Upgrade to Plus for 5.00 a month (offer {i}).",
                                                 {"action": "upgrade", "pay_now_minor": 500, "recurring_minor": 500, "currency": "GBP"}))
    record("5  1,000 unrequested proposals", f"user interrupted {user.asked:,} times", f"user interrupted {user2.asked} times; {agent2.folded} folded",
           user.asked > 10, user2.asked > 10)
    return user.asked == 1000 and user2.asked == 3


# ----------------------------------------------------------------------------------------------- what the draft gets right
def conformance():
    """Checks an implementer can run. The draft's own rules, which hold in this implementation."""
    checks = []
    company, user = world(False)
    op = company.propose("exc_a", "Exchange for size M. No extra cost.", {"action": "exchange", "cost_minor": 0})
    for _ in range(100):
        company.confirm("exc_a", 1, "user", "https://agent.example/id")
    checks.append(("100 confirms through any channel perform the action once", len(company.performed) == 1))
    company.propose("exc_b", "x", {"action": "exchange", "cost_minor": 0}, ttl=60)
    NOW[0] += 61
    checks.append(("an expired operation cannot be confirmed", company.confirm("exc_b", 1, "user", "c")[1]["state"] == "expired" and len(company.performed) == 1))
    company.propose("exc_c", "x", {"action": "exchange", "cost_minor": 0}, user_approval_required=True)
    checks.append(("a standing permission is refused when the Company requires the user", company.confirm("exc_c", 1, "standing_permission", "c")[0] == 403))
    # revision swap: the user approved revision 1, the Company issues a worse revision 2 before the confirm lands
    for label, blindly in (("an agent that follows the draft asks again after a new revision", False), ("TARGET: an agent that re-confirms blindly is caught", True)):
        c, u = world(False)
        o = c.propose("exc_d", "Exchange for size M. No extra cost.", {"action": "exchange", "item": "M", "cost_minor": 0})
        c.truth["exc_d"] = 1700                                  # what revision 2 costs if it runs
        stale = copy.deepcopy(o)
        c.revise("exc_d", "Exchange for size M. 17.00.", {"action": "exchange", "item": "M", "cost_minor": 1700})
        a = BaselineAgent("https://agent.example/id", u, reconfirm_blindly=blindly)
        a.handle(c, stale, {1: {"pay": 0}, 2: {"pay": 1700}})
        checks.append((label, (charged(c) == 0) if not blindly else (charged(c) == 1700)))
    company.propose("exc_e", "x", {"action": "exchange", "cost_minor": 0})
    company.cancel("exc_e")
    checks.append(("a cancelled operation cannot be confirmed", company.confirm("exc_e", 1, "user", "c")[1]["state"] == "cancelled"))
    # two checks on the extensions themselves
    c, u = world(True)
    a = HardenedAgent("https://agent.example/id", u)
    o = c.propose("exc_f", "Exchange. No extra cost.", {"action": "exchange", "pay_now_minor": 0, "restocking_fee_minor": 500, "currency": "GBP"})
    checks.append(("extensions: terms with a money key outside the vocabulary are refused, user not asked", a.handle(c, o)[0] == "refused_untyped_terms" and u.asked == 0))
    o = c.propose("exc_g", "Exchange. No extra cost.", {"action": "exchange", "pay_now_minor": 0, "currency": "GBP"})
    other = User("acct-7f3a")                                   # someone else's key signing for this account
    forged = other.key.sign(terms_hash(c.domain, "exc_g", 1, o["terms"]).encode())
    checks.append(("extensions: an approval signed by the wrong key is refused", c.confirm("exc_g", 1, "user", "x", account=u.account, approval_proof=forged)[0] == 403))
    return checks


def main():
    ok = [f1_two_readings(), f2_approve_means_pay(), f3_who_can_prove_what(), f4_standing_permission(), f5_unrequested_proposals()]
    for r in RESULTS:
        print(f"\n{r['finding']}")
        print(f"   draft, read literally : {r['draft']}")
        print(f"   with the extensions   : {r['with_extensions']}")
    harmed_draft = sum(r["harm_in_draft"] for r in RESULTS)
    harmed_fixed = sum(r["harm_with_extensions"] for r in RESULTS)
    print(f"\nScenarios ending in harm or an unprovable dispute: draft {harmed_draft} of {len(RESULTS)}, with extensions {harmed_fixed} of {len(RESULTS)}")
    print("\nWhat the draft already gets right (these pass on the literal implementation):")
    checks = conformance()
    for name, passed in checks:
        print(f"   {'ok  ' if passed else 'FAIL'} {name}")
    print(f"\nAll findings reproduced as described: {all(ok)}; conformance checks passing: {sum(p for _, p in checks)}/{len(checks)}")
    with open("results.json", "w") as f:
        json.dump({"findings": RESULTS, "conformance": [{"check": n, "passed": p} for n, p in checks]}, f, indent=2)


if __name__ == "__main__":
    main()
