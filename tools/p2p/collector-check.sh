#!/usr/bin/env bash
# Health check for the IXP Manager sFlow collector behind the P2P graphs.
#
# Read-only. Run as root on the collector (it reads other processes' /proc entries):
#
#   sudo ./collector-check.sh                  # ~130s: watches two of the handler's 60s flush cycles
#   sudo ./collector-check.sh -w 600           # when one flush may take minutes
#   sudo ./collector-check.sh -x http://collector/grapher-sflow/   # also check the HTTP export
#
# Each line is OK / WARN / FAIL with what it means for the graphs. The checks follow
# tools/runtime/sflow/sflow-to-rrd-handler in IXP Manager 7.4.0; see docs/p2p-graphs.md.
set -uo pipefail

WINDOW=130
EXPORT_URL=
CONF=
PORT=
SOCK=/var/run/rrdcached.sock   # hard-coded in sflow-to-rrd-handler
COUNT_FILES=1

while getopts "w:x:c:p:nh" o; do
    case "$o" in
        w) WINDOW=$OPTARG ;; x) EXPORT_URL=$OPTARG ;; c) CONF=$OPTARG ;; p) PORT=$OPTARG ;;
        n) COUNT_FILES= ;;
        h) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; echo "options: -w secs -x export-url -c ixpmanager.conf -p sflow-port -n (skip file count)"; exit 0 ;;
        *) exit 1 ;;
    esac
done

FAILS=0 WARNS=0
ok()   { printf '  OK    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; WARNS=$((WARNS + 1)); }
fail() { printf '  FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
info() { printf '        %s\n' "$*"; }
head_() { printf '\n== %s\n' "$*"; }

if [ -z "$CONF" ]; then
    for c in /usr/local/etc/ixpmanager.conf /etc/ixpmanager.conf; do [ -f "$c" ] && { CONF=$c; break; }; done
fi
conf_get() {
    [ -n "$CONF" ] || return 0
    awk -v k="$1" '/<ixp>/{s=1;next} /<\/ixp>/{s=0} s && $1==k {sub(/^[^=]*=[ \t]*/,""); print; exit}' "$CONF"
}
BASE=$(conf_get sflow_rrddir); BASE=${BASE:-/data/ixpmatrix}
API_URL=$(conf_get apibaseurl); API_KEY=$(conf_get apikey)
MACDBTYPE=$(conf_get macdbtype); OPTS=$(conf_get sflowtool_opts)
RRDCACHED_CONF=$(conf_get sflow_rrdcached)

# --- processes ------------------------------------------------------------------------
head_ "Handler process"
# the oldest perl process running the handler (not a wrapper shell, not the improved handler's flush children)
HPID=
for p in $(pgrep -o -f '[s]flow-to-rrd-handler') $(pgrep -f '[s]flow-to-rrd-handler'); do
    case "$(cat /proc/"$p"/comm 2>/dev/null)" in perl|sflow-to-rrd-*) HPID=$p; break ;; esac
done
IMPROVED=
SPID=$(pgrep -x sflowtool | head -1)
if [ -z "$HPID" ]; then
    fail "sflow-to-rrd-handler is not running - no P2P data is being recorded"
else
    ET=$(ps -o etimes= -p "$HPID" | tr -d ' ')
    ok "sflow-to-rrd-handler pid $HPID, up $((ET / 3600))h$((ET % 3600 / 60))m"
    [ "$ET" -lt 3600 ] && warn "started less than an hour ago - check the journal for crash loops"
    ARGS=$(tr '\0' ' ' </proc/"$HPID"/cmdline)
    info "command: $ARGS"
    FT=$(sed -n 's/.*--flushtimer[ =]*\([0-9]\+\).*/\1/p' <<<"$ARGS")
    for w in $ARGS; do
        [ -f "$w" ] && grep -q 'drop-in replacement for IXP Manager' "$w" 2>/dev/null && IMPROVED=1
    done
    [ -n "$IMPROVED" ] && info "this is the improved handler from tools/p2p: its own 'flush:' lines in the journal give interval, duration and drops"
    case "$ARGS" in *--infraid*)
        fail "--infraid is set: in 7.4.0 the handler's 'qw ( \$infraid )' never interpolates, so every sample is dropped" ;;
    esac
    case "$ARGS" in *--debug*|*--insanedebug*) warn "running with --debug: logs every dropped sample and slows the read loop" ;; esac
