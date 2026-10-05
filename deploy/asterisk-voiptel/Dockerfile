# Asterisk 22 built from source, for the Voiptel / SkyPhone trunk.
#
# Built rather than pulled because Dograh's media path needs chan_websocket and
# res_websocket_client, and no public Asterisk image ships both reliably. The
# build asserts they exist before it succeeds -- a missing module here would
# otherwise surface much later as "the caller hears silence".
FROM debian:bookworm-slim

ARG ASTERISK_TARBALL=https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-22-current.tar.gz

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        file \
        gettext-base \
        libcurl4-openssl-dev \
        libedit-dev \
        libjansson-dev \
        libncurses-dev \
        libsqlite3-dev \
        libsrtp2-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        pkg-config \
        procps \
        uuid-dev \
        xmlstarlet \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src
RUN curl -fsSL "$ASTERISK_TARBALL" -o asterisk.tar.gz \
    && mkdir -p asterisk \
    && tar -xzf asterisk.tar.gz -C asterisk --strip-components=1 \
    && rm asterisk.tar.gz

WORKDIR /usr/src/asterisk
RUN ./configure \
        --prefix=/usr \
        --sysconfdir=/etc \
        --localstatedir=/var \
        --with-jansson-bundled \
        --with-pjproject-bundled \
        --disable-xmldoc

# menuselect.makeopts must exist before the modules can be toggled.
RUN make menuselect.makeopts \
    && menuselect/menuselect \
        --enable chan_websocket \
        --enable res_websocket_client \
        --enable res_ari \
        --enable res_ari_channels \
        --enable res_ari_bridges \
        --enable res_ari_applications \
        --enable res_http_websocket \
        --enable codec_ulaw \
        --enable codec_alaw \
        --enable codec_g722 \
        --enable res_pjsip \
        --enable res_pjsip_outbound_registration \
        --disable BUILD_NATIVE \
        menuselect.makeopts

# The bundled pjproject build is not parallel-safe and swallows compiler output
# by default. Build it first, serially and noisily, so a failure here is
# readable instead of a bare "Error 2".
RUN make NOISY_BUILD=yes third-party

RUN make -j"$(nproc)" \
    && make install \
    && make samples \
    && ldconfig

# Fail the build now rather than a call later.
RUN set -eu; \
    for module in chan_websocket res_websocket_client res_ari res_pjsip; do \
        test -f "/usr/lib/asterisk/modules/${module}.so" \
            || { echo "FATAL: ${module}.so was not built"; exit 1; }; \
    done; \
    echo "verified: chan_websocket, res_websocket_client, res_ari, res_pjsip"

WORKDIR /
RUN rm -rf /usr/src/asterisk

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Config templates are rendered into /etc/asterisk at container start.
COPY etc/ /etc/asterisk-templates/

EXPOSE 5071/tcp 8088/tcp
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
