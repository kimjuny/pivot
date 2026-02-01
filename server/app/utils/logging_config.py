# Logging configuration for core modules
import logging
import sys

# Create a logger for the core module
core_logger = logging.getLogger('core')
core_logger.setLevel(logging.DEBUG)  # Default to DEBUG level for development
core_logger.propagate = False  # Prevent logs from propagating to root logger

# Create a formatter that includes timestamp, logger name, log level, and message
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create a stream handler to output logs to stdout
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)

# Add the handler to the core logger
core_logger.addHandler(stream_handler)

# Make the logger accessible to other modules
def get_logger(name: str | None = None):
    """
    Get a logger instance with the given name. If no name is provided,
    returns the core logger instance.
    
    Args:
        name (str, optional): The name of the logger. If None, returns the core logger.
        
    Returns:
        logging.Logger: The logger instance.
    """
    if name:
        logger = logging.getLogger(f'core.{name}')
        logger.setLevel(logging.DEBUG)  # Set level for child logger
        logger.propagate = False  # Prevent logs from propagating to parent logger
        
        # Add stream handler to child logger if it doesn't have one
        if not logger.handlers:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)
            
        return logger
    return core_logger

# Set up a basic configuration for the root logger to capture all logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)