fi
[ -n "$SPID" ] && ok "sflowtool pid $SPID: $(tr '\0' ' ' </proc/"$SPID"/cmdline)" || fail "sflowtool is not running"
if [ -n "$OPTS" ]; then
    P=$(sed -n 's/.*-p[ ]*\([0-9]\+\).*/\1/p' <<<"$OPTS"); PORT=${PORT:-$P}
fi
PORT=${PORT:-6343}

cpu_ticks() { awk '{print $14 + $15}' "/proc/$1/stat" 2>/dev/null; }

# --- start the rate measurements (both need a time window) ---------------------------
udp_line() {  # drops and rx queue of the socket bound to $PORT
    local hex; hex=$(printf '%04X' "$PORT")
    local q d
    read -r q d < <(awk -v p=":$hex" 'FNR>1 && substr($2, length($2)-4)==p {split($5,x,":"); print x[2], $NF; exit}' \
        /proc/net/udp /proc/net/udp6 2>/dev/null)
    [ -n "$q" ] && echo "$((16#$q)) $d"
}
snmp_rcvbuf() { awk '/^Udp:/{if(!h){split($0,k);h=1;next} split($0,v); for(i in k) if(k[i]=="RcvbufErrors") print v[i]; exit}' /proc/net/snmp; }
rrdc_stat() {
    [ -S "$SOCK" ] || return 1
    if command -v socat >/dev/null; then printf 'STATS\nQUIT\n' | socat -t 5 - "UNIX-CONNECT:$SOCK" 2>/dev/null
    else printf 'STATS\nQUIT\n' | timeout 5 nc -U "$SOCK" 2>/dev/null; fi
}
stat_val() { awk -v k="$1:" '$1==k {print $2; exit}'; }

U0=$(udp_line); R0=$(snmp_rcvbuf); S0=$(rrdc_stat); C0=${HPID:+$(cpu_ticks "$HPID")}
T0=$(date +%s)

# --- static checks while the window runs ----------------------------------------------
head_ "Configuration ($CONF)"
[ -n "$CONF" ] || warn "no ixpmanager.conf found - using defaults"
info "sflow_rrddir=$BASE  macdbtype=${MACDBTYPE:-learned}  sflowtool_opts='${OPTS:--l}'  port=$PORT"
[ "${RRDCACHED_CONF:-1}" = 0 ] && warn "sflow_rrdcached = 0: every update is a direct disk write - far slower at this scale"

