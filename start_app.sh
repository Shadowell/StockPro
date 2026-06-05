#!/bin/bash

cd "$(dirname "$0")"

./restart.sh

if command -v open >/dev/null 2>&1; then
    open http://localhost:4444
fi

echo "Application is running on http://localhost:4444"
echo "Stop services with ./stop.sh"
