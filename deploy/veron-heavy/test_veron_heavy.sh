#!/bin/bash
# Tests for veron-heavy. Usage: bash test_veron_heavy.sh [path-to-veron-heavy]. Uses a private temp dir and a fake pressure file.
W=${1:-$(cd "$(dirname "$0")" && pwd)/veron-heavy}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export VERON_HEAVY_DIR=$T/hv VERON_HEAVY_PRESSURE=$T/pressure VERON_HEAVY_LOADAVG=$T/loadavg VERON_HEAVY_POLL=1 VERON_HEAVY_MAX=2
export VERON_HEAVY_CPU_PRESSURE=$T/cpupressure VERON_HEAVY_MEMINFO=$T/meminfo
unset VERON_HEAVY_IO_MAX VERON_HEAVY_CPU_MAX VERON_HEAVY_MEM_MIN_GB VERON_HEAVY_LOAD_MAX
unset VERON_HEAVY_SLOT
pr() { printf 'some avg10=0.00 avg60=%s avg300=0.00 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=1\n' "$1" > "$T/pressure"; }
la() { printf '%s 10.00 10.00 1/100 12345\n' "$1" > "$T/loadavg"; }
cpr() { printf 'some avg10=0.00 avg60=%s avg300=0.00 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=1\n' "$1" > "$T/cpupressure"; }
mem() { printf 'MemTotal:       263000000 kB\nMemFree:         1000000 kB\nMemAvailable:   %s kB\n' "$1" > "$T/meminfo"; }
pr 0.00; la 0.50; cpr 0.00; mem 170000000
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $*"; }
chk() { if eval "$2"; then ok; else bad "$1  [$2]"; fi; }

echo "== basics"
out=$(bash "$W" -- echo "hello world" 2>&1); chk "runs and passes stdout" '[ "$out" = "hello world" ]'
bash "$W" -- bash -c 'exit 7'; chk "passes the exit code" '[ $? = 7 ]'
bash "$W" -- /no/such/cmd 2>/dev/null; chk "command not found = 127" '[ $? = 127 ]'
bash "$W" 2>/dev/null; chk "no command = 64" '[ $? = 64 ]'
out=$(printf 'abc' | bash "$W" -- cat); chk "stdin passes through" '[ "$out" = abc ]'
out=$(bash "$W" -- printf '%s|' "a b" 'c  d' ''); chk "args with spaces survive" '[ "$out" = "a b|c  d||" ]'
out=$(bash "$W" -- bash -c 'echo $VERON_HEAVY_SLOT'); chk "the job sees its slot number" '[[ "$out" =~ ^[01]$ ]]'

