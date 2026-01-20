import requests

# API base URL
API_BASE_URL = "http://localhost:8003/api"

# Check if agent already exists, if so, get its ID
print("Checking if agent exists...")
try:
    response = requests.get(f"{API_BASE_URL}/agents")
    agents = response.json()
    existing_agent = None
    for agent in agents:
        if agent["name"] == "Sleep Companion":
            existing_agent = agent
            break

    if existing_agent:
        print(f"Agent 'Sleep Companion' already exists with ID: {existing_agent['id']}")
        agent_id = existing_agent["id"]
        # Delete all scenes for this agent
        print("Deleting existing scenes...")
        scenes = requests.get(f"{API_BASE_URL}/scenes").json()

        # Handle different API response formats
        if isinstance(scenes, dict):
            scenes_list = scenes.get("data", scenes.get("scenes", []))
        elif isinstance(scenes, list):
            scenes_list = scenes
        else:
            scenes_list = []

        for scene in scenes_list:
            if isinstance(scene, dict) and scene.get("agent_id") == agent_id:
                # Delete scene (this will cascade delete subscenes and connections)
                scene_id = scene.get("id")
                if scene_id:
                    try:
                        requests.delete(f"{API_BASE_URL}/scenes/{scene_id}")
                        print(f"Deleted scene: {scene.get('name')}")
                    except Exception as e:
                        print(f"Error deleting scene: {e}")
    else:
        # Create agent
        print("Creating agent...")
        agent_data = {
            "name": "Sleep Companion",
            "description": "Virtual girlfriend who helps user fall asleep",
            "model_name": "doubao",
        }
        response = requests.post(f"{API_BASE_URL}/agents", json=agent_data)
        agent = response.json()
        print(f"Created agent: {agent}")
        agent_id = agent["id"]
except Exception as e:
    print(f"Error checking/creating agent: {e}")
    exit(1)

# Create scene
print("\nCreating scene...")
scene_data = {
    "name": "Sleep Companion Scene",
    "description": "Sleep companion scene",
    "agent_id": agent_id,
}
response = requests.post(f"{API_BASE_URL}/scenes", json=scene_data)
scene = response.json()
print(f"Created scene: {scene}")
scene_id = scene["id"]

# Create subscenes
print("\nCreating subscenes...")
subscenes_data = [
    {
        "name": "Bedtime Greeting",
        "type": "start",
        "state": "inactive",
        "description": "Warmly greet user",
        "mandatory": True,
        "objective": "Create a comfortable atmosphere",
        "scene_id": scene_id,
    },
    {
        "name": "Storytelling",
        "type": "normal",
        "state": "inactive",
        "description": "Tell gentle stories to help user relax",
        "mandatory": False,
        "objective": "Help user relax and prepare for sleep",
        "scene_id": scene_id,
    },
    {
        "name": "Breathing Exercise",
        "type": "normal",
        "state": "inactive",
        "description": "Guide user through breathing exercises",
        "mandatory": False,
        "objective": "Help body relax and prepare for sleep",
        "scene_id": scene_id,
    },
    {
        "name": "Goodnight Farewell",
        "type": "end",
        "state": "inactive",
        "description": "Say goodnight and wish sweet dreams",
        "mandatory": True,
        "objective": "Wish user sweet dreams",
        "scene_id": scene_id,
    },
]

subscenes = []
for subscene_data in subscenes_data:
    response = requests.post(
        f"{API_BASE_URL}/scenes/{scene_id}/subscenes", json=subscene_data
    )
    subscene = response.json()
    subscenes.append(subscene)
    print(f"Created subscene: {subscene}")

# Create connections
print("\nCreating connections...")
connections_data = [
    {
        "name": "Enter story time",
        "condition": "User wants to hear a story",
        "from_subscene": "Bedtime Greeting",
        "to_subscene": "Storytelling",
        "scene_id": scene_id,
    },
    {
        "name": "Enter relaxation exercise",
        "condition": "User feels tense or needs relaxation",
        "from_subscene": "Bedtime Greeting",
        "to_subscene": "Breathing Exercise",
        "scene_id": scene_id,
    },
    {
        "name": "Need further relaxation",
        "condition": "User wants to continue relaxing",
        "from_subscene": "Storytelling",
        "to_subscene": "Breathing Exercise",
        "scene_id": scene_id,
    },
    {
        "name": "Prepare for sleep",
        "condition": "User is already relaxed and ready to sleep",
        "from_subscene": "Storytelling",
        "to_subscene": "Goodnight Farewell",
        "scene_id": scene_id,
    },
    {
        "name": "Complete relaxation",
        "condition": "User has relaxed and ready to sleep",
        "from_subscene": "Breathing Exercise",
        "to_subscene": "Goodnight Farewell",
        "scene_id": scene_id,
    },
]

# Find subscene IDs by name
subscene_id_map = {subscene["name"]: subscene["id"] for subscene in subscenes}

for connection_data in connections_data:
    # Find subscene ID for from_subscene
    from_subscene_id = subscene_id_map.get(connection_data["from_subscene"])
    to_subscene_id = subscene_id_map.get(connection_data["to_subscene"])

    if from_subscene_id and to_subscene_id:
        # Add subscene IDs to connection data
        connection_data["from_subscene_id"] = from_subscene_id
        connection_data["to_subscene_id"] = to_subscene_id

        response = requests.post(
            f"{API_BASE_URL}/subscenes/{from_subscene_id}/connections",
            json=connection_data,
        )
        connection = response.json()
        print(f"Created connection: {connection}")
    else:
        print(
            f"Warning: Could not find subscene IDs for connection: {connection_data['name']}"
        )

print("\n=== All data inserted successfully ===")
print(f"Agent ID: {agent_id}")
print(f"Scene ID: {scene_id}")
print(f"Total subscenes: {len(subscenes)}")
print(f"Total connections: {len(connections_data)}")
