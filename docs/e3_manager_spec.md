# E3 Manager Spec (LINE Bot)

## Scope

Build E3 as a first-class feature with:
1. First-time user login + account binding
2. Auto fetch reminders at 09:00 and 21:00 by default
3. Per-user settings for reminder schedule and reminder types

## Data Model (SQLite)

### Table: `users`

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  line_user_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### Table: `e3_accounts`

```sql
CREATE TABLE e3_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  e3_account TEXT NOT NULL,
  encrypted_password TEXT,
  encrypted_cookie_json TEXT,
  cookie_expires_at TEXT,
  last_login_at TEXT,
  login_status TEXT NOT NULL DEFAULT 'unknown',
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Table: `reminder_prefs`

```sql
CREATE TABLE reminder_prefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  timezone TEXT NOT NULL DEFAULT 'Asia/Taipei',
  schedule_json TEXT NOT NULL DEFAULT '["09:00","21:00"]',
  remind_types_json TEXT NOT NULL DEFAULT '["homework","announcement"]',
  lead_times_json TEXT NOT NULL DEFAULT '["24h","3h"]',
  quiet_hours_json TEXT NOT NULL DEFAULT '{"start":"23:00","end":"07:00"}',
  digest_mode TEXT NOT NULL DEFAULT 'delta',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Table: `events_cache`

```sql
CREATE TABLE events_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'e3',
  event_uid TEXT NOT NULL,
  event_type TEXT NOT NULL,
  course_id TEXT,
  title TEXT NOT NULL,
  due_at TEXT,
  payload_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  UNIQUE(user_id, event_uid),
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Table: `notification_log`

```sql
CREATE TABLE notification_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  event_uid TEXT,
  notification_type TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  result TEXT NOT NULL,
  details TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

## Command Contract (LINE)

### Authentication

- `e3 login`
  - Starts login flow.
  - Preferred: send one-time login web link.
  - Alternative: interactive account/password collection in direct chat.

- `e3 relogin`
  - Force renew session/cookies.

- `e3 logout`
  - Delete encrypted cookie/password and disable reminders.

### Status / Data

- `e3 狀態`
  - Show connection status, last sync time, next scheduled reminder.

- `e3 課程`
  - List courses from latest successful sync.

- `e3 近期`
  - Show upcoming items (next 7 days by default).

### Reminder Settings

- `e3 remind on`
- `e3 remind off`
- `e3 remind time 09:00,21:00`
- `e3 remind type homework,announcement,grade`
- `e3 remind before 24h,3h`
- `e3 remind quiet 23:00-07:00`
- `e3 remind digest delta|summary`
- `e3 remind show`

## Scheduler Jobs

### Job 1: `sync_e3_data` (default 09:00 / 21:00 per user timezone)

Steps:
1. Load all users with `reminder_prefs.enabled=1`.
2. For each user, check if now matches user's `schedule_json`.
3. Validate session cookie; if expired, try re-login if credential is available.
4. Fetch latest E3 data.
5. Normalize into event records and upsert into `events_cache`.
6. Mark stale events as resolved if not present in latest sync.

### Job 2: `dispatch_reminders` (every 10 minutes)

Steps:
1. Load active events from `events_cache`.
2. For each user event, compute whether any lead time threshold is reached.
3. Respect quiet hours and digest mode.
4. Check `notification_log` dedup key (`user_id + event_uid + lead_time`).
5. Send LINE message and store send result.

## Default Reminder Rules

- Schedule: `09:00`, `21:00`
- Types: `homework`, `announcement`
- Lead times: `24h`, `3h`
- Digest mode: `delta` (new or changed only)

## Security Rules

1. Encrypt credentials/cookies at rest (AES-GCM with key from env).
2. Never log account/password/cookie raw values.
3. Use short-lived session if possible.
4. On repeated auth failures, disable auto login and ask user to relogin.

## Suggested Environment Variables

```env
E3_API_BASE_URL=http://127.0.0.1:5001
E3_ENCRYPTION_KEY=base64-encoded-32-byte-key
E3_DEFAULT_TIMEZONE=Asia/Taipei
E3_DEFAULT_SCHEDULE=09:00,21:00
```

## Rollout Plan

1. Phase 1: manual commands only (`e3 login`, `e3 課程`, `e3 近期`)
2. Phase 2: add scheduler with fixed default reminders
3. Phase 3: add per-user reminder config commands
4. Phase 4: add digest mode and quiet hours

## Extra Recommendations

1. Add `/healthz` and `/metrics` for scheduler/queue visibility.
2. Add admin command: `e3 admin stats` (only allowed user IDs).
3. Add retry with exponential backoff for E3 transient failures.
4. Add user-facing `e3 test remind` command.
