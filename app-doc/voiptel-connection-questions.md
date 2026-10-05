# Voiptel — follow-up on the SIP interconnect details

**Re:** SIP client interconnect for `demo7062` / extension `7065`
**Scope:** inbound calls only for now. Outbound is a separate conversation.

Thanks for the interconnect details. We have started configuring our side and
have hit two things in the details that we cannot resolve without you, plus a
few short questions. Everything below is inbound-only.

---

## 1. Two problems in the details as sent

### 1a. The registrar hostname does not answer on port 5071

You gave us:

> Registrar/domain: `demo7062.skyphonecentral.com`
> Port `5071`, Transport TCP

That hostname resolves to `54.164.171.221`, and that address **refuses**
connections on port 5071 on both TCP and UDP:

```
$ dig +short demo7062.skyphonecentral.com A
54.164.171.221

$ nc -z -w 4 54.164.171.221 5071
(connection refused)
```

Refused rather than timed out, so the host is reachable but nothing is
listening on 5071.

### 1b. There is a working SIP server, on a different address

`skyphonecentral.com` has a wildcard A record pointing at `84.39.233.90`
(`demo7061`, `demo7063`, `pbx`, `sip` and any other label all resolve there).
That address **does** answer on port 5071, on both TCP and UDP:

```
$ (SIP OPTIONS to 84.39.233.90:5071 over TCP)
SIP/2.0 200 OK
Contact: <sip:gw+zipit.skyphonecentral.com-magrathea@84.39.233.90:5071;transport=udp>
User-Agent: Sky DANCE
Allow: INVITE, ACK, BYE, CANCEL, OPTIONS, MESSAGE, INFO, UPDATE, REGISTER, ...
Supported: timer, path, replaces
```

So it looks like the `demo7062` A record is stale and overriding the wildcard.

Separately, you listed **`84.39.232.90`** as the signalling and RTP address.
That is one octet away from the live server at **`84.39.233.90`**, and
`84.39.232.90` does not respond to SIP on 5060 or 5071.

**Please confirm:**

1. Which address should we register to — will you correct the `demo7062` A
   record to `84.39.233.90`, or should we point at `84.39.233.90` directly and
   keep `demo7062.skyphonecentral.com` only as the SIP domain in the From
   header and digest realm?
2. Is `84.39.232.90` a real second address (a separate media or egress edge),
   or a typo for `84.39.233.90`?

---

## 2. What we still need before we can take a call

3. **The SIP username and password.** Please send these over a secure channel —
   a password manager share, an encrypted file, or read out by phone. Not plain
   email.

   This is genuinely the only thing left on the authentication side. Testing
   against `84.39.233.90:5071` over TCP, your server challenges us correctly and
   then rejects the attempt only because we do not have the password:

   ```
   REGISTER sip:demo7062.skyphonecentral.com  ->  SIP/2.0 401 Unauthorized
       realm="demo7062.skyphonecentral.com", qop="auth"
   REGISTER (with digest response)            ->  SIP/2.0 403 Forbidden
   ```

   So the host, the port, the TCP transport, the realm and the username `7065`
   are all confirmed working from our side.

4. **Every source IP that inbound INVITEs and RTP will arrive from.** We have to
   authorise them explicitly, and carriers commonly signal from more addresses
   than they document. A list or a CIDR range is fine; one address is usually
   not the whole story.

5. **The PSTN number (DDI) that rings extension `7065`.** We have no way to
   place an end-to-end inbound test without a number to dial.

6. **Concurrent channel limit on this extension.** A PBX extension is often
   limited to one simultaneous call. Our platform answers calls with an AI
   agent, so we need to know the ceiling — and what we can raise it to.

---

## 3. Short questions about call presentation

7. **How will inbound INVITEs be delivered?** Down the TCP connection we
   established with our REGISTER, or by opening a new connection to the Contact
   address we registered? This determines whether we need to open an inbound
   port on our side.

8. **What exactly will appear in the Request-URI and To header** on an inbound
   call? You said short extension numbers, e.g. `7065`. We need the literal
   string — `7065`, `+7065`, or a full E.164 DDI — because we match on it
   exactly.

9. **What format will the caller's number (CLI) be in?** E.164 (`+353…`),
   national (`0…`), or bare subscriber digits.

10. **DTMF method.** We expect RFC 2833 / `telephone-event`. Please confirm, and
    confirm it is offered in the SDP.

11. ~~Digest realm~~ — resolved. Your server returns
    `realm="demo7062.skyphonecentral.com"`, so no need to answer this one.

---

## 4. Optional, but worth asking

12. **Is TLS available** for signalling (port 5061 or 5081), and **SRTP** for
    media? Port 5071 as supplied is plain TCP/UDP, so signalling metadata and
    all audio cross the internet in the clear. Fine for a demo, not something we
    would want to carry live customer calls.

13. **Is the 180-second registration expiry a hard minimum**, or can it be
    raised?

---

## 5. What we will send you once you reply

- Our SIP contact address and transport, once we know whether you deliver on the
  registration socket or open a new connection.
- Our public source IP, if you need to authorise it.

## 6. Confirmed working on our side

For reference, so you know what we have already validated:

- Codecs: G.711 µ-law and a-law are both fine for us. µ-law is preferred. G.722
  is acceptable but will be transcoded.
- Your RTP range (UDP 8000–20000) is fine.
- TCP transport is fine.
- Short-extension number presentation is fine — we do not need E.164 DDIs
  presented on inbound.
- Registration over TCP to `84.39.233.90:5071` reaches your platform and gets a
  correct digest challenge. Only the password is outstanding.

---

**Contact:**

| | |
|---|---|
| Account / reference | `demo7062`, extension `7065` |
| Technical contact | |
| Email | |
| Phone | |
| Preferred secure channel for credentials | |
