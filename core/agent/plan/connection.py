from typing import Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class Connection:
    """
    Represents a connection between subscenes in agent's scene graph.
    Connections define transition conditions between subscenes.
    """
    
    name: str # The name of the connection (short, explanatory text)
    from_subscene: str # The name of the starting subscene
    to_subscene: str # The name of the destination subscene
    condition: str = "" # Text description of conditions for transitioning
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the connection to a dictionary representation with proper JSON keys.
        
        Returns:
            Dict[str, Any]: Dictionary representation of the connection
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Create a Connection from a dictionary representation with proper JSON keys.
        
        Args:
            data (Dict[str, Any]): The dictionary representation of the connection
        
        Returns:
            Connection: The created Connection object
        """
        # Create instance using mapped data
        return cls(**data)
