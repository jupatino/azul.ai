#!/usr/bin/env bash
# Keep ONE Slack message per pull request up to date, with a thread of history.
#
# Usage: slack-pr-status.sh <state>
#   state: running | passed | failed | cancelled | merged | merge_failed
#
# The first call for a PR posts the message and records its Slack timestamp in a
# PR comment (<!-- azul-slack-message ts=... -->). Later calls edit that message
# and add a thread reply. Mentions go in thread replies, because Slack does not
# notify for mentions added by editing a message.
#
# Env (required): SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, GH_TOKEN, plus the standard
#   GITHUB_* variables of a pull_request event.
# Env (optional): TEST_DURATION (s), COVERAGE (e.g. 91%), FAILING (comma list),
#   FAILING_COUNT, SLACK_MENTION_USER_ID (Slack member ID to ping on failures).
set -euo pipefail

state="${1:?state required}"

if [[ -z "${SLACK_BOT_TOKEN:-}" || -z "${SLACK_CHANNEL_ID:-}" ]]; then
  echo "::warning::SLACK_BOT_TOKEN / SLACK_CHANNEL_ID not available; skipping Slack update."
  exit 0
fi

repo="$GITHUB_REPOSITORY"
ev() { jq -r "$1" "$GITHUB_EVENT_PATH"; }
number="$(ev .pull_request.number)"
title="$(ev .pull_request.title)"
pr_url="$(ev .pull_request.html_url)"
author="$(ev .pull_request.user.login)"
files="$(ev '.pull_request.changed_files // 0')"
adds="$(ev '.pull_request.additions // 0')"
dels="$(ev '.pull_request.deletions // 0')"
short_sha="$(ev .pull_request.head.sha | cut -c1-7)"
run_url="${GITHUB_SERVER_URL}/${repo}/actions/runs/${GITHUB_RUN_ID}"
icon_base="https://raw.githubusercontent.com/${repo}/main/assets/slack"
mention=""
[[ -n "${SLACK_MENTION_USER_ID:-}" ]] && mention="<@${SLACK_MENTION_USER_ID}> "

esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

# --- state -> what the message shows ----------------------------------------
ok=":white_check_mark:"; bad=":x:"; todo=":white_circle:"; busy=":hourglass_flowing_sand:"
case "$state" in
  running)      label="Tests running";     icon="tests-started.png";   s_tests="$busy Tests running"; s_merge="$todo Merge" ;;
  passed)       label="Tests passed";      icon="tests-passed.png";    s_tests="$ok Tests passed";    s_merge="$todo Merge" ;;
  failed)       label="Tests failed";      icon="tests-failed.png";    s_tests="$bad Tests failed";   s_merge="$todo Merge" ;;
  cancelled)    label="Tests cancelled";   icon="tests-cancelled.png"; s_tests="$todo Tests";         s_merge="$todo Merge" ;;
  merged)       label="Merged";            icon="pr-merged-v2.png";    s_tests="$ok Tests passed";    s_merge="$ok Merged" ;;
  merge_failed) label="Auto-merge failed"; icon="tests-failed.png";    s_tests="$ok Tests passed";    s_merge="$bad Merge failed" ;;
  *) echo "::error::unknown state: $state"; exit 1 ;;
esac
steps="$ok Opened    ${s_tests}    ${s_merge}"

meta="$(printf '%s' "$author" | esc) · ${files} files · +${adds} −${dels}"
if [[ "$state" != "running" && -n "${TEST_DURATION:-}" ]]; then meta+=" · tests ${TEST_DURATION}s"; fi
if [[ "$state" == "passed" || "$state" == "merged" ]] && [[ -n "${COVERAGE:-}" ]]; then meta+=" · coverage ${COVERAGE}"; fi

failing_line=""
if [[ "$state" == "failed" && -n "${FAILING:-}" ]]; then
  failing_line="${FAILING_COUNT:-}${FAILING_COUNT:+ failing: }$(printf '%s' "$FAILING" | esc)"
fi

run_label="View run"; [[ "$state" == "failed" || "$state" == "merge_failed" ]] && run_label="View failed run"

