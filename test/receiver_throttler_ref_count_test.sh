#! /bin/bash

_bin/wdt/wdt -skip_writes -avg_mbytes_per_sec=10 -max_accept_retries=10
STATUS=$?
if [ $STATUS -ne 3 ]; then
  echo "Receiver should exit with status 3, but it exited with $STATUS"
  exit $STATUS
fi
echo "Test passed"