if [ -n "$API_URL" ] && [ -n "$API_KEY" ]; then
    EP=learned-macs; [ "$MACDBTYPE" = configured ] && EP=configured-macs
    TMP=$(mktemp)
    read -r CODE TT < <(curl -s -o "$TMP" -w '%{http_code} %{time_total}\n' --max-time 30 \
        -H "X-IXP-Manager-API-Key: $API_KEY" "${API_URL%/}/sflow-db-mapper/$EP")
    if [ "$CODE" = 200 ]; then
        read -r NVLI NMAC TAGS PAIRS < <(python3 -c '
import json,sys
from collections import defaultdict
d=json.load(open(sys.argv[1])) or {}
v={x for i in d.values() for t in i.values() for x in t.values()}
m=sum(len(t) for i in d.values() for t in i.values())
per=defaultdict(set)
for i in d.values():
    for t, macs in i.items(): per[t].update(macs.values())
# the handler pairs interfaces only within one VLAN tag
pairs=sum(len(s)*(len(s)-1) for s in per.values())
print(len(v), m, ",".join(sorted(per)) or "-", pairs)' "$TMP")
        ok "$EP: $NVLI VLAN interfaces, $NMAC MACs on tags $TAGS (fetched in ${TT}s)"
        [ "${NVLI:-0}" -gt 0 ] || fail "the MAC table is empty - the handler drops every sample"
        awk -v t="$TT" 'BEGIN{exit !(t > 1.0)}' && warn "the handler re-fetches this every flush and reads no samples meanwhile (${TT}s)"
        UPPER=$(grep -o '"[0-9A-F]*[A-F][0-9A-F]*"' "$TMP" | grep -c . || true)
        [ "$UPPER" -gt 0 ] && fail "$UPPER MAC(s) stored in upper case - sflowtool prints lower case, those members are never matched"
    elif [ "$CODE" = 401 ]; then
        fail "$EP: HTTP 401 - API key refused or expired (7.4 keys expire); the handler keeps the old table and exits after 24h"
    else
        fail "$EP: HTTP $CODE - the handler cannot refresh its MAC table"
    fi
    rm -f "$TMP"
else
    warn "apibaseurl/apikey not found in ixpmanager.conf"
fi

head_ "rrdcached"
RPID=$(pgrep -x rrdcached | head -1)
if [ -z "$RPID" ]; then
    fail "rrdcached is not running - the handler writes through unix:$SOCK and every update fails"
else
    RARGS=$(tr '\0' ' ' </proc/"$RPID"/cmdline)
    ok "rrdcached pid $RPID: $RARGS"
    [ -S "$SOCK" ] || fail "$SOCK missing - the handler cannot reach rrdcached (path is hard-coded)"
    W=$(sed -n 's/.*-w[ ]*\([0-9]\+\).*/\1/p' <<<"$RARGS"); W=${W:-300}
    Z=$(sed -n 's/.*-z[ ]*\([0-9]\+\).*/\1/p' <<<"$RARGS"); Z=${Z:-0}
    LAG=$((W + Z))
    if [ "$LAG" -gt 900 ]; then
        warn "write delay -w $W (+ -z $Z): files on disk lag up to $((LAG / 60)) min; IXP Manager copies them over HTTP, so the newest part of every graph reads as zero"
    else
        ok "write delay -w $W (+ -z $Z): on-disk files at most $((LAG / 60)) min behind"
    fi
fi

head_ "Socket buffer"
RMEM=$(cat /proc/sys/net/core/rmem_max)
if [ "$RMEM" -lt 2000000 ]; then
    fail "net.core.rmem_max=$RMEM: sflowtool asks for 2000000 bytes and is capped here - bursts during each flush overflow it"
else
    ok "net.core.rmem_max=$RMEM"
fi

head_ "Disk ($BASE)"
if [ -d "$BASE" ]; then
    df -h "$BASE" | awk 'NR==2{printf "        %s used of %s (%s), %s free\n", $3, $2, $5, $4}'
    PCT=$(df --output=pcent "$BASE" | tail -1 | tr -dc 0-9); IPCT=$(df --output=ipcent "$BASE" | tail -1 | tr -dc 0-9)
    [ "${PCT:-0}" -ge 90 ] && fail "disk ${PCT}% full - new RRDs cannot be created" || ok "disk ${PCT}% used"
    [ "${IPCT:-0}" -ge 90 ] && fail "inodes ${IPCT}% used" || ok "inodes ${IPCT:-?}% used"
else
    fail "$BASE does not exist"
fi

if [ -n "$COUNT_FILES" ] && [ -d "$BASE" ]; then
    head_ "RRD inventory (use -n to skip)"
    NP2P=0
    for d in "$BASE"/ipv{4,6}/{bytes,pkts}/p2p; do
        [ -d "$d" ] || continue
        n=$(find "$d" -name '*.rrd' 2>/dev/null | wc -l); NP2P=$((NP2P + n))
        info "$(printf '%9d' "$n")  ${d#"$BASE"/}"
    done
    NIND=$(find "$BASE" -path '*/individual/*' -name '*.rrd' 2>/dev/null | wc -l)
    info "$(printf '%9d' "$NIND")  individual"
    if [ -n "${NVLI:-}" ] && [ "$NVLI" -gt 1 ]; then
        FULL=$((4 * ${PAIRS:-0}))
        info "current pairs: ${PAIRS:-?} ordered pairs of interfaces on the same VLAN tag, x2 protocols x2 types = $FULL files"
        if [ -z "$IMPROVED" ]; then
            info "the stock handler updates every one of them on every flush, traffic or not"
        fi
        if [ "$NP2P" -gt "$FULL" ]; then
            STALE=$((NP2P - FULL))
            warn "$STALE pair files (~$((STALE * 182 / 1000000)) GB) belong to interfaces no longer in the MAC table: never updated again"
            info "list them: find $BASE -path '*/p2p/*' -name '*.rrd' -mtime +7   (current pairs are rewritten every few minutes)"
        fi
    fi
fi

# --- finish the rate measurements -------------------------------------------------------
# Is anyone reading the samples? sflowtool writes each one into a pipe to the handler. When the
# handler stops reading (the stock handler while it flushes) the pipe fills and sflowtool blocks in
# write() - and while it is blocked nobody reads the UDP socket. Sampling sflowtool's kernel wait
# state a few times a second measures exactly the share of time samples go unread.
NOW=$(date +%s); LEFT=$((T0 + WINDOW - NOW))
[ "$LEFT" -gt 0 ] && printf '\n(measuring for another %ss ...)\n' "$LEFT"
PROBES=0 BLOCKED=0 QMAX=0
while [ "$(date +%s)" -lt $((T0 + WINDOW)) ]; do
    if [ -n "$SPID" ] && [ -r "/proc/$SPID/wchan" ]; then
        W=$(cat "/proc/$SPID/wchan" 2>/dev/null)
        SC=$(cut -d' ' -f1,2 "/proc/$SPID/syscall" 2>/dev/null)
        PROBES=$((PROBES + 1))
        # x86_64 write(2) is syscall 1; fd 1 is sflowtool's stdout, the pipe
        case "$W $SC" in *pipe_write*|*" 1 0x1") BLOCKED=$((BLOCKED + 1)) ;; esac
    fi
    Q=$(udp_line); Q=${Q%% *}
    [ -n "$Q" ] && [ "$Q" -gt "$QMAX" ] && QMAX=$Q
    sleep 0.2
