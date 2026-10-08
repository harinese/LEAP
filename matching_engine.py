import math
import random
from typing import Optional, Dict, Any, List
import db_manager

# Hubballi Corridor Matrix
CORRIDORS = {
    "belagavi": {
        "canonical": "Belagavi",
        "distance_km": 98,
        "base_rate_per_tonne": 420,
        "waypoints": ["dharwad", "kittur", "hirebagewadi", "belagavi"]
    },
    "davanagere": {
        "canonical": "Davanagere",
        "distance_km": 148,
        "base_rate_per_tonne": 550,
        "waypoints": ["kundgol", "shiggaon", "haveri", "ranibennur", "harihar", "davanagere"]
    },
    "bengaluru": {
        "canonical": "Bengaluru",
        "distance_km": 412,
        "base_rate_per_tonne": 1150,
        "waypoints": ["haveri", "davanagere", "chitradurga", "tumakuru", "bengaluru"]
    },
    "pune": {
        "canonical": "Pune",
        "distance_km": 438,
        "base_rate_per_tonne": 1220,
        "waypoints": ["belagavi", "kolhapur", "karad", "satara", "pune"]
    },
    "bagalkot": {
        "canonical": "Bagalkot",
        "distance_km": 132,
        "base_rate_per_tonne": 510,
        "waypoints": ["navalgund", "nargund", "kerur", "bagalkot"]
    },
    "goa": {
        "canonical": "Goa",
        "distance_km": 178,
        "base_rate_per_tonne": 690,
        "waypoints": ["dharwad", "alnavar", "ramnagar", "anmod", "ponda", "panaji"]
    }
}

def normalize_city(city: str) -> str:
    c = city.strip().lower()
    if "bangalore" in c or "bengaluru" in c or "ಬೆಂಗಳೂರು" in c:
        return "bengaluru"
    if "belgaum" in c or "belagavi" in c or "ಬೆಳಗಾವಿ" in c:
        return "belagavi"
    if "davangere" in c or "davanagere" in c or "ದಾವಣಗೆರೆ" in c:
        return "davanagere"
    if "pune" in c or "poona" in c or "ಪುಣೆ" in c:
        return "pune"
    if "bagalkot" in c or "ಬಾಗಲಕೋಟೆ" in c:
        return "bagalkot"
    if "goa" in c or "panaji" in c or "ಗೋವಾ" in c:
        return "goa"
    return c

def compute_route_similarity(truck_dest: str, load_dest: str) -> float:
    t_key = normalize_city(truck_dest)
    l_key = normalize_city(load_dest)

    if t_key == l_key:
        return 1.0

    t_corridor = CORRIDORS.get(t_key)
    l_corridor = CORRIDORS.get(l_key)

    if t_corridor and l_key in t_corridor["waypoints"]:
        return 0.85
    if l_corridor and t_key in l_corridor["waypoints"]:
        return 0.80

    return 0.0

def compute_capacity_similarity(truck_cap: float, load_weight: float) -> float:
    if truck_cap <= 0:
        return 0.0
    if load_weight > (truck_cap * 1.05):
        return 0.0

    ratio = load_weight / truck_cap
    if 0.70 <= ratio <= 1.0:
        return 1.0
    elif 0.50 <= ratio < 0.70:
        return 0.85
    elif ratio < 0.50:
        return 0.60
    return 0.90

def calculate_return_price(destination: str, weight: float, driver_min: float = 0, shipper_budget: float = 0) -> float:
    key = normalize_city(destination)
    corridor = CORRIDORS.get(key)
    if corridor:
        standard_rate = weight * corridor["base_rate_per_tonne"]
        # Return freight discount: 22% below regular outbound rate
        discounted = round(standard_rate * 0.78 / 100) * 100
    else:
        discounted = round((weight * 650 + 1500) / 100) * 100

    if driver_min > 0 and shipper_budget > 0:
        if driver_min <= shipper_budget:
            return round((driver_min + shipper_budget) / 2)
        return driver_min
    elif driver_min > 0:
        return max(driver_min, discounted)
    elif shipper_budget > 0:
        return min(shipper_budget, discounted)

    return discounted

