#!/usr/bin/env python3
"""Standalone SIP REGISTER / OPTIONS prober.

Confirms a SIP host, port, transport and credentials in seconds, before
spending hours standing up Asterisk. Pure stdlib -- no venv, no pjsip.

    # is anything listening, and what is it?
    python3 scripts/sip_register_probe.py --host 84.39.233.90 --port 5071 --options

    # do the credentials work?
    python3 scripts/sip_register_probe.py \
        --host 84.39.233.90 --port 5071 --transport tcp \
        --user 7065 --domain demo7062.skyphonecentral.com

    # compare two candidate hosts in one run
    python3 scripts/sip_register_probe.py \
        --host 84.39.233.90 --host demo7062.skyphonecentral.com \
        --port 5071 --user 7065 --domain demo7062.skyphonecentral.com

The password is read from the SIP_PASSWORD environment variable, or prompted
for interactively. Never pass it on the command line -- it lands in your shell
history and in `ps`.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import socket
import sys
import uuid

DEFAULT_EXPIRES = 180
RECV_BYTES = 65535


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def _token(length: int = 16) -> str:
    return uuid.uuid4().hex[:length]


class SipDialog:
    """One REGISTER/OPTIONS transaction over a single socket."""

    def __init__(self, host: str, port: int, transport: str, timeout: float):
        self.host = host
        self.port = port
        self.transport = transport.lower()
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.local_addr = ("0.0.0.0", 0)

    def connect(self) -> None:
        if self.transport == "tcp":
            self.sock = socket.create_connection((self.host, self.port), self.timeout)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.connect((self.host, self.port))
        self.sock.settimeout(self.timeout)
        self.local_addr = self.sock.getsockname()

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def send_recv(self, message: str) -> str:
        assert self.sock is not None, "connect() first"
        self.sock.sendall(message.encode())
        # A provisional 100 Trying can arrive before the real answer.
        while True:
            data = self.sock.recv(RECV_BYTES).decode(errors="replace")
            if not data.startswith("SIP/2.0 100"):
                return data


def build_request(
    *,
    method: str,
    target_uri: str,
    from_uri: str,
    to_uri: str,
    contact: str,
    local_addr: tuple[str, int],
    transport: str,
    call_id: str,
    from_tag: str,
    cseq: int,
    expires: int | None,
    authorization: str | None,
) -> str:
    lines = [
        f"{method} {target_uri} SIP/2.0",
        (
            f"Via: SIP/2.0/{transport.upper()} {local_addr[0]}:{local_addr[1]}"
            f";branch=z9hG4bK{_token()};rport"
        ),
        "Max-Forwards: 70",
        f"From: <{from_uri}>;tag={from_tag}",
        f"To: <{to_uri}>",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} {method}",
        f"Contact: <{contact}>",
        "User-Agent: dograh-sip-probe",
    ]
    if expires is not None:
        lines.append(f"Expires: {expires}")
    if authorization:
        lines.append(authorization)
    lines += ["Accept: application/sdp", "Content-Length: 0", "", ""]
    return "\r\n".join(lines)


def parse_challenge(response: str) -> tuple[str, dict[str, str]] | None:
    """Return (header_name, params) for a WWW-/Proxy-Authenticate header."""
    for header in ("WWW-Authenticate", "Proxy-Authenticate"):
        match = re.search(
            rf"^{header}:\s*Digest\s+(.*)$", response, re.MULTILINE | re.IGNORECASE
        )
        if not match:
            continue
        params = {
            key: quoted or bare
            for key, quoted, bare in re.findall(
                r'(\w+)\s*=\s*(?:"([^"]*)"|([^,\s]+))', match.group(1)
            )
        }
        auth_header = (
            "Authorization" if header == "WWW-Authenticate" else "Proxy-Authorization"
        )
        return auth_header, params
    return None


def build_authorization(
    *,
    header_name: str,
    params: dict[str, str],
    username: str,
    password: str,
    method: str,
    uri: str,
) -> str:
    realm = params.get("realm", "")
    nonce = params.get("nonce", "")
    opaque = params.get("opaque")
    qop_options = [q.strip() for q in params.get("qop", "").split(",") if q.strip()]
    algorithm = params.get("algorithm", "MD5")

    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")

    fields = {
        "username": username,
        "realm": realm,
        "nonce": nonce,
        "uri": uri,
        "algorithm": algorithm,
    }

    if "auth" in qop_options:
        cnonce = _token(8)
        nc = "00000001"
        fields["response"] = _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
        fields["qop"] = "auth"
        fields["nc"] = nc
        fields["cnonce"] = cnonce
    else:
        fields["response"] = _md5(f"{ha1}:{nonce}:{ha2}")

    if opaque:
        fields["opaque"] = opaque

    unquoted = {"algorithm", "qop", "nc"}
    rendered = ", ".join(
        f"{key}={value}" if key in unquoted else f'{key}="{value}"'
        for key, value in fields.items()
    )
    return f"{header_name}: Digest {rendered}"


def status_line(response: str) -> str:
    return response.splitlines()[0] if response else "<empty response>"


def show(label: str, payload: str, verbose: bool) -> None:
    print(f"\n--- {label} ---")
    if verbose:
        print(payload.rstrip())
    else:
        for line in payload.splitlines():
            if not line.strip():
                break
            print(line)


def run_options(args: argparse.Namespace, host: str) -> bool:
    dialog = SipDialog(host, args.port, args.transport, args.timeout)
    try:
        dialog.connect()
    except OSError as exc:
        print(f"  connect failed: {type(exc).__name__}: {exc}")
        return False

    target = f"sip:{args.domain or host}"
    request = build_request(
        method="OPTIONS",
        target_uri=target,
        from_uri="sip:probe@example.invalid",
        to_uri=target,
        contact=f"sip:probe@{dialog.local_addr[0]}:{dialog.local_addr[1]}",
        local_addr=dialog.local_addr,
        transport=args.transport,
        call_id=uuid.uuid4().hex,
        from_tag=_token(12),
        cseq=1,
        expires=None,
        authorization=None,
    )
    show("OPTIONS request", request, args.verbose)
    try:
        response = dialog.send_recv(request)
    except OSError as exc:
        print(f"  no reply: {type(exc).__name__}: {exc}")
        return False
    finally:
        dialog.close()

    show("OPTIONS response", response, args.verbose)
    return response.startswith("SIP/2.0 200")


def run_register(args: argparse.Namespace, host: str, password: str) -> bool:
    domain = args.domain or host
    dialog = SipDialog(host, args.port, args.transport, args.timeout)
    try:
        dialog.connect()
    except OSError as exc:
        print(f"  connect failed: {type(exc).__name__}: {exc}")
        return False

    target = f"sip:{domain}"
    aor = f"sip:{args.user}@{domain}"
    contact = (
        f"sip:{args.user}@{dialog.local_addr[0]}:{dialog.local_addr[1]}"
        f";transport={args.transport}"
    )
    call_id = uuid.uuid4().hex
    from_tag = _token(12)

    def request(cseq: int, authorization: str | None) -> str:
        return build_request(
            method="REGISTER",
            target_uri=target,
            from_uri=aor,
            to_uri=aor,
            contact=contact,
            local_addr=dialog.local_addr,
            transport=args.transport,
            call_id=call_id,
            from_tag=from_tag,
            cseq=cseq,
            expires=args.expires,
            authorization=authorization,
        )

    try:
        first = request(1, None)
        show("REGISTER (unauthenticated)", first, args.verbose)
        response = dialog.send_recv(first)
        show("response", response, args.verbose)

        if response.startswith("SIP/2.0 200"):
            print(
                "\n  Registered with no challenge -- the server is IP-authenticating us."
            )
            return True

        challenge = parse_challenge(response)
        if challenge is None:
            print(f"\n  {status_line(response)} and no digest challenge to answer.")
            return False

        header_name, params = challenge
        print(
            f"\n  Challenged: realm={params.get('realm')!r} qop={params.get('qop')!r}"
        )

        authorization = build_authorization(
            header_name=header_name,
            params=params,
            username=args.user,
            password=password,
            method="REGISTER",
            uri=target,
        )
        second = request(2, authorization)
        show("REGISTER (authenticated)", second, args.verbose)
        response = dialog.send_recv(second)
        show("response", response, args.verbose)
        return response.startswith("SIP/2.0 200")
    except OSError as exc:
        print(f"  no reply: {type(exc).__name__}: {exc}")
        return False
    finally:
        dialog.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a SIP host with OPTIONS or REGISTER.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--host",
        action="append",
        required=True,
        help="SIP host or IP. Repeat to compare candidates in one run.",
    )
    parser.add_argument("--port", type=int, default=5060)
    parser.add_argument("--transport", choices=("tcp", "udp"), default="tcp")
    parser.add_argument("--user", help="SIP username / extension")
    parser.add_argument(
        "--domain",
        help="SIP domain for the AOR and Request-URI, if it differs from --host",
    )
    parser.add_argument("--expires", type=int, default=DEFAULT_EXPIRES)
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument(
        "--options",
        action="store_true",
        help="Send OPTIONS instead of REGISTER (no credentials needed)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print full SIP messages"
    )
    args = parser.parse_args()

    password = ""
    if not args.options:
        if not args.user:
            parser.error("--user is required unless --options is given")
        password = os.environ.get("SIP_PASSWORD", "")
        if not password:
            password = getpass.getpass("SIP password: ")
        if not password:
            parser.error("no password supplied")

    results: list[tuple[str, bool]] = []
    for host in args.host:
        print(f"\n{'=' * 70}\n{host}:{args.port}/{args.transport}\n{'=' * 70}")
        if args.options:
            ok = run_options(args, host)
        else:
            ok = run_register(args, host, password)
        results.append((host, ok))

    print(f"\n{'=' * 70}\nSummary\n{'=' * 70}")
    for host, ok in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {host}:{args.port}/{args.transport}")

    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
