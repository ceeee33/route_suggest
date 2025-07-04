from dotenv import load_dotenv
load_dotenv()

import googlemaps
import networkx as nx
from haversine import haversine
import heapq
import random
from typing import List, Tuple, Dict
import os
import polyline


# === Step 1: Connect to Google Maps ===
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY").strip('"')
gmaps = googlemaps.Client(key=API_KEY)


# === Step 2: Get route steps with congestion-aware duration ===
# def get_route_steps(origin, destination, mode="driving"):
#     directions = gmaps.directions(
#         origin,
#         destination,
#         mode=mode,
#         departure_time="now",
#         traffic_model="best_guess"
#     )
#     steps = directions[0]['legs'][0]['steps']
#     path = []

#     for step in steps:
#         start = (step['start_location']['lat'], step['start_location']['lng'])
#         end = (step['end_location']['lat'], step['end_location']['lng'])
#         distance_km = step['distance']['value'] / 1000
#         duration_sec = step.get('duration_in_traffic', step['duration'])['value']
#         duration_min = duration_sec / 60
#         mode = step.get('travel_mode', 'driving')
#         path.append((start, end, distance_km, duration_min, mode))

#     return path

def get_route_steps(origin, destination, mode="driving", alternatives=True):
    """
    Retrieves directions between origin and destination for a specific mode.
    Supports driving, walking, bicycling, and transit (with detailed transit info).
    
    Parameters:
        origin (str): Start location.
        destination (str): End location.
        mode (str): Travel mode - "driving", "walking", "bicycling", "transit".
        alternatives (bool): Whether to fetch multiple route options (if supported).
    
    Returns:
        List[Dict]: A list of routes. Each route is a list of step dictionaries.
    """
    directions = gmaps.directions(
        origin,
        destination,
        mode=mode,
        departure_time="now",
        traffic_model="best_guess",
        alternatives=alternatives
    )

    all_routes = []

    for route in directions:
        steps = route['legs'][0]['steps']
        path = []
        coordinates = []

        for step in steps:
            start = (step['start_location']['lat'], step['start_location']['lng'])
            end = (step['end_location']['lat'], step['end_location']['lng'])
            distance_km = step['distance']['value'] / 1000
            # duration_min = step['duration']['value'] / 60
            travel_mode = step['travel_mode']

            # Use duration_in_traffic if driving mode and field exists
            if mode == "driving" and 'duration_in_traffic' in step:
                duration_sec = step['duration_in_traffic']['value']
            else:
                duration_sec = step['duration']['value']
            duration_min = duration_sec / 60

            step_info = {
                "from": start,
                "to": end,
                "distance_km": distance_km,
                "duration_min": duration_min,
                "mode": travel_mode,
                "polyline": polyline.decode(step['polyline']['points'])
            }

            # If this step involves transit, include extra transit details
            if travel_mode == "TRANSIT":
                transit = step['transit_details']
                vehicle_type = transit['line']['vehicle']['type']
                line_name = transit['line'].get('short_name') or transit['line'].get('name')
                departure_stop = transit['departure_stop']['name']
                arrival_stop = transit['arrival_stop']['name']
                num_stops = transit['num_stops']

                step_info.update({
                    "transit_vehicle": vehicle_type,
                    "line": line_name,
                    "departure_stop": departure_stop,
                    "arrival_stop": arrival_stop,
                    "num_stops": num_stops
                })

            path.append(step_info)
            # coordinates.append(start)
        
        # Make sure last point is included
        # if steps:
        #     coordinates.append((steps[-1]['end_location']['lat'], steps[-1]['end_location']['lng']))

        # all_routes.append({
        #     "path": path,
        #     "coordinates": coordinates
        # })

        all_routes.append(path)

    return all_routes

def tag_and_flatten_routes(origin, destination):
    modes = ["DRIVING", "BICYCLING", "WALKING", "TRANSIT"]
    all_steps = []
    # all_coordinates = []

    for mode in modes:
        try:
            routes = get_route_steps(origin, destination, mode=mode)
            for route in routes:
                for step in route:
                    start = tuple(step['from'])
                    end = tuple(step['to'])
                    dist = step['distance_km']
                    time = step['duration_min']
                    travel_mode = step['mode'].upper()  # Must match emission_rate keys

                    all_steps.append((start, end, dist, time, travel_mode, step['polyline']))
                # route_coords.append(start)

            # route_coords.append(end)
            # all_coordinates.append(route_coords)
        except Exception as e:
            print(f"Error getting steps for mode {mode}: {e}")
    
    return all_steps

