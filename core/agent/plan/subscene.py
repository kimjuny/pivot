from enum import Enum

from .connection import Connection


class SubsceneType(Enum):
    START = "start"
    END = "end"
    NORMAL = "normal"


class SubsceneState(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Subscene:
    """
    Represents a subscene in the agent's scene graph.
    Subscenes are nodes within a main scene and can be start, end, or normal nodes.
    """

    def __init__(self, name: str, subscene_type: SubsceneType, mandatory: bool, objective: str):
        """
        Initialize a Subscene.
        
        Args:
            name (str): The name of the subscene (short, explanatory text)
            subscene_type (SubsceneType): Type of the subscene (start, end, or normal)
            mandatory (bool): Whether this node is mandatory (cannot be skipped)
            objective (str): Text description of what should be achieved in this subscene
            state (SubsceneState): State of the subscene (active or inactive)
            connections (List[Connection], optional): List of connections from this subscene to other subscenes. Defaults to empty list.
        """
        self.name = name
        self.type = subscene_type
        self.mandatory = mandatory
        self.objective = objective
        self.state = SubsceneState.INACTIVE
        self.connections: list[Connection] = []
        
    def activate(self):
        """Set the subscene state to active."""
        self.state = SubsceneState.ACTIVE
        
    def deactivate(self):
        """Set the subscene state to inactive."""
        self.state = SubsceneState.INACTIVE
        
    def add_connection(self, connection: Connection):
        """Add a connection from this subscene."""
        self.connections.append(connection)
        
    def to_dict(self) -> dict:
        """Convert the subscene to a dictionary representation."""
        return {
            "name": self.name,
            "type": self.type.value,
            "mandatory": self.mandatory,
            "objective": self.objective,
            "state": self.state.value,
            "connections": [conn.to_dict() for conn in self.connections]
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create a Subscene from a dictionary representation with connections."""
        
        subscene = cls(
            name=data["name"],
            subscene_type=SubsceneType(data["type"]),
            mandatory=data["mandatory"],
            objective=data["objective"]
        )
        subscene.state = SubsceneState(data["state"].lower())
        
        # Process connections directly from data
        if data.get("connections"):
            subscene.connections = [Connection.from_dict(connection_data) for connection_data in data["connections"]]
        
        return subscene
