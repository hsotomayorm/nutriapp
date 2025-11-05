# Paula Food Tracker (UI móvil + Resumen mensual)

App web lista para contenedor (IBM Code Engine). Permite:
- Subir foto de comida y analizar impacto según exámenes de Paula (OpenAI visión si está configurado).
- Ver un **Resumen mensual** con totales, distribución por tipo y detalle por día.
- Exportar CSV.

## Variables de entorno
- `OPENAI_API_KEY` (opcional; si no está, usa fallback sin visión)
- `OPENAI_MODEL` (opcional; por defecto `gpt-4o`)
- `APP_TZ` (opcional; por defecto `America/Santiago`)
- `PORT` (opcional; por defecto `8080`)

## Desarrollo local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...  # opcional
python app.py
# abre http://localhost:8080
```

## Despliegue en IBM Code Engine (ejemplo)
```bash
# 1) Construye y publica la imagen
export IMG=tuusuario/paula-food-tracker:full
docker build -t $IMG .
docker push $IMG

# 2) Secrets y app
ibmcloud ce project select -n <tu-proyecto>
ibmcloud ce secret create --name openai_key_secret --from-literal OPENAI_API_KEY=$OPENAI_API_KEY

ibmcloud ce app create --name paula-food-tracker \
  --image $IMG \
  --env OPENAI_API_KEY=@openai_key_secret \
  --env APP_TZ=America/Santiago \
  --cpu 0.25 --memory 0.5G --min 0 --max 1 --port 8080
```

> Almacenamiento es efímero; usa **Descargar CSV** con frecuencia.