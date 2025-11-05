import os, logging
from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

APP_TZ = os.getenv("APP_TZ", "America/Santiago")

# Fallback zona horaria (en contenedores a veces falla zoneinfo)
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(APP_TZ)
except Exception:
    import pytz
    TZ = pytz.timezone(APP_TZ)

app = Flask(__name__)  # sin template_folder por ahora

@app.route("/")
def root():
    return "ntrapp OK - raíz viva (sin templates)"

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})

@app.errorhandler(500)
def handle_500(e):
    app.logger.exception("Internal Server Error: %s", e)
    return jsonify({"error": "internal_server_error", "detail": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
