# First Blood → Telegram (CTFd 3.8.0)

This repository contains a minimal **CTFd 3.8.0** plugin that announces **First Blood** solves to a Telegram chat.

Key goals:

- **Drop-in plugin**: copy a folder into `CTFd/plugins/`.
- **No HTML or templates**: configuration is done entirely via an admin JSON API.
- **CTFd config storage**: uses `get_config/set_config` to persist settings.
- **Accurate First Blood semantics**: first visible, non-banned solve per challenge.
- **Telegram delivery**: sends a message via `sendMessage` using only stdlib (no extra deps).

---

## 1. Plugin Layout

Copy the plugin directory into your CTFd instance:

```
CTFd/plugins/first_blood_telegram/
├── __init__.py
└── config.json
```

`config.json` tells CTFd to expose the admin route in the Plugins UI:

```json
{
  "name": "First Blood Telegram",
  "route": "/admin/first_blood_telegram"
}
```

---

## 2. Install

1. Copy the plugin into `CTFd/plugins/`:

   ```bash
   cp -R first_blood_telegram /path/to/CTFd/plugins/
   ```

2. Restart CTFd.
3. Log in as an admin and open the plugin settings:

   - `GET https://<ctfd>/admin/first_blood_telegram/`

You will see a JSON response with the current settings and placeholders.

---

## 3. Configuration API (JSON only)

### 3.1 GET settings

`GET /admin/first_blood_telegram/`

Returns:

- `settings.enabled`: whether the plugin is enabled.
- `settings.token_masked`: masked bot token (never returns full token).
- `settings.token_is_set`: boolean, whether token is present.
- `settings.chat_id`: target Telegram chat.
- `settings.template`: message template.
- `settings.parse_mode`: `""`, `"HTML"`, or `"MarkdownV2"`.
- `placeholders`: list of supported template variables.
- `how_to_update`: example of a POST body.

### 3.2 POST settings

`POST /admin/first_blood_telegram/`

**Body (JSON)** — only fields present will be updated:

```json
{
  "enabled": true,
  "token": "123456:ABCDEF...",
  "chat_id": "-1001234567890",
  "template": "🏁 FB! {solver} первым закрыл «{challenge}».",
  "parse_mode": ""
}
```

### 3.3 POST test message

`POST /admin/first_blood_telegram/test`

Sends a test message to the configured `chat_id` using the current `token`.

---

## 4. Telegram Setup

1. Create a bot with `@BotFather` and copy the token.
2. Add the bot to your target chat or channel.
3. Get the `chat_id`:
   - For channels/groups, you can use `@userinfobot` or inspect the `getUpdates` output.
   - For supergroups, IDs often look like `-1001234567890`.

---

## 5. Template Placeholders

You can customize the message with placeholders:

- `{solver}`: account name (user or team)
- `{solver_type}`: `user` or `team`
- `{challenge}`: challenge name
- `{category}`: challenge category
- `{points}`: challenge point value
- `{solve_id}`: solve row id
- `{challenge_id}`: challenge id
- `{date_utc}`: current UTC timestamp (`YYYY-MM-DD HH:MM:SS`)

Example template:

```
🩸 FIRST BLOOD! {solver} solved {challenge} ({points} pts)
```

**Note:** This is a simple string-replace renderer. It does not escape Markdown/HTML. If you use `parse_mode`, make sure your template is valid for that mode.

---

## 6. First Blood Semantics

The plugin considers a solve a First Blood if **it is the earliest solve for the challenge** among **non-hidden** and **non-banned** accounts. This matches CTFd’s First Blood logic used in webhooks.

Implementation details:

- The plugin collects new `Solves` during `after_flush`.
- It announces only after a successful `after_commit`.
- It queries for the earliest solve (by solve date, then id) where the account is visible and not banned.

---

## 7. Example Usage (curl)

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -b cookies.txt -c cookies.txt \
  https://<ctfd>/admin/first_blood_telegram/ \
  -d '{"enabled":true,"token":"123456:ABCDEF","chat_id":"-1001234567890","template":"🏁 FB! {solver} первым закрыл «{challenge}».","parse_mode":""}'
```

Test message:

```bash
curl -sS -X POST \
  -b cookies.txt -c cookies.txt \
  https://<ctfd>/admin/first_blood_telegram/test
```

---

## 8. Configuration Keys (CTFd config)

The plugin stores settings with these keys:

- `FB_TG_ENABLED` (`"1"` or `"0"`)
- `FB_TG_TOKEN`
- `FB_TG_CHAT_ID`
- `FB_TG_TEMPLATE`
- `FB_TG_PARSE_MODE`

---

## 9. Troubleshooting

- **No messages sent:**
  - Ensure `enabled` is `true`.
  - Verify `token` and `chat_id`.
  - Check Telegram bot permissions in the target chat.
- **Message formatting issues:**
  - If using `parse_mode`, your template must match the syntax (e.g., `MarkdownV2`).
  - Try `parse_mode: ""` to disable formatting.
- **No First Blood detected:**
  - Only visible, non-banned accounts count.
  - If a hidden or banned account solved first, the plugin will wait until a valid account becomes the earliest visible solve.

---

## 10. Files in This Repo

```
CTFd/plugins/first_blood_telegram/config.json
CTFd/plugins/first_blood_telegram/__init__.py
README.md
```

---

## 11. Compatibility

- **Tested for:** CTFd 3.8.0
- **Dependencies:** None beyond CTFd + Python stdlib

---

## 12. Security Notes

- The token is never returned in full via the settings API.
- Admin-only endpoints (protected with `@admins_only`).
- CSRF is bypassed for JSON endpoints via `@bypass_csrf_protection`.
