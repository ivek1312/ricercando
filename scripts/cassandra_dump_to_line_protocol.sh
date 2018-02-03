#!/bin/bash
set -e

python3 -c 'import ricercando.db' >/dev/null 2>&1 || {
    echo 'ERROR: Install python package first. pip install ricercando'
    exit 1
}
command -v csvtool >/dev/null || {
    echo 'ERROR: sudo apt install csvtool'
    exit 1
}
[ "$INFLUXDB_ADMIN_PASSWORD" ] || {
    echo 'ERROR: Create admin user on InfluxDB and provide password in INFLUXDB_ADMIN_PASSWORD env variable.'
    exit 1
}

# Create users. If user/pass details match, the actions are idempotent
echo "Creating users."
influx -username admin -password "$INFLUXDB_ADMIN_PASSWORD" \
    -execute "CREATE USER admin WITH PASSWORD '$INFLUXDB_ADMIN_PASSWORD' WITH ALL PRIVILEGES;
              CREATE USER monroe WITH PASSWORD 'secure';
              GRANT READ ON monroe TO monroe;"

scripts="$(readlink -f "$(dirname "$0")")"
recipes="$scripts/recipes"
tables="$(ls "$recipes")"

# Convert archived CSV dumps from ./ into InfluxDB line protocol files (in ./).
# Many uncompressed files of 100k lines are created.
# FIXME: ensure enough disk space
echo 'Converting dumps ...'

for table in $tables; do
    { read columns;
      read -r tags fields; } < "$recipes/$table"

    echo "    $table" >&2

    # For each file of "table" type, in date-ascending order
    for file in $(ls -v *"$table"*.csv.txz); do
        [ ! -f "$file" ] && continue

        echo "        $file" >&2

        tar xJOf "$file" |
            csvtool -u TAB namedcol "$columns" - |
            tail -n +2 |
            sed -E 's/\b(None|null)\b//g'
    done |
        "$scripts/tsv_to_line_protocol.py" "${table}_10ms" "$tags" "$fields"
done |
    split -a 5 -d -l 100000 - "influxdb_lines_"


# Import line files into DB
#
# Several jobs simultaneously to liken threads. influx CLI tool imports
# some 1000 points per second, so if we spawn multiple invocations of it,
# we can speed up the importation considerably.
# Any import errors are written, along with context lines, into ./notice.
echo
echo 'Importing data into database ...'

N_JOBS=10

# Print DB import errors after completion
trap '[ -f notice ] && grep error notice && echo -e "\nSee ./notice for import stats & errors"' EXIT

for file in ./influxdb_lines_*; do
    [ ! -f "$file" ] && continue
    echo "$file"
    { echo "$file"
      influx -import -precision ms -username admin -password "$INFLUXDB_ADMIN_PASSWORD" -path <(
          echo '#DDL
CREATE DATABASE monroe
# DML
# CONTEXT-DATABASE: monroe';
          cat "$file";) >> notice 2>&1 && rm "$file" || true; } &

    if [ $(jobs -lr | wc -l) -ge $N_JOBS ]; then
        wait -n
    fi
done

wait


_first_time() {
    influx -precision rfc3339 -database monroe \
        -username admin -password "$INFLUXDB_ADMIN_PASSWORD" \
        -format csv -execute "SELECT * FROM ${1}_10ms ORDER BY time $2 LIMIT 1" |
        csvtool namedcol time - |
        tail -n +2
}

# Make distinct level-of-detail tables for faster retrieval
echo 'Making LOD tables ...'
for table in $tables; do
    agg_columns="$(python3 -c "from ricercando.db import $table; print($table._select_agg())")"
    start_time="$(_first_time "$table" ASC)"
    end_time="$(_first_time "$table" DESC)"
    for time_bin in '1s' '1m' '30m'; do
        echo "        $time_bin  $(
            influx -database monroe -username admin -password "$INFLUXDB_ADMIN_PASSWORD" -format csv \
                -execute "SELECT $agg_columns \
                          INTO ${table}_${time_bin} \
                          FROM ${table}_10ms \
                          WHERE time >= '$start_time' \
                          AND time <= '$end_time' \
                          GROUP BY time($time_bin),*" |
            csvtool namedcol written - | tail -n +2)"
    done
done

wait
echo "All done."
