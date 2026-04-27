#!/usr/bin/env bash
# mqtt-fake-emitter.sh — emit fake MQTT-style JSON lines to stdout

set -euo pipefail

# Trap Ctrl-C for a clean exit
trap 'echo; echo "Stopped." >&2; exit 0' INT

legs=(L1 L2)
metrics=(voltage amperage wattage power error)

# Float random helper using awk (bash $RANDOM is integer-only)
rand_float() {
    local min=$1 max=$2
    awk -v min="$min" -v max="$max" -v seed="$RANDOM$$" \
        'BEGIN { srand(seed); printf "%.2f", min + rand() * (max - min) }'
}

rand_int() {
    local min=$1 max=$2
    awk -v min="$min" -v max="$max" -v seed="$RANDOM$$" \
        'BEGIN { srand(seed); printf "%d", min + int(rand() * (max - min + 1)) }'
}

while true; do
    leg=${legs[RANDOM % ${#legs[@]}]}
    metric=${metrics[RANDOM % ${#metrics[@]}]}
    topic="powerdog/${leg}/${metric}"

    case "$metric" in
        voltage)
            value=$(rand_float 99.0 130.0)
            ;;
        amperage)
            value=$(rand_float 1.0 30.0)
            ;;
        wattage)
            v=$(rand_float 99.0 130.0)
            a=$(rand_float 1.0 30.0)
            value=$(awk -v v="$v" -v a="$a" 'BEGIN { printf "%.2f", v * a }')
            ;;
        power)
            value=$(rand_int 3000 10000)
            ;;
        error)
            value=$(rand_int 0 3)
            ;;
    esac

    printf '{ "topic":"%s","value":"%s"}\n' "$topic" "$value"
    sleep 1
done