done
U1=$(udp_line); R1=$(snmp_rcvbuf); S1=$(rrdc_stat); C1=${HPID:+$(cpu_ticks "$HPID")}
T1=$(date +%s); DT=$((T1 - T0))

head_ "Loss on the collector over ${DT}s"
if [ -n "$U0" ] && [ -n "$U1" ]; then
    read -r Q0 D0 <<<"$U0"; read -r Q1 D1 <<<"$U1"
    DD=$((D1 - D0))
    if [ "$DD" -gt 0 ]; then
        fail "udp/$PORT socket dropped $DD datagrams ($((DD * 60 / DT))/min): the reader is not keeping up, those samples are lost"
    else
        ok "udp/$PORT socket dropped no datagrams (lifetime drops: $D1)"
    fi
    info "receive queue now: $Q1 bytes"
else
    fail "nothing is bound to udp/$PORT - is sflowtool listening on another port? (-p)"
fi
[ -n "$R0" ] && [ -n "$R1" ] && [ "$((R1 - R0))" -gt 0 ] && warn "system-wide UDP RcvbufErrors +$((R1 - R0))"

if [ -n "${HPID:-}" ] && [ -n "${C0:-}" ] && [ -n "${C1:-}" ]; then
    HZ=$(getconf CLK_TCK); CPU=$(( (C1 - C0) * 100 / HZ / DT ))
    if [ "$CPU" -ge 90 ]; then
        fail "handler at ${CPU}% CPU: it is single-threaded and stops reading samples while it writes RRDs"
    else
        ok "handler at ${CPU}% CPU"
    fi
fi

