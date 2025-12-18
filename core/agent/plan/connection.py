from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .subscene import Subscene


class Connection:
    """
    Represents a connection between subscenes in the agent's scene graph.
    Connections define transition conditions between subscenes.
    """

    def __init__(self, name: str, from_subscene: 'Subscene', to_subscene: 'Subscene', condition: str):
        """
        Initialize a Connection.
        
        Args:
            name (str): The name of the connection (short, explanatory text)
            from_subscene (Subscene): The starting subscene
            to_subscene (Subscene): The destination subscene
            condition (str): Text description of conditions for transitioning
        """
        self.name = name
        self.from_subscene = from_subscene
        self.to_subscene = to_subscene
        self.condition = condition
        
    def to_dict(self) -> dict:
        """Convert the connection to a dictionary representation."""
        return {
            "name": self.name,
            "from": self.from_subscene.name,
            "to": self.to_subscene.name,
            "condition": self.condition
        }