# --- thread reply for this step ---------------------------------------------
case "$state" in
  running)      reply="Tests started on \`${short_sha}\`" ;;
  passed)       reply="Tests passed${TEST_DURATION:+ in ${TEST_DURATION}s}${COVERAGE:+ · coverage ${COVERAGE}}" ;;
  failed)       reply="${mention}Tests failed on \`${short_sha}\`${failing_line:+ — ${failing_line}} · <${run_url}|logs>" ;;
  cancelled)    reply="Test run for \`${short_sha}\` cancelled (superseded by a newer push)" ;;
  merged)       reply="Merged into main" ;;
  merge_failed) reply="${mention}Auto-merge failed · <${run_url}|logs>" ;;
esac

# --- Slack + GitHub helpers -------------------------------------------------
slack() { # slack <method> <json>
  local resp
  resp="$(curl --fail --silent --show-error --max-time 20 --retry 3 \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -H "Content-Type: application/json; charset=utf-8" \
    --data "$2" "https://slack.com/api/$1")"
  if ! jq -e '.ok == true' <<<"$resp" >/dev/null; then
    echo "::error::Slack $1 failed for PR #${number}: $(jq -r '.error // "unknown_error"' <<<"$resp")"
    return 1
  fi
  printf '%s' "$resp"
}

find_ts() {
  gh api "repos/${repo}/issues/${number}/comments" --paginate \
    --jq '.[] | select(.user.login == "github-actions[bot]") | .body' \
    | sed -n 's/.*<!-- azul-slack-message ts=\([0-9.]*\) -->.*/\1/p' | tail -n 1
}

message_json() { # message_json [ts]
  jq -n \
    --arg channel "$SLACK_CHANNEL_ID" --arg ts "${1:-}" \
    --arg label "$label" --arg icon "${icon_base}/${icon}" \
    --arg number "$number" --arg title "$title" --arg pr_url "$pr_url" \
    --arg meta "$meta" --arg steps "$steps" --arg failing "$failing_line" \
    --arg run_url "$run_url" --arg run_label "$run_label" \
    'def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
     ($title | esc) as $t |
     {
       channel: $channel,
       unfurl_links: false,
       text: ($label + ": PR #" + $number + ": " + $t),
       blocks: ([
         {type: "context", elements: [
           {type: "image", image_url: $icon, alt_text: $label},
           {type: "mrkdwn", text: ("*" + $label + "*")}]},
         {type: "section", text: {type: "mrkdwn", text: ("<" + $pr_url + "|PR #" + $number + ": " + $t + ">")}},
         {type: "context", elements: [{type: "mrkdwn", text: $meta}]},
         {type: "context", elements: [{type: "mrkdwn", text: $steps}]}
       ]
       + (if $failing == "" then [] else
           [{type: "context", elements: [{type: "mrkdwn", text: ("`" + $failing + "`")}]}] end)
       + [{type: "actions", elements: [
           {type: "button", action_id: "view_pr", text: {type: "plain_text", text: "View PR"}, url: $pr_url},
           {type: "button", action_id: "view_run", text: {type: "plain_text", text: $run_label}, url: $run_url}]}])
     } + (if $ts == "" then {} else {ts: $ts} end)'
}

# --- main ------------------------------------------------------------------
ts="$(find_ts || true)"

if [[ -z "$ts" ]]; then
  ts="$(slack chat.postMessage "$(message_json)" | jq -r '.ts')"
  gh api "repos/${repo}/issues/${number}/comments" \
    -f body="Slack status for this PR is kept up to date in the azul.ai channel. <!-- azul-slack-message ts=${ts} -->" \
    >/dev/null || echo "::warning::Could not record the Slack message for PR #${number}; the next step will post a new one."
elif [[ "$state" != "cancelled" ]]; then
  # A cancelled run was superseded by a newer one: leave the message alone so
  # it can't overwrite the newer run's status; just log it in the thread.
  slack chat.update "$(message_json "$ts")" >/dev/null
fi

slack chat.postMessage "$(jq -n --arg channel "$SLACK_CHANNEL_ID" --arg ts "$ts" --arg text "$reply" \
  '{channel: $channel, thread_ts: $ts, text: $text, unfurl_links: false}')" >/dev/null

echo "Slack: PR #${number} -> ${label}"
