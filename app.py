import os
import io
import csv
import json
import base64
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, send_file, render_template

# -------------------------
# Configuración
# -------------------------
APP_TZ = os.getenv("APP_TZ", "America/Santiago")
TZ = ZoneInfo(APP_TZ)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # para chat.completions con visión

# Baseline de Paula
PAULA_BASELINE = {
    "ferritina": 10.5,
    "vitamina_d": 25.4,
    "homa_ir": 4.6,
    "ldl": 97,
    "hdl": 39,
    "tg": 193,
}

# Memoria en proceso
LOG = []
# ----- NUEVO: tabla con el formato solicitado -----
LOG_TABLE = []  # cada item es un dict con claves exactas:
# "Día","Fecha","Hora","Tipo de comida","Descripción","Impacto según exámenes","Color"
def append_table_row(dia, fecha_iso, hora_local, tipo, descripcion, impacto, color):
    # fecha visual DD/MM/YYYY
    y,m,d = fecha_iso.split("-")
    fecha_vis = f"{d}/{m}/{y}"
    row = {
        "Día": int(dia),
        "Fecha": fecha_vis,
        "Hora": hora_local,
        "Tipo de comida": tipo or "",
        "Descripción": descripcion or "",
        "Impacto según exámenes": impacto or "",
        "Color": color or "🟡"
    }
    LOG_TABLE.append(row)


# Cliente OpenAI si hay API key (opcional)
client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        client = None

# Heurísticas de impacto
IMPACT_RULES = {
    "azucares_simples": {"homa_ir": +2, "tg": +2, "color": "red"},
    "refinados": {"homa_ir": +1, "tg": +1, "color": "red"},
    "alcohol": {"tg": +2, "homa_ir": +1, "color": "red"},
    "grasas_saturadas": {"ldl": +2, "tg": +1, "color": "red"},
    "fibra": {"homa_ir": -1, "ldl": -1, "tg": -1, "color": "green"},
    "omega_3": {"tg": -2, "hdl": +1, "color": "green"},
    "hierro_hemo": {"ferritina": +2, "color": "green"},
    "vitamina_c": {"ferritina": +1, "color": "green"},
    "vitamina_d_fuente": {"vitamina_d": +1, "color": "green"},
}

SYSTEM_PROMPT = (
    "Eres un nutricionista que analiza imágenes de comidas para una paciente con: "
    f"HOMA-IR {PAULA_BASELINE['homa_ir']}, TG {PAULA_BASELINE['tg']} mg/dL, LDL {PAULA_BASELINE['ldl']} mg/dL, "
    f"HDL {PAULA_BASELINE['hdl']} mg/dL, Ferritina {PAULA_BASELINE['ferritina']} ng/mL, "
    f"Vitamina D {PAULA_BASELINE['vitamina_d']} ng/mL. "
    "Responde SOLO JSON con las claves: items (lista de objetos {nombre, porcion}), "
    "etiquetas (lista con valores como 'azucares_simples','alcohol','grasas_saturadas','fibra','omega_3','hierro_hemo','vitamina_c','vitamina_d_fuente'), "
    "comentario_breve (string, 1-2 frases)."
)

def now_local():
    return datetime.now(TZ)

def score_color(tags):
    score = 0
    colors = []
    for t in tags:
        eff = IMPACT_RULES.get(t, {})
        score += eff.get("homa_ir", 0) + eff.get("tg", 0) + eff.get("ldl", 0) - eff.get("hdl", 0)
        if eff.get("color"):
            colors.append(eff["color"])
    if "red" in colors and score >= 2:
        return "🔴"
    if "green" in colors and score <= 0 and "red" not in colors:
        return "🟢"
    return "🟡"

def impact_text(tags):
    out = []
    for t in tags:
        eff = IMPACT_RULES.get(t)
        if not eff:
            continue
        parts = []
        if eff.get("homa_ir", 0) > 0: parts.append("↑ resistencia a la insulina (HOMA-IR)")
        if eff.get("tg", 0) > 0: parts.append("↑ triglicéridos")
        if eff.get("ldl", 0) > 0: parts.append("↑ LDL")
        if eff.get("hdl", 0) > 0: parts.append("↑ HDL")
        if eff.get("ferritina", 0) > 0: parts.append("↑ ferritina")
        if eff.get("vitamina_d", 0) > 0: parts.append("↑ vitamina D")
        if parts:
            out.append(f"{t.replace('_', ' ')}: " + ", ".join(parts))
    return "; ".join(out) or "Impacto incierto (etiquetas vacías)."

def recommendation(tags):
    adv = []
    if "alcohol" in tags or "azucares_simples" in tags:
        adv.append("Preferir agua/soda sin azúcar o versión sin alcohol.")
    if "grasas_saturadas" in tags:
        adv.append("Elegir cortes magros y métodos con menos grasa.")
    if "fibra" not in tags:
        adv.append("Agregar ensalada/verduras o legumbres para subir fibra.")
    if "hierro_hemo" in tags and "vitamina_c" not in tags:
        adv.append("Acompañar con vitamina C (limón, tomate) para absorber hierro.")
    if "omega_3" in tags and PAULA_BASELINE["tg"] > 150:
        adv.append("Bueno para triglicéridos; 2-3 veces/semana.")
    if "vitamina_d_fuente" in tags and PAULA_BASELINE["vitamina_d"] < 30:
        adv.append("Suma a vitamina D; considerar exposición solar segura o suplemento médico.")
    return " ".join(adv) or "Mantener equilibrio y porciones moderadas."

