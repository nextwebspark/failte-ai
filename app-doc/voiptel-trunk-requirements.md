# SIP Trunk Requirements — Information Request for Voiptel

**To:** Voiptel support / provisioning
**Subject:** SIP trunk provisioning for AI voice agent platform — technical details required

---

## 1. What we are building

We operate an AI voice agent platform. We want calls to and from our Voiptel
numbers to be answered and placed by an automated voice agent rather than by a
handset or a hosted PBX extension.

To do that we need a **SIP trunk** on our account rather than (or alongside)
standard hosted-PBX service. Our platform terminates SIP directly and handles
the call media itself.

We are not asking for any API or developer platform access — a standard SIP
trunk is sufficient. We only need the connection details below so we can point
our side at yours.

---

## 2. Information we need from you

Please answer each item. Where we have suggested a format, an answer in that
shape saves a round trip.

### 2.1 Trunk provisioning

| # | Question | Why we need it |
|---|---|---|
| 1 | Can you provision a **SIP trunk** on our account, for **inbound** (calls to our numbers delivered to us) and **outbound** (calls we originate)? | Determines whether this is possible at all on our current plan |
| 2 | Is there a **channel limit** or concurrent-call cap on the trunk? What is it, and can it be raised? | We need to size concurrency for the agent |
| 3 | Is there a **separate tariff** for trunk service vs. hosted extensions? | Commercial planning |
| 4 | Any **minimum contract, setup fee, or lead time**? | Scheduling |

### 2.2 Authentication method

**Question 5:** Which authentication method does the trunk use?

- [ ] **IP authentication** — you whitelist our platform's source IP, no credentials
- [ ] **SIP registration** — we register with a username and password
- [ ] Either is available

*This is the single most important answer.* IP authentication is our strong
preference — it is simpler and more reliable for an always-on platform.

**If IP authentication:** we will send you our source IP address to whitelist as
soon as you confirm. Please tell us how many IPs you can whitelist.

**If registration:** please supply:

| Field | Value |
|---|---|
| SIP username | |
| SIP password | (send via a secure channel, not plain email) |
| Registrar host | |
| Registration expiry / refresh interval | |
| Realm / domain (if different from registrar host) | |

### 2.3 SIP signalling

| # | Question | Example answer |
|---|---|---|
| 6 | **SIP signalling hostname** we should send to | `sip.voiptel.ie` |
| 7 | **Port** | `5060` |
| 8 | Which **transports** do you accept? | UDP / TCP / TLS — please list all |
| 9 | If TLS is supported, what **port**, and do you require a specific certificate or SNI? | `5061` |
| 10 | **All source IP addresses or ranges** you will send SIP signalling *from* | We must whitelist every one — please include failover and secondary POPs, not just the primary |
| 11 | Do you support **SIP OPTIONS keepalives**? At what interval? | Used to monitor trunk health |

<br>

**Item 10 matters more than it looks.** If you signal from an address we have
not whitelisted, those calls are silently rejected at our firewall and appear
to you as if our platform is down. Please give the complete list, including any
addresses used only during failover.

### 2.4 Media (RTP)

| # | Question | Example answer |
|---|---|---|
| 12 | **RTP media IP ranges** we should expect audio from and send audio to | `x.x.x.x/24` |
| 13 | **RTP port range** | `10000–20000` |
| 14 | Do you perform any **media relay / SBC anchoring**, or is media sent end to end? | |

### 2.5 Codecs — please confirm explicitly

**Question 15:** Does the trunk support **G.711 µ-law (PCMU)** and/or
**G.711 a-law (PCMA)**?

This is a hard requirement. Our media pipeline uses G.711. **A trunk that
negotiates only G.729 or a compressed codec will not work with our platform** —
calls will connect but audio will not be usable.

If G.711 is not offered by default on your trunks, please tell us whether it
can be enabled for our account.

**Question 16:** Do you support **DTMF via RFC 2833 / telephone-event**? Our
agent uses DTMF for menu input.

### 2.6 Number presentation — inbound

**Question 17:** In what **format will you present the dialled number (DDI /
DNID)** on inbound calls to us?

Please answer with a literal example, e.g. for the number `+353 1 443 3000`:

- [ ] Full E.164 with plus — `+35314433000`
- [ ] E.164 without plus — `35314433000`
- [ ] National format — `014433000`
- [ ] Subscriber digits only — `4433000`
- [ ] Other — please give an example

**Question 18:** In what format will you present the **caller's number**
(CLI / P-Asserted-Identity)?

- [ ] `+353...` / `+44...` etc.
- [ ] National format
- [ ] Other — please give an example

**Question 19:** Which **SIP header** carries the dialled number — the
Request-URI, the To header, or a custom header? If they can differ, which
should we treat as authoritative?

<br>

**Why we ask:** our platform routes each inbound call to the correct AI agent by
matching the dialled number. We normalise to E.164 internally. If you present a
different format we can convert it — but we need to know the exact format in
advance, not discover it during testing.

### 2.7 Number presentation — outbound

| # | Question |
|---|---|
| 20 | Will you accept a **caller ID we set** on outbound calls, or do you overwrite it with a fixed number? |
| 21 | If we can set it, must it be a **number on our own Voiptel account**, or can we present any verified number? |
| 22 | Is there a **verification process** for presenting third-party caller IDs? |
| 23 | What **dialled-number format** do you expect from us on outbound — E.164 with plus, without, or national? |
| 24 | Are there **destination restrictions** on the trunk (international, premium rate, emergency services)? |

### 2.8 Numbers

| # | Question |
|---|---|
| 25 | Which of our **existing numbers** can be routed to this trunk? Please confirm the full list. |
| 26 | Can we **add more numbers** later and route them to the same trunk without re-provisioning? |
| 27 | What is the **lead time** to route a number to the trunk once requested? |
| 28 | Are there constraints on **emergency calling (112 / 999)** from a trunk? What are our obligations? |

### 2.9 Operations

| # | Question |
|---|---|
| 29 | Do you provide a **portal or CDR export** so we can reconcile call records? |
| 30 | What is the **support contact and escalation path** for trunk faults, and what are the hours? |
| 31 | Do you have a **test / staging number** we can use to validate the setup before cutting live traffic over? |
| 32 | Is there a **maintenance window** we should expect, and how are changes notified? |

---

## 3. What we will send you once you reply

Once you confirm the authentication method (Question 5), we will send:

- **Our SIP endpoint hostname and port** — the destination you route our
  inbound calls to
- **Our source IP address** — for you to whitelist, if the trunk is
  IP-authenticated
- **The transport we will use** — UDP, TCP, or TLS, depending on what you support

We can be ready to test within a day of receiving your details.

---

## 4. Summary — the five answers that unblock us

If a full response will take time, these five let us start:

1. **Question 5** — IP authentication or registration?
2. **Question 6 + 7** — your SIP host and port
3. **Question 10** — every IP you will signal from
4. **Question 15** — is G.711 (µ-law or a-law) available?
5. **Question 17** — exact format of the dialled number on inbound calls

---

## 5. Contact

| | |
|---|---|
| Account name | |
| Account number | |
| Technical contact | |
| Email | |
| Phone | |
| Preferred secure channel for credentials | |

---

*Please reply inline against the question numbers above.*
