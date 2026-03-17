from agent.config import auto_reload_enabled, port
from agent.platforms.line.app import app


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port(), threaded=True, use_reloader=auto_reload_enabled())