def find_best_load_for_truck(destination: str, capacity: float, min_price: float = 0) -> Optional[Dict[str, Any]]:
    db_manager.expire_stale_records()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM loads WHERE status = 'PENDING'")
    pending_loads = cursor.fetchall()
    conn.close()

    best_match = None
    highest_score = 0.0

    for l in pending_loads:
        load = dict(l)
        route_sim = compute_route_similarity(destination, load["destination"])
        if route_sim == 0.0:
            continue

        cap_sim = compute_capacity_similarity(capacity, load["weight_tonnes"])
        if cap_sim == 0.0:
            continue

        price_sim = 1.0
        if min_price > 0 and load["max_budget"] > 0:
            if min_price <= load["max_budget"]:
                price_sim = 1.0
            else:
                price_sim = max(0.4, 1.0 - (min_price - load["max_budget"]) / min_price)

        overall_score = round(route_sim * 0.50 + cap_sim * 0.35 + price_sim * 0.15, 2)

        if overall_score > highest_score and overall_score >= 0.60:
            agreed_price = calculate_return_price(load["destination"], load["weight_tonnes"], min_price, load["max_budget"])
            highest_score = overall_score
            best_match = {
                "load_id": load["id"],
                "shipper_name": load["shipper_name"],
                "shipper_phone": load["phone"],
                "cargo_type": load["cargo_type"],
                "weight_tonnes": load["weight_tonnes"],
                "pickup_location": load["pickup_location"],
                "destination": load["destination"],
                "agreed_price": agreed_price,
                "overall_score": int(overall_score * 100),
                "route_score": int(route_sim * 100),
                "capacity_score": int(cap_sim * 100),
            }

    return best_match

def find_best_truck_for_load(destination: str, weight: float, max_budget: float = 0) -> Optional[Dict[str, Any]]:
    db_manager.expire_stale_records()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trucks WHERE status = 'AVAILABLE'")
    available_trucks = cursor.fetchall()
    conn.close()

    best_match = None
    highest_score = 0.0

    for t in available_trucks:
        truck = dict(t)
        route_sim = compute_route_similarity(truck["destination"], destination)
        if route_sim == 0.0:
            continue

        cap_sim = compute_capacity_similarity(truck["capacity_tonnes"], weight)
        if cap_sim == 0.0:
            continue

        price_sim = 1.0
        if truck["min_price"] > 0 and max_budget > 0:
            if max_budget >= truck["min_price"]:
                price_sim = 1.0
            else:
                price_sim = max(0.4, 1.0 - (truck["min_price"] - max_budget) / truck["min_price"])

        overall_score = round(route_sim * 0.50 + cap_sim * 0.35 + price_sim * 0.15, 2)

        if overall_score > highest_score and overall_score >= 0.60:
            agreed_price = calculate_return_price(destination, weight, truck["min_price"], max_budget)
            highest_score = overall_score
            best_match = {
                "truck_id": truck["id"],
                "driver_name": truck["driver_name"],
                "driver_phone": truck["phone"],
                "truck_type": truck["truck_type"],
                "capacity_tonnes": truck["capacity_tonnes"],
                "current_location": truck["current_location"],
                "destination": truck["destination"],
                "agreed_price": agreed_price,
                "overall_score": int(overall_score * 100),
                "route_score": int(route_sim * 100),
                "capacity_score": int(cap_sim * 100),
            }

    return best_match

def create_match_record(truck_id: int, load_id: int, route_score: float, capacity_score: float,
                        overall_score: float, agreed_price: float) -> Dict[str, Any]:
    token = f"RET-{random.randint(1000, 9999)}"
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO matches (truck_id, load_id, route_score, capacity_score, overall_score, agreed_price, booking_token, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'OFFERED')
    """, (truck_id, load_id, route_score, capacity_score, overall_score, agreed_price, token))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "match_id": match_id,
        "booking_token": token,
        "agreed_price": agreed_price,
        "status": "OFFERED"
    }

def confirm_match(match_id: int, truck_id: Optional[int] = None, load_id: Optional[int] = None):
    conn = db_manager.get_connection()
    with conn:
        conn.execute("""
            UPDATE matches
            SET status = 'CONFIRMED', driver_accepted = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (match_id,))

        if truck_id:
            conn.execute("UPDATE trucks SET status = 'MATCHED' WHERE id = ?", (truck_id,))
        if load_id:
            conn.execute("UPDATE loads SET status = 'MATCHED' WHERE id = ?", (load_id,))
    conn.close()
