from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .subscene import Subscene


class SceneState(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Scene:
    """
    Represents a main scene in the agent's scene graph.
    A scene is a high-level context that the agent can be in.
    """

    def __init__(self, name: str, identification_condition: str):
        """
        Initialize a Scene.
        
        Args:
            name (str): The name of the scene (short, explanatory text)
            identification_condition (str): Text description of conditions for entering this scene
        """
        self.name = name
        self.identification_condition = identification_condition
        self.state = SceneState.INACTIVE
        self.subscenes: list[Subscene] = []
        
    def activate(self):
        """Set the scene state to active."""
        self.state = SceneState.ACTIVE
        
    def deactivate(self):
        """Set the scene state to inactive."""
        self.state = SceneState.INACTIVE
        
    def add_subscene(self, subscene: 'Subscene'):
        """Add a subscene to this scene."""
        self.subscenes.append(subscene)
        
    def to_dict(self) -> dict:
        """Convert the scene to a dictionary representation."""
        return {
            "name": self.name,
            "identification_condition": self.identification_condition,
            "state": self.state.value,
            "subscenes": [subscene.to_dict() for subscene in self.subscenes]
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create a Scene from a dictionary representation."""
        from .subscene import Subscene
        
        scene = cls(
            name=data["name"],
            identification_condition=data["identification_condition"]
        )
        scene.state = SceneState(data["state"].lower())
        
        # Create subscenes from dict data
        if "subscenes" in data and data["subscenes"]:
            scene.subscenes = [Subscene.from_dict(subscene_data) for subscene_data in data["subscenes"]]
        
        return scene