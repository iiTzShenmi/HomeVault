<<<<<<< HEAD
# Multi-Task Agent

A bot project designed for multiple task domains and multiple chat platforms.

## Features

- Multi-platform ready architecture
- LINE adapter implemented now
- Feature-first organization (`weather`, `e3`, ...)
- Weather feature for Taiwan city/district forecasts
- E3 feature command entry (`e3 幫助`, `e3 狀態`, `e3 課程`)

## Project Layout

```text
app.py                              # stable entrypoint used by service
agent/
  platforms/
    line/
      app.py                        # LINE webhook adapter
  features/
    weather/
      __init__.py
      handler.py                    # weather command handling
      weather_api.py                # Open-Meteo client
      geolocation.py                # geolocation + nearest-city logic
      city_data.py                  # Taiwan city/district coordinates
    e3/
      __init__.py
      handler.py                    # e3 command handling
      client.py                     # E3 API client wrapper
```

## Setup

1. Create a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure `.env`:

   ```env
   LINE_CHANNEL_SECRET=...
   LINE_CHANNEL_ACCESS_TOKEN=...
   E3_API_BASE_URL=http://127.0.0.1:5001
   ```

4. Run:

   ```bash
   python3 app.py
   ```

## Commands

```text
天氣 台北
天氣
e3 幫助
e3 login <帳號> <密碼>
e3 relogin
e3 logout
e3 狀態
e3 課程
e3 近期
```

## LINE Rich Menu

Create and bind the persistent HomeVault rich menu with:

```bash
/home/eason/server/venv/bin/python /home/eason/server/scripts/line_rich_menu.py
```

This script reads `LINE_CHANNEL_ACCESS_TOKEN` from `.env`, generates a simple PNG menu image, creates the rich menu, and binds it to all users.

## E3 Implementation

- Detailed plan: `docs/e3_manager_spec.md`

## Note

If you also want to rename the repository folder itself, rename
`/home/eason/server` to a neutral name (for example `/home/eason/multi-task-agent`) and update your systemd `WorkingDirectory` and `ExecStart` paths.