echo "== at most MAX holders at once (MAX=2, 5 jobs)"
rm -f "$T/cur" "$T/peak"; echo 0 > "$T/cur"; echo 0 > "$T/peak"
job() { bash "$W" -- bash -c '
  exec 9>"$0/lk"; flock 9
  c=$(( $(cat "$0/cur") + 1 )); echo $c > "$0/cur"; [ $c -gt $(cat "$0/peak") ] && echo $c > "$0/peak"
  flock -u 9; sleep 1.5; exec 9>"$0/lk"; flock 9; echo $(( $(cat "$0/cur") - 1 )) > "$0/cur"' "$T"; }
for i in 1 2 3 4 5; do job & done; wait
chk "peak concurrency is 2" '[ "$(cat $T/peak)" = 2 ]'
chk "all five ran and the slots are free" '[ "$(cat $T/cur)" = 0 ] && ! ls $T/hv/holders/slot.* >/dev/null 2>&1'

echo "== a full house: the third waits, then runs; waiting is bounded"
bash "$W" -- sleep 4 & h1=$!; bash "$W" -- sleep 4 & h2=$!; sleep 1
s=$(date +%s); out=$(VERON_HEAVY_WAIT=2 bash "$W" -- echo late 2>&1); rc=$?
chk "gives up with 75 after WAIT" '[ $rc = 75 ] && [ $(( $(date +%s) - s )) -le 6 ]'
chk "the give-up line names the holders and the reason" '[[ "$out" == *"all 2 slots busy"* && "$out" == *"cmd=sleep"* ]]'
out=$(bash "$W" -- echo got-in 2>&1); chk "a waiter gets in once a slot frees" '[[ "$out" == *got-in* ]]'
wait $h1 $h2

echo "== the IO gate"
pr 55.00
s=$(date +%s); out=$(VERON_HEAVY_WAIT=2 bash "$W" -- echo x 2>&1); rc=$?
chk "pressure above the gate: waits then 75" '[ $rc = 75 ] && [[ "$out" == *"io pressure avg60=55 >= 20"* ]]'
(sleep 2; pr 5.00) & out=$(VERON_HEAVY_WAIT=20 bash "$W" -- echo proceeded 2>&1); chk "pressure drops: it proceeds" '[[ "$out" == *proceeded ]]'
pr 19.90; out=$(bash "$W" -- echo under-gate 2>&1); chk "just under the gate (20) is allowed" '[[ "$out" == *under-gate ]]'
pr 20.00; VERON_HEAVY_WAIT=1 bash "$W" -- echo x >/dev/null 2>&1; chk "AT the gate waits (>= 20 since 11-09)" '[ $? = 75 ]'
pr 30.00; VERON_HEAVY_WAIT=1 bash "$W" -- echo x >/dev/null 2>&1; chk "30 (the old gate) waits" '[ $? = 75 ]'
pr 31.00; VERON_HEAVY_WAIT=1 bash "$W" -- echo x >/dev/null 2>&1; chk "above the gate waits" '[ $? = 75 ]'
VERON_HEAVY_WAIT=1 bash "$W" --io-max 40 -- echo y >/dev/null 2>&1; chk "--io-max raises the gate" '[ $? = 0 ]'
pr 0.00; rm -f "$T/pressure"; out=$(bash "$W" -- echo nofile 2>&1); chk "an unreadable gate is open (not a hang)" '[[ "$out" == *nofile ]]'; pr 0.00

echo "== the CPU gate (11-09: wait while cpu PSI some avg60 >= 25)"
cpr 25.00; out=$(VERON_HEAVY_WAIT=2 bash "$W" -- echo x 2>&1); rc=$?
chk "cpu PSI AT 25 waits, then 75, naming the reason" '[ $rc = 75 ] && [[ "$out" == *"cpu pressure avg60=25 >= 25"* ]]'
cpr 24.99; out=$(bash "$W" -- echo under-cpu 2>&1); chk "cpu PSI 24.99 is allowed" '[[ "$out" == *under-cpu ]]'
cpr 48.30; (sleep 2; cpr 9.00) & out=$(VERON_HEAVY_WAIT=20 bash "$W" -- echo cpu-went 2>&1); chk "cpu PSI drops: it proceeds" '[[ "$out" == *cpu-went ]]'
cpr 48.30; VERON_HEAVY_WAIT=1 bash "$W" --cpu-max 60 -- echo y >/dev/null 2>&1; chk "--cpu-max raises the gate" '[ $? = 0 ]'
VERON_HEAVY_CPU_MAX=60 VERON_HEAVY_WAIT=1 bash "$W" -- echo y >/dev/null 2>&1; chk "VERON_HEAVY_CPU_MAX raises the gate" '[ $? = 0 ]'
rm -f "$T/cpupressure"; out=$(bash "$W" -- echo nofile 2>&1); chk "an unreadable cpu pressure file is open" '[[ "$out" == *nofile ]]'
printf 'garbage\n' > "$T/cpupressure"; out=$(bash "$W" -- echo garbled 2>&1); chk "a garbled cpu pressure file is open (no bash error)" '[ "$out" = garbled ]'; cpr 0.00
la 47.00; cpr 10.00; out=$(bash "$W" -- echo pinned-case 2>&1); chk "high load1 under the backstop with low cpu PSI is allowed" '[[ "$out" == *pinned-case ]]'; la 0.50; cpr 0.00

echo "== the MEMORY gate (11-09: wait while MemAvailable < 48 GiB)"
mem 40000000; out=$(VERON_HEAVY_WAIT=2 bash "$W" -- echo x 2>&1); rc=$?
chk "MemAvailable 38 GiB waits, then 75, naming the reason" '[ $rc = 75 ] && [[ "$out" == *"MemAvailable=38GiB < 48GiB"* ]]'
mem 50331648; out=$(bash "$W" -- echo at-mem 2>&1); chk "MemAvailable exactly 48 GiB (50331648 kB) is allowed" '[[ "$out" == *at-mem ]]'
mem 50331647; VERON_HEAVY_WAIT=1 bash "$W" -- echo x >/dev/null 2>&1; chk "1 kB under 48 GiB waits" '[ $? = 75 ]'
mem 40000000; VERON_HEAVY_WAIT=1 bash "$W" --mem-min-gb 32 -- echo y >/dev/null 2>&1; chk "--mem-min-gb lowers the floor" '[ $? = 0 ]'
mem 40000000; (sleep 2; mem 170000000) & out=$(VERON_HEAVY_WAIT=20 bash "$W" -- echo mem-went 2>&1); chk "memory frees: it proceeds" '[[ "$out" == *mem-went ]]'
rm -f "$T/meminfo"; out=$(bash "$W" -- echo nofile 2>&1); chk "an unreadable meminfo is open" '[[ "$out" == *nofile ]]'
printf 'MemTotal: 1 kB\n' > "$T/meminfo"; out=$(bash "$W" -- echo nomemavail 2>&1); chk "meminfo without MemAvailable is open" '[ "$out" = nomemavail ]'; mem 170000000
st=$(bash "$W" --status 2>&1); chk "--status shows cpu pressure and MemAvailable with their gates" '[[ "$st" == *"cpu pressure some avg60=0 (gate 25)"* && "$st" == *"MemAvailable=162 GiB (gate 48)"* ]]'

echo "== a gate value that is not a whole number is refused (64), never an open gate"
out=$(bash "$W" --cpu-max abc -- echo ran 2>&1); rc=$?; chk "--cpu-max abc: 64, the job does not run" '[ $rc = 64 ] && [[ "$out" != *ran* && "$out" == *"CPU_MAX gate"* ]]'
bash "$W" --mem-min-gb x -- true >/dev/null 2>&1; chk "--mem-min-gb x: 64" '[ $? = 64 ]'
bash "$W" --io-max 2.5 -- true >/dev/null 2>&1; chk "--io-max 2.5: 64" '[ $? = 64 ]'
VERON_HEAVY_LOAD_MAX=lots bash "$W" -- true >/dev/null 2>&1; chk "VERON_HEAVY_LOAD_MAX=lots: 64" '[ $? = 64 ]'

echo "== the LOAD gate (Boss 11-05: wait, do not fail, while load1 >= 48; a backstop since 11-09)"
la 48.00; out=$(VERON_HEAVY_WAIT=2 bash "$W" -- echo x 2>&1); rc=$?
chk "load1 AT 48 waits, then 75, naming the reason" '[ $rc = 75 ] && [[ "$out" == *"load1=48 >= 48"* ]]'
la 47.99; out=$(bash "$W" -- echo under-load 2>&1); chk "load1 47.99 is allowed" '[[ "$out" == *under-load ]]'
la 120.50; (sleep 2; la 5.00) & out=$(VERON_HEAVY_WAIT=20 bash "$W" -- echo went 2>&1); chk "load drops: it proceeds (waited, did not fail)" '[[ "$out" == *went ]]'
la 120.50; VERON_HEAVY_WAIT=1 bash "$W" --load-max 200 -- echo y >/dev/null 2>&1; chk "--load-max raises the gate" '[ $? = 0 ]'
rm -f "$T/loadavg"; out=$(bash "$W" -- echo nofile 2>&1); chk "an unreadable load file is open (not a hang)" '[[ "$out" == *nofile ]]'; la 0.50
la 90.00; out=$(VERON_HEAVY_WAIT=3 bash "$W" -- true 2>&1); n=$(grep -c '^veron-heavy: waiting:' <<<"$out")
chk "one waiting line a minute: 3 s of waiting prints ONE" '[ "$n" = 1 ]'
out=$(VERON_HEAVY_SAY_EVERY=1 VERON_HEAVY_WAIT=4 bash "$W" -- true 2>&1); n=$(grep -c '^veron-heavy: waiting:' <<<"$out")
chk "the line repeats at the configured interval (SAY_EVERY=1, 4 s: at least 3)" '[ "$n" -ge 3 ]'; la 0.50
st=$(bash "$W" --status 2>&1); chk "--status shows load1 and its gate" '[[ "$st" == *"load1=0 (gate 48)"* ]]'

echo "== the job runs niced, ionice-d and with capped workers"
base=$(nice); out=$(bash "$W" -- nice); chk "nice -n 10 on top of the caller's" '[ "$out" = "$((base + 10))" ]'
out=$(bash "$W" -- ionice -p $$ 2>&1 | head -1); out=$(bash "$W" -- bash -c 'ionice -p $$' 2>&1); chk "ionice best-effort class, priority 7" '[[ "$out" == *best-effort* && "$out" == *"prio 7"* ]]'
out=$(bash "$W" -- bash -c 'echo $JEST_MAX_WORKERS $PYTEST_XDIST_AUTO_NUM_WORKERS $PYTEST_XDIST_WORKERS $MAKEFLAGS'); chk "worker caps are exported to the job (2)" '[ "$out" = "2 2 2 -j2" ]'
out=$(VERON_HEAVY_WORKERS=3 JEST_MAX_WORKERS=16 MAKEFLAGS=-j64 bash "$W" -- bash -c 'echo $JEST_MAX_WORKERS $MAKEFLAGS'); chk "a lane's own bigger numbers are overridden; VERON_HEAVY_WORKERS sets the cap" '[ "$out" = "3 -j3" ]'
bash "$W" -- bash -c 'exit 7'; chk "the exit code still passes through the wrapper chain" '[ $? = 7 ]'
s=$(date +%s); bash "$W" --max-run 2 -- sleep 30; rc=$?; chk "--max-run still stops a niced job (124)" '[ $rc = 124 ] && [ $(( $(date +%s) - s )) -le 8 ]'
out=$(printf 'abc' | bash "$W" -- cat); chk "stdin still passes through" '[ "$out" = abc ]'

echo "== holder timeout and release"
s=$(date +%s); bash "$W" --max-run 2 -- sleep 30 2>"$T/err"; rc=$?
chk "a holder that runs too long is stopped (124) and the slot freed" '[ $rc = 124 ] && [ $(( $(date +%s) - s )) -le 8 ] && grep -q "longer than 2s" "$T/err" && ! ls $T/hv/holders/slot.* >/dev/null 2>&1'
# SIGKILL the wrapper: its slot frees at once (the job it started may run on; its PID is recorded so the test can stop it)
bash "$W" -- bash -c 'echo $$ > "$0/j1.pid"; exec sleep 30' "$T" & h1=$!
bash "$W" -- bash -c 'echo $$ > "$0/j2.pid"; exec sleep 30' "$T" & h2=$!; sleep 1.5
VERON_HEAVY_WAIT=1 bash "$W" -- true >/dev/null 2>&1; chk "two live holders fill MAX=2" '[ $? = 75 ]'
kill -9 $h1 2>/dev/null; wait $h1 2>/dev/null; sleep 1
VERON_HEAVY_WAIT=2 bash "$W" -- true >/dev/null 2>&1; chk "a SIGKILLed wrapper frees its slot at once" '[ $? = 0 ]'
kill "$(cat "$T/j1.pid")" 2>/dev/null; kill "$(cat "$T/j2.pid")" 2>/dev/null; wait $h2 2>/dev/null; sleep 1
echo "== a job's stray child does not keep the slot"
bash "$W" -- bash -c 'sleep 25 & echo $! > "$0/stray.pid"; disown; exit 0' "$T"; rc=$?
VERON_HEAVY_WAIT=1 bash "$W" -- true >/dev/null 2>&1; r2=$?
VERON_HEAVY_WAIT=1 bash "$W" -- true >/dev/null 2>&1; r3=$?
chk "a leftover background child does not hold a slot (two more jobs fit)" '[ $rc = 0 ] && [ $r2 = 0 ] && [ $r3 = 0 ]'
kill "$(cat "$T/stray.pid")" 2>/dev/null

echo "== nested, status, privacy"
out=$(VERON_HEAVY_MAX=1 bash "$W" -- bash "$W" -- echo inner 2>&1); chk "nested call does not deadlock (MAX=1)" '[[ "$out" == *inner ]]'
bash "$W" --lane lane-x -- sleep 3 & h1=$!; sleep 1
st=$(bash "$W" --status 2>&1)
chk "--status shows the holder, slots and pressure" '[[ "$st" == *"slots in use: 1 of 2"* && "$st" == *"lane=lane-x"* && "$st" == *"cmd=sleep"* && "$st" == *"avg60="* ]]'
pr 55.00; (VERON_HEAVY_WAIT=4 bash "$W" --lane waiter -- true >/dev/null 2>&1 &) ; sleep 2
chk "--status counts a waiter (held back by the IO gate)" 'bash "$W" --status 2>&1 | grep -q "^waiting: 1"'
sleep 3; pr 0.00
wait $h1 $h2
bash "$W" -- bash -c 'sleep 2; echo SECRETARG' >/dev/null 2>&1 & sleep 1
bash "$W" -- bash -c 'sleep 2' "tokenvalue-12345" 2>/dev/null & sleep 1
chk "the holder record has the command name, never its arguments" '! grep -rq "tokenvalue-12345\|SECRETARG" "$T/hv"'
wait
chk "no holder files are left behind" '! ls $T/hv/holders/slot.* >/dev/null 2>&1'
echo "passed $pass, failed $fail"
[ $fail = 0 ]
