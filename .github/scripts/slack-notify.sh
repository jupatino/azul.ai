#!/usr/bin/env bash
# Post a PR status message to Slack as the azul.ai bot.
#
# Usage: slack-notify.sh "<status label>" "<icon file in assets/slack, or empty>"
# Env:   SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, PR_NUMBER, PR_TITLE, PR_URL
#        GITHUB_REPOSITORY (set by Actions)
set -euo pipefail

status_label="${1:?status label required}"
icon_file="${2:-}"

if [[ -z "${SLACK_BOT_TOKEN:-}" || -z "${SLACK_CHANNEL_ID:-}" ]]; then
  echo "::warning::SLACK_BOT_TOKEN / SLACK_CHANNEL_ID not available; skipping Slack notification."
  exit 0
fi

icon_url=""
if [[ -n "$icon_file" ]]; then
  icon_url="https://raw.githubusercontent.com/${GITHUB_REPOSITORY}/main/assets/slack/${icon_file}"
fi

# Escape Slack mrkdwn control characters so PR titles / logins can't inject
# <!channel> pings or fake links.
payload="$(jq -n \
  --arg channel "$SLACK_CHANNEL_ID" \
  --arg status "$status_label" \
  --arg icon_url "$icon_url" \
  --arg number "${PR_NUMBER:-}" \
  --arg title "${PR_TITLE:-}" \
  --arg url "${PR_URL:-}" \
  'def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
   ($title | esc) as $t |
   {
     channel: $channel,
     unfurl_links: false,
     text: ($status + ": PR #" + $number + ": " + $t),
     blocks: [
       {type: "context", elements:
         ((if $icon_url == "" then [] else [{type: "image", image_url: $icon_url, alt_text: $status}] end)
          + [{type: "mrkdwn", text: ("*" + $status + "*")}])},
       {type: "section", text: {type: "mrkdwn", text: ("<" + $url + "|PR #" + $number + ": " + $t + ">")}}
     ]
   }')"

response="$(curl --fail --silent --show-error --max-time 20 \
  -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data "$payload" \
  https://slack.com/api/chat.postMessage)"

if ! jq -e '.ok == true' <<<"$response" >/dev/null; then
  echo "::error::Slack rejected '${status_label}' for PR #${PR_NUMBER:-?}: $(jq -r '.error // "unknown_error"' <<<"$response")"
  exit 1
fi
echo "Posted '${status_label}' for PR #${PR_NUMBER:-?} to Slack."
