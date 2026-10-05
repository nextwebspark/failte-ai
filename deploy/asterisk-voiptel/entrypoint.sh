#!/bin/sh
# Render the config templates, then hand off to Asterisk in the foreground.
set -eu

# Only these names are substituted. The dialplan is full of Asterisk's own
# ${EXTEN} and ${CALLERID(num)} -- an unrestricted envsubst would eat them.
SUBSTITUTE='${SIP_USER} ${SIP_PASS} ${SIP_DOMAIN} ${REGISTRAR_HOST}
${REGISTRAR_PORT} ${STASIS_APP} ${ARI_PASSWORD} ${PUBLIC_IP}
${DOGRAH_WS_URI} ${RTP_START} ${RTP_END} ${REGISTRATION_EXPIRY}
${PBX_SIGNALLING_IPS} ${INBOUND_MODE}'

: "${SIP_USER:?SIP_USER is required -- copy .env.example to .env}"
: "${SIP_PASS:?SIP_PASS is required -- copy .env.example to .env}"
: "${REGISTRAR_HOST:?REGISTRAR_HOST is required}"
: "${STASIS_APP:?STASIS_APP is required}"
: "${ARI_PASSWORD:?ARI_PASSWORD is required}"

: "${SIP_DOMAIN:=$REGISTRAR_HOST}"
: "${REGISTRAR_PORT:=5071}"
: "${REGISTRATION_EXPIRY:=180}"
: "${RTP_START:=10000}"
: "${RTP_END:=10050}"
: "${PUBLIC_IP:=}"
: "${DOGRAH_WS_URI:=ws://host.docker.internal:8000/api/v1/telephony/ws/ari}"
: "${PBX_SIGNALLING_IPS:=84.39.233.90}"
: "${INBOUND_MODE:=echo}"

export SIP_USER SIP_PASS SIP_DOMAIN REGISTRAR_HOST REGISTRAR_PORT \
       STASIS_APP ARI_PASSWORD PUBLIC_IP DOGRAH_WS_URI \
       RTP_START RTP_END REGISTRATION_EXPIRY PBX_SIGNALLING_IPS INBOUND_MODE

for template in /etc/asterisk-templates/*.conf; do
    name=$(basename "$template")
    envsubst "$SUBSTITUTE" < "$template" > "/etc/asterisk/$name"
done

# PUBLIC_IP is optional: with it, Asterisk advertises the public address in SDP.
# Without it, we rely on the far end latching onto our RTP source address.
if [ -z "$PUBLIC_IP" ]; then
    sed -i '/^external_media_address/d;/^external_signaling_address/d' \
        /etc/asterisk/pjsip.conf
    echo "PUBLIC_IP unset -- external_*_address stripped, relying on far-end latching"
else
    echo "advertising PUBLIC_IP=$PUBLIC_IP in SDP and Contact"
fi

# type=identify needs one "match =" line per source IP. Built into a file and
# spliced in with `sed r` rather than awk -v, which cannot take a multi-line
# value portably.
matches_file=$(mktemp)
printf '%s\n' "$PBX_SIGNALLING_IPS" | tr ',' '\n' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | sed '/^$/d' \
    | sed 's/^/match = /' > "$matches_file"

if [ ! -s "$matches_file" ]; then
    echo "PBX_SIGNALLING_IPS empty -- falling back to REGISTRAR_HOST for identify"
    echo "match = $REGISTRAR_HOST" > "$matches_file"
fi

sed -e "/^; IDENTIFY_MATCHES\$/r $matches_file" /etc/asterisk/pjsip.conf \
    > /etc/asterisk/pjsip.conf.tmp \
    && mv /etc/asterisk/pjsip.conf.tmp /etc/asterisk/pjsip.conf
rm -f "$matches_file"

echo "identify matches:"; sed -n '/^type = identify$/,$p' /etc/asterisk/pjsip.conf | sed -n 's/^match = /  /p'

echo "rendered config for ${SIP_USER}@${SIP_DOMAIN} -> ${REGISTRAR_HOST}:${REGISTRAR_PORT} (inbound mode: ${INBOUND_MODE})"

exec asterisk -f -vvv -p
