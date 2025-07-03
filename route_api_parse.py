import os
from dotenv import load_dotenv
load_dotenv()

import googlemaps
from fastapi import FastAPI, Query
from pydantic import BaseModel

import networkx as nx
from typing import List, Tuple, Dict
from haversine import haversine

import json
import base64

import firebase_admin
from firebase_admin import credentials, firestore

from routeSuggestion import tag_and_flatten_routes, build_graph, score_path, give_feedback

app = FastAPI()

# === Initialise Firebase App ===
# if not firebase_admin._apps:
#     cred = credentials.Certificate("firebase-service-account.json")
#     firebase_admin.initialize_app(cred)

firebase_cert = os.getenv("FIREBASE_CREDENTIALS")
if firebase_cert is None:
    raise ValueError("FIREBASE_CREDENTIALS env variable not set.")

cert_dict = json.loads(base64.b64decode(firebase_cert).decode("utf-8"))
cred = credentials.Certificate(cert_dict)

firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

# === Google Maps API ===
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY").strip('"')
gmaps = googlemaps.Client(key=API_KEY)

# === Data ===
emission_rate = {"DRIVING": 180, "WALKING": 50, "TRANSIT": 80, "BICYCLING": 50}

def get_user_preferences(user_id: str) -> Dict[str, float]:
    doc_ref = db.collection("user").document(user_id)
    doc = doc_ref.get()

    if doc.exists:
        data = doc.to_dict()
        weights = data.get("weight_preference", {})
        return {
            "alpha": weights.get("co2", 0.5),
            "beta": weights.get("time", 0.5)
        }
    else:
        # Default fallback if user not found
        return {
            "alpha": 0.5,
            "beta": 0.5
        }

def update_user_preferences(user_id: str, alpha: float, beta: float):
    db.collection("user").document(user_id).set({
        "weight_preference": {
            "co2": alpha,
            "time": beta
        }
    }, merge=True)

# === API Models ===
class RecommendationRequest(BaseModel):
    user_id: str
    origin: str
    destination: str

class FeedbackRequest(BaseModel):
    user_id: str
    chosen_index: int

# === Globals for Feedback Memory ===
last_routes = {}

# === API Endpoints ===
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI!"}

@app.post("/recommend")
def recommend_routes(req: RecommendationRequest):

    print("✅ Received /recommend request:")
    print(f"User ID: {req.user_id}")
    print(f"Origin: {req.origin}")
    print(f"Destination: {req.destination}")

    steps = tag_and_flatten_routes(req.origin, req.destination)
    G = build_graph(steps)

    if not steps:
        return {"error": "No route steps found."}

    start_node = steps[0][0]
    end_node = steps[-1][1]

    try:
        all_paths = list(nx.all_simple_paths(G, source=start_node, target=end_node))
    except:
        return {"error": "No paths between origin and destination"}

    if not all_paths:
        return {"error": "No valid paths"}

    prefs = get_user_preferences(req.user_id)
    alpha = prefs['alpha']
    beta = prefs['beta']

    times = []
    emissions = []
    for path in all_paths:
        t = sum(G[path[i]][path[i+1]]['time'] for i in range(len(path)-1))
        e = sum(G[path[i]][path[i+1]]['emission'] for i in range(len(path)-1))
        times.append(t)
        emissions.append(e)

    max_time = max(times)
    max_emission = max(emissions)

    scored = [score_path(G, path, alpha, beta, max_time, max_emission) for path in all_paths]
    scored.sort(key=lambda x: x['score'])

    last_routes[req.user_id] = {
        "scored": scored,
        "max_time": max_time,
        "max_emission": max_emission
    }

    return {
        "user": req.user_id,
        "recommendations": [
            {
                "rank": i+1,
                "steps": r['path'],
                "polyline_points": r['coordinates'],
                "total_time": r["total_time"],
                "total_emission": r["total_emission"],
                "score": r["score"]
            }
            for i, r in enumerate(scored[:])  # top 3
        ]
    }

@app.post("/feedback")
def feedback(req: FeedbackRequest):
    data = last_routes.get(req.user_id)
    if not data:
        return {"error": "No previous recommendation for user"}

    chosen = data["scored"][req.chosen_index]
    top = data["scored"][0]

    prefs = get_user_preferences(req.user_id)
    alpha = prefs['alpha']
    beta = prefs['beta']

    new_alpha, new_beta = give_feedback(alpha, beta, chosen, top, data["max_time"], data["max_emission"])

    update_user_preferences(req.user_id, new_alpha, new_beta)

    # Read updated values from Firestore
    prefs = get_user_preferences(req.user_id)
    # alpha = prefs['alpha']
    # beta = prefs['beta']
    

    # if doc.exists:
    #     weights = doc.to_dict().get("weight_preference", {})
    #     return {
    #         "message": "Feedback received",
    #         "new_alpha": weights.get("co2", 0.5),
    #         "new_beta": weights.get("time", 0.5)
        # }

    # Fallback response
    return {
        "message": "Feedback received, but user record not found after update",
        "new_alpha": prefs['alpha'],
        "new_beta": prefs['beta']
    }