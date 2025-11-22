from flask import Flask, request, jsonify, render_template
import requests
import math
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

print(">>> app.py is running")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ------------------------------------------------------------
# Distance function (backend computes distance)
# ------------------------------------------------------------
def distance_km(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2

    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


# ------------------------------------------------------------
# Intent Detector
# ------------------------------------------------------------
def detect_intent(message):
    text = message.lower()

    wants_weather = any(
        w in text for w in ["weather", "temperature", "temp"]
    )

    wants_places = any(
        p in text for p in ["places", "visit", "tourist", "attraction", "plan my trip"]
    )

    near_me = any(
        m in text for m in ["near me", "around me"]
    )

    if "trip" in text and not wants_weather and not wants_places:
        return {"weather": True, "places": True, "near_me": near_me}

    return {"weather": wants_weather, "places": wants_places, "near_me": near_me}


# ------------------------------------------------------------
# Extract City Name
# ------------------------------------------------------------
import re  # add this at top of file if not already there

def extract_place_name(message):
    text = message.lower()

    # Remove some filler phrases but DON'T eat the "to <city>" itself
    cleaned = text
    cleaned = re.sub(r"(going to|want to|gonna|planning to)\s+", "", cleaned)

    # Look for "to <place>" or "in <place>"
    match = re.search(r"\b(to|in)\s+([a-zA-Z\s]+)", cleaned)
    if not match:
        return None

    place = match.group(2).strip()

    # Stop at punctuation like comma, question mark, etc.
    place = re.split(r"[?,.]", place)[0].strip()

    if not place:
        return None

    return place.title()



# ------------------------------------------------------------
# Geocode Agent (Nominatim)
# ------------------------------------------------------------
def geocode_place(place):
    params = {
        "q": place,
        "format": "json",
        "limit": 1
    }
    headers = {
        "User-Agent": "tourism-multi-agent/1.0"
    }

    res = requests.get(NOMINATIM_URL, params=params, headers=headers)
    data = res.json()

    if not data:
        return None

    return {
        "lat": float(data[0]["lat"]),
        "lon": float(data[0]["lon"]),
        "name": data[0]["display_name"]
    }


# ------------------------------------------------------------
# Weather Agent (Open-Meteo)
# ------------------------------------------------------------
def get_weather(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "hourly": "precipitation_probability"
    }

    res = requests.get(OPEN_METEO_URL, params=params)
    data = res.json()

    weather = {
        "temp_c": data.get("current_weather", {}).get("temperature"),
        "rain_chance": data.get("hourly", {}).get("precipitation_probability", [None])[0]
    }

    return weather

def place_score(tags):
    """
    Higher score = more touristy / famous.
    """
    tourism = tags.get("tourism", "")
    historic = "historic" in tags

    if tourism in ["museum", "theme_park", "zoo"]:
        return 3  # very touristy
    if tourism == "attraction" or historic:
        return 2  # good tourist spot
    return 1  # parks, temples etc.

# ------------------------------------------------------------
# Places Agent (Overpass)
# ------------------------------------------------------------
def get_places(lat, lon, limit=5):
    print(">>> get_places called for:", lat, lon)  # debug

    # We will try bigger and bigger radii until we get enough places
    radii = [5000, 10000, 20000, 30000]  # 5 km, 10 km, 20 km, 30 km

    collected = []

    for r in radii:
        print(f">>> querying Overpass with radius {r} meters")

        query = f"""
        [out:json];
        (
          node["tourism"="attraction"](around:{r},{lat},{lon});
          node["tourism"="museum"](around:{r},{lat},{lon});
          node["tourism"="theme_park"](around:{r},{lat},{lon});
          node["tourism"="zoo"](around:{r},{lat},{lon});
          node["historic"](around:{r},{lat},{lon});
          node["leisure"="park"](around:{r},{lat},{lon});
          node["leisure"="garden"](around:{r},{lat},{lon});
          node["natural"="beach"](around:{r},{lat},{lon});
          node["natural"="peak"](around:{r},{lat},{lon});
          node["amenity"="place_of_worship"](around:{r},{lat},{lon});
        );
        out 80;
        """

        res = requests.post(OVERPASS_URL, data=query)
        data = res.json()

        if "elements" not in data:
            print(">>> no elements for radius", r)
            continue

        for el in data["elements"]:
            tags = el.get("tags", {})
            name = tags.get("name")

            if not name:
                continue

            # Filter out boring / non-tourist POIs
            bad_keywords = [
                "company", "group", "finance", "corporation", "pvt", "limited", "ltd",
                "hospital", "clinic", "bank", "school", "college", "office"
            ]
            lower_name = name.lower()
            if any(bad in lower_name for bad in bad_keywords):
                continue

            # Avoid duplicates (same name, same coordinates)
            already = any(
                p["name"] == name and abs(p["lat"] - el["lat"]) < 1e-5 and abs(p["lon"] - el["lon"]) < 1e-5
                for p in collected
            )
            if already:
                continue

            collected.append({
                "name": name,
                "lat": el["lat"],
                "lon": el["lon"],
                "tags": tags  # keep tags temporarily for scoring
            })

        # If we have enough places, we can stop expanding radius
        if len(collected) >= limit:
            break

    if not collected:
        print(">>> no collected places at all")
        return []

    # Compute distance from the reference point (city center or user) and score
    for p in collected:
        p["distance_km"] = round(distance_km(lat, lon, p["lat"], p["lon"]), 2)
        p["score"] = place_score(p["tags"])

    # Sort: highest score first, then closest distance
    collected.sort(key=lambda x: (-x["score"], x["distance_km"]))

    # Take at most 'limit' closest highest-scored places
    final_places = [
        {"name": p["name"], "lat": p["lat"], "lon": p["lon"], "distance_km": p["distance_km"]}
        for p in collected[:limit]
    ]

    print(">>> final places used:", [p["name"] for p in final_places])
    return final_places


# ------------------------------------------------------------
# Home Route  (serves index.html)
# ------------------------------------------------------------
@app.route("/")
def home():
    print("Home route triggered")  # debug
    return render_template("index.html")


# ------------------------------------------------------------
# Parent Agent (Core Brain)
# ------------------------------------------------------------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    user_lat = data.get("lat")
    user_lon = data.get("lon")

    intent = detect_intent(user_message)
    wants_weather = intent["weather"]
    wants_places = intent["places"]
    near_me = intent["near_me"]

    # If user asks for "near me" using location
    if near_me and wants_places and user_lat and user_lon:
        places = get_places(user_lat, user_lon)

        # Calculate distance
        for p in places:
            p["distance_km"] = round(distance_km(user_lat, user_lon, p["lat"], p["lon"]), 2)

        reply = "Here are the nearest places you can visit:\n" + \
                "\n".join([p["name"] for p in places])

        return jsonify({
            "reply": reply,
            "weather": None,
            "places": places,
            "city": None,
            "center_lat": user_lat,
            "center_lon": user_lon
        })

    # City-based query
    place_name = extract_place_name(user_message)
    if not place_name:
        return jsonify({"reply": "Please mention a city name.", "places": []})

    geo = geocode_place(place_name)
    if not geo:
        return jsonify({"reply": f'I don’t know if "{place_name}" exists.'})

    lat = geo["lat"]
    lon = geo["lon"]

    final_reply = ""

    # Weather
    weather_info = None
    if wants_weather:
        weather_info = get_weather(lat, lon)
        final_reply += (
            f"In {place_name} it’s currently {weather_info['temp_c']}°C "
            f"with a {weather_info['rain_chance']}% chance to rain.\n"
        )

    # Places
    places = []
    if wants_places:
        places = get_places(lat, lon)

        # Distance from city center
        for p in places:
            p["distance_km"] = round(distance_km(lat, lon, p["lat"], p["lon"]), 2)

        names = "\n".join([p["name"] for p in places])

        if "plan my trip" in user_message.lower():
            final_reply += f"In {place_name} these are the places you can go,\n{names}"
        else:
            final_reply += f"And these are the places you can go:\n{names}"

    return jsonify({
        "reply": final_reply.strip(),
        "weather": weather_info,
        "places": places,
        "city": place_name,
        "center_lat": lat,
        "center_lon": lon
    })


# ------------------------------------------------------------
# Run Flask
# ------------------------------------------------------------
if __name__ == "__main__":
    print(">>> Starting Flask dev server...")
    app.run(debug=True)