# === Step 3: Build graph ===
emission_rate = {"DRIVING": 180, "WALKING": 60, "TRANSIT": 50, "BICYCLING": 50}

def build_graph(steps):
    G = nx.DiGraph()
    for start, end, dist, time, mode, polyline in steps:
        emission = dist * emission_rate[mode]
        G.add_edge(start, end, distance=dist, time=time, emission=emission, mode=mode, polyline=polyline)
    return G

# === Step 4: User profiles and scoring ===
# def simulate_user_profiles():
#     return {
#         'user_1': {'alpha': 0.6, 'beta': 0.4},  # prefers green
#         'user_2': {'alpha': 0.3, 'beta': 0.7},  # prefers speed
#     }

def score_path(graph, path, alpha, beta, max_time, max_emission):
    total_time = 0
    total_emission = 0
    steps = []
    coordinates = []

    for i in range(len(path) - 1):
        data = graph[path[i]][path[i + 1]]
        steps.append(f"{path[i]} → {path[i+1]} via {data['mode']}")
        # coordinates.append(path[i])

        edge_polyline = data['polyline']
        if i == 0:
            coordinates.extend(edge_polyline)
        else:
            coordinates.extend(edge_polyline[1:])  # Skip duplicate point

        total_time += data['time']
        total_emission += data['emission']
    
    # coordinates.append(path[-1])

    norm_time = total_time / max_time
    norm_emission = total_emission / max_emission
    score = alpha * norm_emission + beta * norm_time

    print("Coor:", coordinates)

    return {
        "path": steps,
        "coordinates": coordinates,
        "total_time": total_time,
        "total_emission": total_emission,
        "score": score
    }

# def give_feedback(user_profiles, user_id, route, liked, max_time, max_emission):
#     profile = user_profiles[user_id]

#     # Normalize emission and time for both routes
#     chosen_norm_emission = route['total_emission'] / max_emission
#     chosen_norm_time = route['total_time'] / max_time
#     top_norm_emission = liked['total_emission'] / max_emission
#     top_norm_time = liked['total_time'] / max_time

#     # Invert to turn lower values into higher preference
#     chosen_emission_pref = 1 - chosen_norm_emission
#     chosen_time_pref = 1 - chosen_norm_time
#     top_emission_pref = 1 - top_norm_emission
#     top_time_pref = 1 - top_norm_time

#     # Calculate delta between chosen and top-ranked route
#     delta_emission = chosen_emission_pref - top_emission_pref
#     delta_time = chosen_time_pref - top_time_pref

#     # Adjust alpha and beta slightly in the direction of the chosen route
#     learning_rate = 0.1  # Small step for smooth learning
#     profile['alpha'] += learning_rate * delta_emission
#     profile['beta'] += learning_rate * delta_time

#     # Normalize alpha and beta so they always sum to 1
#     total = profile['alpha'] + profile['beta']
#     profile['alpha'] = round(profile['alpha'] / total, 3)
#     profile['beta'] = round(1.0 - profile['alpha'], 3)

#     print(f"⚖️ User {user_id} chose a route different from the top suggestion.")
#     print(f"Updated weights → Alpha (CO₂): {profile['alpha']} | Beta (Time): {profile['beta']}")

    # update_user_preferences(user_id, profile['alpha'], profile['beta'])

    # if liked:
    #     print(f"\u2705 User {user_id} liked the route.")
    #     if route['total_emission'] < 100:
    #         profile['alpha'] = min(profile['alpha'] + 0.05, 1.0)
    #         profile['beta'] = 1.0 - profile['alpha']
    # else:
    #     print(f"❌ User {user_id} disliked the route.")
    #     profile['beta'] = min(profile['beta'] + 0.05, 1.0)
    #     profile['alpha'] = 1.0 - profile['beta']

