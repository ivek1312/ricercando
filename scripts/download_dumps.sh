#!/bin/bash

month="$1"
shift

if [[ "$month" =~ ^201[0-9]-[0-3][0-9] ]]; then :
else
    echo "Usage: $0 YYYY-MM [additional-wget-args]"
    exit 1
fi

wget -r -np \
    --accept-regex='exp_ping|device_gps|device_modem|node_event|nettest|udp_complete|tcp_complete|node_sensor' \
    --regex-type=pcre \
    --certificate=crt.pem --private-key=key.pem \
    "$@" \
    https://www.monroe-system.eu/user/dailyDumps/$month/