# Fallback por texto (cuando no hay visión)
def tags_from_text(text: str):
    t = (text or "").lower()
    tags = set()
    if any(w in t for w in ["chocolate", "dulce", "galleta", "helado", "postre"]):
        tags.update(["azucares_simples", "grasas_saturadas"])
    if any(w in t for w in ["bebida", "jugo", "gaseosa", "soda"]):
        tags.add("azucares_simples")
    if any(w in t for w in ["cerveza", "vino", "pisco", "aperol", "spritz"]):
        tags.update(["alcohol", "azucares_simples"])
    if any(w in t for w in ["ensalada", "verde", "legumbre", "fibra"]):
        tags.add("fibra")
    if any(w in t for w in ["salmón", "atun", "sardina", "caballa"]):
        tags.update(["omega_3"])
    if any(w in t for w in ["vacuno", "asado"]):
        tags.update(["hierro_hemo", "grasas_saturadas"])
    return list(tags)

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/summary")
def summary():
    return render_template("summary.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    meal_type = request.form.get("tipo", "")
    desc_user = request.form.get("descripcion", "")

    if not file:
        return jsonify({"error": "Falta imagen"}), 400

    etiquetas = []
    comentario = ""
    items = [{"nombre": "comida", "porcion": "?"}]

    if client:
        try:
            # Usamos chat.completions con JSON mode y image_url (data URI)
            image_b64 = base64.b64encode(file.read()).decode("utf-8")
            mime = file.mimetype or "image/jpeg"
            data_url = f"data:{mime};base64,{image_b64}"

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "Identifica alimentos y etiquetas nutricionales. Devuelve SOLO JSON válido."},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}}
                ]}
            ]

            # Vision call with strict JSON mode
            comp = client.chat.completions.create(
                model=OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=messages
            )
            content = comp.choices[0].message.content
            if not content or not isinstance(content, str):
                # If model didn't return text content, fallback to text tagging
                raise ValueError(f"Empty/None content from model: {type(content)}")
            try:
                parsed = json.loads(content)
            except Exception as je:
                # Try to coerce to valid JSON (strip code fences)
                cleaned = content.strip()
                if cleaned.startswith('```'):
                    cleaned = cleaned.strip('`')
                    cleaned = cleaned.split('\n',1)[-1]
                    if cleaned.strip().startswith('json'):
                        cleaned = cleaned.split('\n',1)[-1]
                parsed = json.loads(cleaned)
            etiquetas = parsed.get("etiquetas", []) or []
            comentario = parsed.get("comentario_breve", "") or ""
            if parsed.get("items"):
                items = parsed["items"]
        except Exception as e:
            etiquetas = tags_from_text(desc_user)
            comentario = f"Etiquetado por texto (fallback). Error visión: {e}"
    else:
        etiquetas = tags_from_text(desc_user)
        comentario = "Sin OPENAI_API_KEY: etiquetado por texto (fallback)."

    color = score_color(etiquetas)
    impacto = impact_text(etiquetas)
    reco = recommendation(etiquetas)

    now = datetime.now(TZ)
    registro = {
        "fecha_iso": now.date().isoformat(),
        "dia": now.strftime("%d"),
        "hora": now.strftime("%H:%M"),
        "tipo": meal_type or "",
        "descripcion": desc_user or ", ".join([i.get("nombre", "?") for i in items]),
        "impacto": impacto,
        "color": color,
        "recomendacion": reco,
        "etiquetas": etiquetas,
        "modelo": OPENAI_MODEL if client else "fallback",
    }
    LOG.append(registro)

    # Añadir al formato de tabla solicitado
    append_table_row(dia=registro['dia'], fecha_iso=registro['fecha_iso'], hora_local=registro['hora'],
                    tipo=registro['tipo'], descripcion=registro['descripcion'],
                    impacto=registro['impacto'], color=registro['color'])

    return jsonify({"ok": True, "registro": registro, "comentario": comentario})

@app.route("/registros", methods=["GET"])
def registros():
    return jsonify({"count": len(LOG), "items": LOG})

@app.route("/export.csv", methods=["GET"])
def export_csv():
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["fecha_iso", "dia", "hora", "tipo", "descripcion", "impacto", "color", "recomendacion", "etiquetas", "modelo"],
    )
    writer.writeheader()
    for r in LOG:
        r2 = r.copy()
        r2["etiquetas"] = ",".join(r2.get("etiquetas", []))
        writer.writerow(r2)
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="paula_registros.csv")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

@app.route("/registros_tabla", methods=["GET"])
def registros_tabla():
    # Devuelve la sesión en el formato exacto pedido
    return jsonify({"count": len(LOG_TABLE), "items": LOG_TABLE})

@app.route("/tabla", methods=["GET"])
def tabla():
    # Render simple HTML table with the exact columns
    headers = ["Día","Fecha","Hora","Tipo de comida","Descripción","Impacto según exámenes","Color"]
    return render_template("tabla.html", headers=headers, rows=LOG_TABLE)

