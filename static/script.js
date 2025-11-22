/*******************************************************
 * GLOBAL VARIABLES
 *******************************************************/
let map;
let userLat = null;
let userLon = null;
let userMarker = null;
let placeMarkers = [];
let typingMessage = null; // for typing indicator

// ========================= MARKER ICONS =========================

// Blue marker for source (user or city centre)
const sourceIcon = L.icon({
  iconUrl: "https://maps.gstatic.com/mapfiles/ms2/micons/blue-dot.png",
  iconSize: [32, 32],
  iconAnchor: [16, 32],
});

// Red marker for destination places
const placeIcon = L.icon({
  iconUrl: "https://maps.gstatic.com/mapfiles/ms2/micons/red-dot.png",
  iconSize: [32, 32],
  iconAnchor: [16, 32],
});

/*******************************************************
 * UTILITY: Add message to chat
 *******************************************************/
function addMessage(text, sender) {
  const messages = document.getElementById("messages");

  const msg = document.createElement("div");
  msg.classList.add("message", sender);

  // 🔥 Render HTML from backend (we send <br> and bullets)
  msg.innerHTML = text;

  messages.appendChild(msg);
  messages.scrollTop = messages.scrollHeight;
}

/*******************************************************
 * UTILITY: Typing indicator
 *******************************************************/
function showTyping() {
  const messages = document.getElementById("messages");
  typingMessage = document.createElement("div");
  typingMessage.classList.add("message", "bot");
  typingMessage.innerHTML = "Tourism assistant is thinking...";
  messages.appendChild(typingMessage);
  messages.scrollTop = messages.scrollHeight;
}

function hideTyping() {
  if (typingMessage) {
    typingMessage.remove();
    typingMessage = null;
  }
}

/*******************************************************
 * MAP INITIALIZATION
 *******************************************************/
function initMap() {
  map = L.map("map").setView([20.5937, 78.9629], 5); // India default

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
  }).addTo(map);
}

/*******************************************************
 * MAP: Mark source location (user or city centre)
 *******************************************************/
function markUserLocation(lat, lon, label = "Source Location") {
  if (userMarker) {
    map.removeLayer(userMarker);
  }

  userMarker = L.marker([lat, lon], {
    icon: sourceIcon,
    title: label,
  })
    .addTo(map)
    .bindPopup(label)
    .openPopup();

  map.setView([lat, lon], 14);
}

/*******************************************************
 * MAP: Clear attraction markers
 *******************************************************/
function clearPlaceMarkers() {
  placeMarkers.forEach((m) => map.removeLayer(m));
  placeMarkers = [];
}

/*******************************************************
 * MAP: Plot Attractions (with distance)
 *******************************************************/
function plotPlacesOnMap(places) {
  clearPlaceMarkers();

  const markers = [];

  places.forEach((p) => {
    const marker = L.marker([p.lat, p.lon], { icon: placeIcon })
      .addTo(map)
      .bindPopup(`${p.name}<br>${p.distance_km} km away`);

    markers.push(marker);
    placeMarkers.push(marker);
  });

  // Auto-fit the map to show source + all places
  if (markers.length > 0) {
    const all = [...markers];
    if (userMarker) all.push(userMarker);

    const group = L.featureGroup(all);
    map.fitBounds(group.getBounds().pad(0.2));
  }
}

/*******************************************************
 * SEND MESSAGE TO FLASK BACKEND
 *******************************************************/
async function sendToBackend(message) {
  const payload = {
    message: message,
    lat: userLat,
    lon: userLon,
  };

  const res = await fetch("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return res.json();
}

/*******************************************************
 * CHAT HANDLER
 *******************************************************/
async function handleUserMessage(text) {
  addMessage(text, "user");
  showTyping();

  let data;
  try {
    data = await sendToBackend(text);
  } catch (err) {
    hideTyping();
    addMessage("Sorry, I couldn't fetch data right now.", "bot");
    console.error(err);
    return;
  }
  hideTyping();

  // Main bot reply
  addMessage(data.reply, "bot");

  // Clarify what the distances mean
  if (data.distance_from) {
    addMessage(
      `Note: distances on the map are measured from ${data.distance_from}.`,
      "bot"
    );
  }

  // Map centering + source marker (user or city centre)
  if (data.center_lat && data.center_lon) {
    const label =
      data.source_label ||
      data.distance_from_name ||
      (data.city ? `Center of ${data.city}` : "Source Location");

    markUserLocation(data.center_lat, data.center_lon, label);
  }

  // Places markers
  if (data.places && data.places.length > 0) {
    plotPlacesOnMap(data.places);
  }
}

/*******************************************************
 * GET USER LOCATION (geolocation) — NO BACKEND CALL HERE
 *******************************************************/
function detectUserLocation() {
  if (!navigator.geolocation) {
    addMessage("Your browser does not support geolocation.", "bot");
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      userLat = pos.coords.latitude;
      userLon = pos.coords.longitude;

      // Just mark user on map – NO places query
      markUserLocation(userLat, userLon, "Your Location");

      addMessage(
        "Your location detected! You can now ask things like:<br>• Places near me<br>• I’m going to go to Bangalore, let’s plan my trip.<br>• What’s the temperature in Mumbai?",
        "bot"
      );
    },
    () => {
      addMessage("Location access denied. You can still search by city.", "bot");
    }
  );
}

/*******************************************************
 * INITIALIZE CHAT + MAP ON PAGE LOAD
 *******************************************************/
window.onload = () => {
  initMap();
  detectUserLocation();

  // Initial greeting
  addMessage(
    "Hi! I'm your tourism assistant.","bot");

  const form = document.getElementById("chat-form");
  const input = document.getElementById("user-input");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    handleUserMessage(text);
  });
};
