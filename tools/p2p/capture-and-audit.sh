#!/usr/bin/env bash
# Capture live sFlow on the collector and audit it against IXP Manager's MAC table.
#
# Read-only: tcpdump copies the packets, so sflow-to-rrd-handler keeps running and
# keeps its socket. Needs tcpdump, sflowtool, curl and python3 on the collector.
#
#   sudo ./capture-and-audit.sh                 # 120s, settings from ixpmanager.conf
#   sudo ./capture-and-audit.sh -s 300 -j       # 5 minutes, JSON report
#
# The API key and URL are read from the same ixpmanager.conf the handler uses
# (<ixp> apikey / apibaseurl / macdbtype), so the audit sees the handler's MAC table.
set -euo pipefail

SECONDS_TO_CAPTURE=120
IFACE=any
PORT=6343
OUT=
JSON=
CONF=
API_URL=
API_KEY=
MACDBTYPE=

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    echo "options: -s seconds  -i interface  -p udp-port  -o outdir  -c ixpmanager.conf"
    echo "         -u api-base-url  -k api-key  -t learned|configured  -j (json)"
    exit "${1:-0}"
}

while getopts "s:i:p:o:c:u:k:t:jh" o; do
    case "$o" in
        s) SECONDS_TO_CAPTURE=$OPTARG ;; i) IFACE=$OPTARG ;; p) PORT=$OPTARG ;; o) OUT=$OPTARG ;;
        c) CONF=$OPTARG ;; u) API_URL=$OPTARG ;; k) API_KEY=$OPTARG ;; t) MACDBTYPE=$OPTARG ;;
        j) JSON=--json ;; h) usage 0 ;; *) usage 1 ;;
    esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
for bin in tcpdump sflowtool curl python3; do
    command -v "$bin" >/dev/null || { echo "missing: $bin" >&2; exit 1; }
done

# the handler's own lookup order (IXPManager::Config): <bin>/../etc, /usr/local/etc, /etc
if [ -z "$CONF" ]; then
    for c in /usr/local/etc/ixpmanager.conf /etc/ixpmanager.conf; do
        [ -f "$c" ] && { CONF=$c; break; }
    done
fi
conf_get() {  # Config::General "key = value" inside <ixp>
    [ -n "$CONF" ] || return 0
    awk -v k="$1" '/<ixp>/{s=1;next} /<\/ixp>/{s=0} s && $1==k {sub(/^[^=]*=[ \t]*/,""); print; exit}' "$CONF"
}
API_URL=${API_URL:-$(conf_get apibaseurl)}
API_KEY=${API_KEY:-$(conf_get apikey)}
MACDBTYPE=${MACDBTYPE:-$(conf_get macdbtype)}
[ -n "$API_URL" ] && [ -n "$API_KEY" ] || { echo "no API URL/key: pass -u/-k or -c ixpmanager.conf" >&2; exit 1; }
# the handler uses configured-macs only when macdbtype = configured
ENDPOINT=learned-macs
[ "$MACDBTYPE" = configured ] && ENDPOINT=configured-macs

OUT=${OUT:-$(mktemp -d /tmp/p2p-audit.XXXXXX)}
mkdir -p "$OUT"
echo "capturing udp/$PORT on $IFACE for ${SECONDS_TO_CAPTURE}s into $OUT ..." >&2
timeout "$SECONDS_TO_CAPTURE" tcpdump -q -n -i "$IFACE" -s 0 -w "$OUT/sflow.raw.pcap" "udp port $PORT" 2>"$OUT/tcpdump.log" || true
grep -E "packets (captured|dropped by kernel)" "$OUT/tcpdump.log" >&2 || true
# -i any records a datagram once per interface it crosses (bond, VLAN, bridge); the handler reads it once
python3 "$HERE/pcap-dedupe.py" "$OUT/sflow.raw.pcap" "$OUT/sflow.pcap" && rm -f "$OUT/sflow.raw.pcap"

sflowtool -r "$OUT/sflow.pcap" -l >"$OUT/sflow.lines" 2>/dev/null
sflowtool -r "$OUT/sflow.pcap" >"$OUT/sflow.full" 2>/dev/null
curl -fsS --max-time 30 -H "X-IXP-Manager-API-Key: $API_KEY" "${API_URL%/}/sflow-db-mapper/$ENDPOINT" >"$OUT/macs.json" \
    || { echo "could not fetch ${API_URL%/}/sflow-db-mapper/$ENDPOINT - the handler cannot either" >&2; exit 1; }

echo "MAC table: $ENDPOINT ($(wc -c <"$OUT/macs.json") bytes); samples: $(grep -c '^FLOW' "$OUT/sflow.lines" || true)" >&2
python3 "$HERE/sflow-audit.py" --lines "$OUT/sflow.lines" --full "$OUT/sflow.full" \
    --macs "$OUT/macs.json" --seconds "$SECONDS_TO_CAPTURE" $JSON
echo "raw files kept in $OUT (delete when done: the pcap holds traffic headers)" >&2