def give_feedback(user_id: str, chosen_route: dict, top_route: dict, max_time: float, max_emission: float):
    # === Normalize emission and time for both routes ===
    chosen_norm_emission = chosen_route['total_emission'] / max_emission
    chosen_norm_time = chosen_route['total_time'] / max_time
    top_norm_emission = top_route['total_emission'] / max_emission
    top_norm_time = top_route['total_time'] / max_time

    # === Invert to convert lower values into higher preference ===
    chosen_emission_pref = 1 - chosen_norm_emission
    chosen_time_pref = 1 - chosen_norm_time
    top_emission_pref = 1 - top_norm_emission
    top_time_pref = 1 - top_norm_time

    # === Compute preference difference ===
    delta_emission = chosen_emission_pref - top_emission_pref
    delta_time = chosen_time_pref - top_time_pref

    # === Update weights with learning rate ===
    learning_rate = 0.1
    alpha += learning_rate * delta_emission
    beta += learning_rate * delta_time

    # === Normalize alpha and beta to ensure they sum to 1 ===
    total = alpha + beta
    alpha = round(alpha / total, 3)
    beta = round(1.0 - alpha, 3)

    print(f"✅ Updated preferences for user '{user_id}': alpha = {alpha}, beta = {beta}")

# def get_user_preferences(user_id: str) -> Dict[str, float]:
#     doc_ref = db.collection("user").document(user_id)
#     doc = doc_ref.get()

#     if doc.exists:
#         data = doc.to_dict()
#         weights = data.get("weight_preference", {})
#         return {
#             "alpha": weights.get("co2", 0.5),
#             "beta": weights.get("time", 0.5)
#         }
#     else:
#         # Default fallback if user not found
#         return {
#             "alpha": 0.5,
#             "beta": 0.5
#         }

# def update_user_preferences(user_id: str, alpha: float, beta: float):
#     db.collection("user").document(user_id).set({
#         "weight_preference": {
#             "co2": alpha,
#             "time": beta
#         }
#     }, merge=True)

# === Step 5: Run Program ===
# if __name__ == "__main__":
#     origin = "Gurney Plaza"
#     destination = "Queensbay Mall, Penang"

#     steps = tag_and_flatten_routes(origin, destination)
#     G = build_graph(steps)

#     start_node = steps[0][0]
#     end_node = steps[-1][1]

#     try:
#         all_paths = list(nx.all_simple_paths(G, source=start_node, target=end_node))
#     except:
#         print("\u26a0\ufe0f No paths found.")
#         exit()

#     if not all_paths:
#         print("\u26a0\ufe0f No valid paths.")
#         exit()

#     for user_id in user_profiles:
#         alpha = user_profiles[user_id]['alpha']
#         beta = user_profiles[user_id]['beta']

#         print(f"\n--- Recommendations for {user_id} (alpha={alpha:.2f}, beta={beta:.2f}) ---")

#         # Calculate max values for normalization
#         times = []
#         emissions = []
#         for path in all_paths:
#             t, e = 0, 0
#             for i in range(len(path)-1):
#                 edge = G[path[i]][path[i+1]]
#                 t += edge['time']
#                 e += edge['emission']
#             times.append(t)
#             emissions.append(e)
#         max_time = max(times)
#         max_emission = max(emissions)

#         # Score and sort
#         scored_routes = [score_path(G, p, alpha, beta, max_time, max_emission) for p in all_paths]
#         scored_routes.sort(key=lambda r: r['score'])
#         best_route = scored_routes[0]

#         # Print all routes
#         for i, route in enumerate(scored_routes, 1):
#             print(f"\n🔹 Route {i}")
#             for step in route["path"]:
#                 print("   ", step)
#             print(f"   🕒 Time: {route['total_time']:.2f} min | ♻️ CO₂: {route['total_emission']:.2f} g | 💰 Score: {route['score']:.3f}")

#         chosen_route = scored_routes[1]

#         if (chosen_route != best_route):
#             give_feedback(user_profiles, user_id, best_route, chosen_route, max_time, max_emission)

#     print("\n🔄 Updated User Preferences:")
#     for user_id, profile in user_profiles.items():
#         print(f"{user_id}: alpha={profile['alpha']:.2f}, beta={profile['beta']:.2f}")
