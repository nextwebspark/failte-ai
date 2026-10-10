---
name: returns-policy
description: Answer questions about returns, refunds and exchanges, and start a return. Use when the caller mentions returning, refunding, exchanging or a faulty or damaged item.
metadata:
  category: customer-service
  version: "1.0"
---

# Returns and refunds

Handle the caller's return question in plain, short sentences. The full policy
is in `references/returns-policy.md`; read it with `read_skill_file` before
quoting any time limit, fee or exception. Do not guess policy details.

## Steps

1. **What and when.** Ask what they bought and roughly when it arrived.
2. **Why.** Ask whether the item is faulty or damaged, or they changed their
   mind. Faulty and changed-mind returns follow different rules.
3. **Check eligibility** against the policy file: the time window, the item's
   condition, and the excluded categories.
4. **Explain the outcome** in one or two sentences: whether they can return it,
   whether it is a refund or an exchange, who pays return postage, and how long
   the refund takes.
5. **Start the return** if they want to and it is eligible: confirm their order
   number (read it back character by character) and the email address the
   return label should go to.

## Rules

- Never promise an exception to the policy. If the caller pushes back, offer to
  pass the request to a person.
- If the order number cannot be found, ask once more, then offer a callback.
- Faulty items always get a refund or replacement, whatever the time since
  purchase; say so early to reassure the caller.
