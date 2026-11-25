#!/bin/sh
# Publish a built site folder as a single commit on gh-pages (what the Action
# does; this is for a run by hand).  usage: tools/publish.sh [site folder]
set -eu
SITE="${1:-work/site}"
REMOTE="$(git remote get-url origin)"
test -f "$SITE/v1/manifest.json" || { echo "no feed in $SITE" >&2; exit 1; }
TMP="$(mktemp -d)"
cp -R "$SITE"/. "$TMP"/
cd "$TMP"
git init --quiet --initial-branch gh-pages
git add -A
git -c user.name="latecup-data pipeline" -c user.email="actions@users.noreply.github.com" \
  commit --quiet -m "Feed $(date -u +%Y-%m-%dT%H:%MZ)"
git push --quiet --force "$REMOTE" gh-pages
cd / && rm -rf "$TMP"
echo "published $SITE"