head_ "Is the handler reading? (sflowtool sampled $PROBES times over ${DT}s)"
if [ "$PROBES" -gt 0 ]; then
    BPCT=$((100 * BLOCKED / PROBES))
    info "sflowtool blocked writing to the handler ${BPCT}% of the time; socket receive queue peaked at $QMAX bytes"
    if [ "$BPCT" -ge 10 ]; then
        fail "for ${BPCT}% of the time nobody reads the sFlow socket: samples queue, then are dropped once it fills."
        if [ -n "$IMPROVED" ]; then
            info "the improved handler is busy even while reading - check its 'flush:' journal lines and its CPU"
        else
            info "The stock handler reads nothing while it flushes and divides what it did read by the whole interval:"
            info "expect P2P graphs to record roughly $((100 - BPCT))% of real traffic, less where the queue overflowed."
        fi
    else
        ok "the handler keeps up: sflowtool blocked only ${BPCT}% of the time"
    fi
    [ "$QMAX" -gt $((RMEM / 2)) ] && warn "the receive queue reached over half of rmem_max ($RMEM) - bursts are close to being dropped"
else
    warn "could not read sflowtool's state from /proc (run as root)"
fi
if [ -n "$S0" ] && [ -n "$S1" ] && [ -n "$(stat_val UpdatesReceived <<<"$S1")" ]; then
    UR=$(( $(stat_val UpdatesReceived <<<"$S1") - $(stat_val UpdatesReceived <<<"$S0") ))
    QL=$(stat_val QueueLength <<<"$S1")
    PERMIN=$((UR * 60 / DT))
    info "rrdcached: $PERMIN updates/min; queue length now: $QL"
fi

head_ "Freshness"
if [ -d "$BASE" ] && command -v rrdtool >/dev/null; then
    F=$(ls -1 "$BASE"/ipv4/bytes/aggregate/*.rrd 2>/dev/null | head -1)
    if [ -n "$F" ]; then
        DISK=$(rrdtool last "$F")
        MEM=$(rrdtool lastupdate --daemon "unix:$SOCK" "$F" 2>/dev/null | awk -F: 'NF>1 && $1 ~ /^[0-9]+$/ {print $1; exit}')
        AGE=$(( $(date +%s) - ${MEM:-$DISK} ))
        [ "$AGE" -gt 180 ] && fail "${F#"$BASE"/} last updated ${AGE}s ago" || ok "${F#"$BASE"/} updated ${AGE}s ago"
        [ -n "$MEM" ] && info "on disk: $(( $(date +%s) - DISK ))s behind (what IXP Manager's HTTP copy sees)"
    else
        warn "no aggregate RRD under $BASE/ipv4/bytes/aggregate"
    fi
fi
if [ -n "$EXPORT_URL" ]; then
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${EXPORT_URL%/}/ipv4/bytes/aggregate/")
    [ "$CODE" = 200 ] || [ "$CODE" = 403 ] && ok "HTTP export answers ($CODE) at $EXPORT_URL" || fail "HTTP export returned $CODE - IXP Manager cannot load any sFlow graph"
fi
if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then ok "clock NTP-synchronised"
else warn "clock not NTP-synchronised (RRD timestamps come from this host)"; fi

head_ "Journal, last 24h"
if command -v journalctl >/dev/null; then
    J=$(journalctl --since -24h -q -o cat 2>/dev/null | grep -E 'sflow|rrdcached' || true)
    for p in 'WARNING: while updating' 'mactable reload failed' 'FATAL' 'Oops, input pipe died' 'No space left'; do
        n=$(grep -c "$p" <<<"$J" || true)
        [ "$n" -gt 0 ] && warn "$n x '$p'" && grep "$p" <<<"$J" | tail -1 | cut -c1-200 | sed 's/^/          /'
    done
    RS=$(journalctl --since -24h -q -o cat -u 'sflow*' 2>/dev/null | grep -ci 'started' || true)
    [ "${RS:-0}" -gt 1 ] && warn "handler unit started $RS times in 24h"
fi

printf '\n%d FAIL, %d WARN\n' "$FAILS" "$WARNS"
[ "$FAILS" -eq 0 ]
