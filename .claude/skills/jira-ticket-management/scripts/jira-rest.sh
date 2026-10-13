#!/usr/bin/env bash
# Minimal Jira Cloud REST helper for operations the Atlassian MCP tools do not cover
# (delete, sprints/boards, attachments, remote links, field search, changelogs, bulk create).
#
# Credentials come from the environment and are never printed or passed on the command line:
#   JIRA_EMAIL      Atlassian account email
#   JIRA_API_TOKEN  API token from https://id.atlassian.com/manage-profile/security/api-tokens
#   JIRA_BASE_URL   optional, defaults to https://nguyenchiemhao2205.atlassian.net
#
# Usage:
#   jira-rest.sh check                                  # verify credentials (prints display name)
#   jira-rest.sh GET    <path>                          # e.g. /rest/agile/1.0/board?projectKeyOrId=EA
#   jira-rest.sh POST   <path> '<json>' | @<file.json>
#   jira-rest.sh PUT    <path> '<json>' | @<file.json>
#   jira-rest.sh DELETE <path>
#   jira-rest.sh upload <ISSUE-KEY> <file>              # add an attachment
#
# Response body goes to stdout; "HTTP <code>" goes to stderr; exit code 1 on non-2xx.

set -euo pipefail

BASE_URL="${JIRA_BASE_URL:-https://nguyenchiemhao2205.atlassian.net}"

die() { echo "jira-rest: $*" >&2; exit 2; }

[[ -n "${JIRA_EMAIL:-}" && -n "${JIRA_API_TOKEN:-}" ]] || die "JIRA_EMAIL and JIRA_API_TOKEN must be set (see references/jira-operations.md#setup)"
[[ $# -ge 1 ]] || die "missing command"

# Feed the credentials to curl through a config on stdin so they never appear in argv or logs.
curl_auth() {
  printf 'user = "%s:%s"\n' "$JIRA_EMAIL" "$JIRA_API_TOKEN" | curl -K - "$@"
}

run() {
  local out code
  out="$(mktemp)"
  code="$(curl_auth -sS -o "$out" -w '%{http_code}' "$@")" || { rm -f "$out"; die "curl failed"; }
  cat "$out"; echo
  rm -f "$out"
  echo "HTTP $code" >&2
  [[ "$code" =~ ^2 ]] || exit 1
}

cmd="$1"; shift
case "$cmd" in
  check)
    run -H 'Accept: application/json' "$BASE_URL/rest/api/3/myself" \
      | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const j=JSON.parse(s);console.log("OK:",j.displayName,"<"+j.emailAddress+">")})'
    ;;
  GET|DELETE)
    [[ $# -ge 1 ]] || die "$cmd needs a path"
    run -X "$cmd" -H 'Accept: application/json' "$BASE_URL$1"
    ;;
  POST|PUT)
    [[ $# -ge 1 ]] || die "$cmd needs a path"
    path="$1"; body="${2:-}"
    [[ -n "$body" ]] || body='{}'
    run -X "$cmd" -H 'Accept: application/json' -H 'Content-Type: application/json' \
      --data-binary "$body" "$BASE_URL$path"
    ;;
  upload)
    [[ $# -eq 2 ]] || die "upload needs <ISSUE-KEY> <file>"
    [[ -f "$2" ]] || die "file not found: $2"
    run -X POST -H 'Accept: application/json' -H 'X-Atlassian-Token: no-check' \
      -F "file=@$2" "$BASE_URL/rest/api/3/issue/$1/attachments"
    ;;
  *)
    die "unknown command: $cmd"
    ;;
esac
