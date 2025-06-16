import os, logging
from functools import lru_cache

from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
import google.generativeai as genai
from dotenv import load_dotenv

# ── env & logging ─────────────────────────────────────────────
load_dotenv()  # reads .env in project root
logging.basicConfig(
    format="%(levelname)s | %(asctime)s | %(message)s",
    level=logging.INFO
)

MONGO_URI      = os.getenv("MONGO_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not (MONGO_URI and GEMINI_API_KEY):
    raise RuntimeError("Set MONGO_URI and GEMINI_API_KEY in .env")

# ── Flask / Mongo / Gemini init ───────────────────────────────
app = Flask(__name__)
CORS(app)

client = MongoClient(MONGO_URI)
db     = client["steamdb"]
games  = db["games"]
pipes  = db["pipelines"]

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-1.5-pro"

# ── small cache so repeated prompts don’t re‑charge API ───────
@lru_cache(maxsize=32)
def cached_ai_summary(prompt: str) -> str:
    logging.info("Gemini API call (cache miss)")
    model   = genai.GenerativeModel(model_name=GEMINI_MODEL)
    return model.generate_content(prompt).text

# ── API: list all pipeline names ──────────────────────────────
@app.route("/pipelines", methods=["GET"])
def get_pipeline_names():
    names = list(pipes.distinct("name"))
    return jsonify(names)

# ── API: run pipeline by name & return data + summary ─────────
@app.route("/dynamic-pipeline", methods=["GET"])
def dynamic_pipeline():
    name = request.args.get("name")
    if not name:
        return jsonify({"error": "Missing pipeline name"}), 400

    doc = pipes.find_one({"name": name})
    if not doc:
        return jsonify({"error": f"No pipeline named “{name}”"}), 404

    try:
        data = list(games.aggregate(doc["pipeline"]))
    except Exception as e:
        logging.exception("Mongo error")
        return jsonify({"error": f"MongoDB error: {e}"}), 500

    prompt  = (f"Summarize this data insight about “{name}”. "
               f"{doc.get('description','')}\n\n{data}")
    try:
        summary = cached_ai_summary(prompt)
    except Exception as e:
        logging.exception("Gemini error")
        return jsonify({"error": f"Gemini error: {e}"}), 500

    return jsonify({
        "title": name,
        "description": doc.get("description", ""),
        "data": data,
        "ai_summary": summary
    })

if __name__ == "__main__":
    app.run(debug=True)
