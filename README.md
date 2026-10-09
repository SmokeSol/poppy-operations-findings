# Poppy operations extension: five findings, with tests and working fixes

Amine El Afrit · [amineelafrit.xyz](https://amineelafrit.xyz) · 9 October 2026

Scope: the `operations` extension, version 1, of the [Personal Agent Protocol draft](https://personalagentprotocol.org/docs/extensions/operations),
as published on 9 October 2026. Everything here runs in a sandbox with no network: `python3 run_findings.py`
(Python 3.11+, `pip install cryptography`). Quoted phrases are from the draft as of that date; it says every part can
still change, so please open an issue if a quote or a reading here no longer matches the text.

## What the draft gets right

These hold in a literal implementation (`ops.py`) and are kept as conformance checks:

- 100 confirmations through any channel perform the action once.
- An expired or cancelled operation cannot be confirmed.
- A standing permission is refused when the Company requires the User.
- Text from the Company never counts as approval, and a new revision needs a new approval.
- The draft is candid about its own limit: a confirmation "doesn't prove that the User saw the terms or approved them."

The findings are about what follows from that last sentence, and from two places where the draft is silent.

## Results

| # | Scenario | Draft, read literally | With the four extensions |
|---|---|---|---|
| 1 | Summary and terms disagree | User approves "No extra cost"; charged 17.00 | User is shown "YOU PAY 17.00 GBP now"; declines |
| 2 | "Confirm to receive your refund" on an operation that charges | User approves; charged 45.00 | User is shown "YOU PAY 45.00 GBP now"; declines |
| 3a | Dispute: agent confirmed without asking | Cannot tell: the call is provable, the approval is not | Blocked: confirm refused without the User's proof |
| 3b | Dispute: Company charged other than the terms | Cannot tell | Company at fault: it charged other than the terms it signed |
| 3c | Dispute: User falsely denies approving | Cannot tell | Denial refuted: the User's key signed these exact terms |
| 4a | Standing permission "under 20", used 50 times | All 50 confirmed; charged 999.50; User never asked | 1 confirmed under a signed grant with a running total; charged 19.99 |
| 4b | Standing permission, an unfamiliar key adds a monthly fee | Careless agent confirms; careful agent cannot use the permission at all | User is shown "ADDS 9.99 GBP EVERY MONTH"; declines |
| 5 | 1,000 proposals nobody asked for | User interrupted 1,000 times | User interrupted 3 times; 997 folded |

Eight of nine scenarios end in harm or an unprovable dispute under the draft, none with the extensions.

## The findings

**1. Two readings of one operation.** The Company writes a `summary` "so the User can decide from it alone" and may add
`terms` whose keys "the Company defines". The draft does not say which governs if they disagree, and the agent cannot
read keys it has never seen. *Fix:* a small reserved vocabulary for money, time and commitment (`pay_now_minor`,
`recurring_minor`, `commitment_months`, ...). The reserved keys govern, and the agent writes the consequence line itself.

**2. Direction of money is not typed.** An operation can be worded as something the User receives while it charges
them. Requests that the payer approves were a known fraud channel on India's UPI, which ended person-to-person
collect requests in October 2025. *Fix:* the same vocabulary; "YOU PAY" comes from a typed field, never from Company text.

**3. Nobody can prove anything afterwards.** The confirm request carries a revision number and `approved_by`, which
"works on trust". The agent's request is bound to its session key, so a Company can show that this agent confirmed
this operation. What the revision said is held only by the Company, unsigned, and whether the User approved it rests on
the agent's word. In three different disputes the evidence a neutral party can check is the same. The draft notes
that a Company wanting proof can ask the User on its own site, but "This extension doesn't define that step." *Fix:* the Company signs each revision; the User's own key
(a passkey in practice) signs the hash of that exact revision; the Company signs a receipt. Each is one small field.

**4. Standing permissions have no shape.** The draft requires a permission to cover "every term of the revision" but
does not say how one is recorded. With Company-defined keys an agent must either guess (and be exploited) or ask the
User every time. There is no running total and no end date. *Fix:* a signed grant with a per-action limit, a
cumulative limit and an expiry, checked by both sides.

**5. Proposals have no budget.** I found no rule tying a proposal to something the agent asked for, and no limit on
how many a Company may make. *Fix:* an `in_response_to` field; anything unrequested goes into a folded list and does
not interrupt the User beyond a small budget.

## Limits of this work

- The User is simulated: each test states what a reasonable person would understand from the text shown.
- No real model was used. Whether a real agent is steered by a hostile `summary` is untested here and is the obvious next experiment.
- Findings 1 and 2 need a Company that is dishonest or careless. Finding 3 does not: it applies to honest parties who later disagree.
- This is one reading of a draft that says every part can still change.

## Proposed extensions

Each would be named under a domain its author controls, as the draft requires. All are optional and leave the core unchanged.

| Extension | What it adds |
|---|---|
| typed terms | Reserved keys for money, time and commitment; they govern, and the agent writes the consequence line |
| approval proof | The Company signs the revision; the User's key signs the hash of that revision |
| signed grant | A standing permission with a per-action limit, a running total and an end date |
| receipt | The Company signs what it did |

## Files

| File | What it is |
|---|---|
| `ops.py` | The operations extension, Company side, following the draft literally |
| `agents.py` | A literal agent, a hardened agent, a simulated User |
| `evidence.py` | The four extensions: typed terms, approval proof (signed revision plus the User's signature), signed grant, receipt |
| `run_findings.py` | Runs every scenario on both and prints the table above |
