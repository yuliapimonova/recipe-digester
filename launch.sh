#!/bin/zsh -l
# Start the server if it isn't already running, then open the app in the browser.
# A login shell (-l) so the `claude` CLI is on PATH when launched from the Dock.
cd "$(dirname "$0")"
URL=http://127.0.0.1:5002
if ! curl -s -o /dev/null "$URL"; then
  nohup .venv/bin/python app.py > server.log 2>&1 &
  for i in {1..40}; do
    curl -s -o /dev/null "$URL" && break
    sleep 0.25
  done
fi
open "$URL"
