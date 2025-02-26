from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Any, Literal, Union

class MessageType(str, Enum):
    """Main types of messages that can be dispatched."""
    LOG = "log"
    PROGRESS = "progress"
    RESULT = "result"

class LogLevel(str, Enum):
    """Log levels for LOG type messages."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"

class ProgressPhase(str, Enum):
    """Different phases of the workflow for PROGRESS type messages."""
    QUERY_INTERPRETATION = "query_interpretation"
    WEB_SEARCH = "web_search"
    CONTENT_EDITING = "content_editing"
    RESULT_CHECK = "result_check"

@dataclass
class WorkflowMessage:
    """Standard message structure for workflow events."""
    type: MessageType
    subtype: Union[LogLevel, ProgressPhase, Literal["final"]]  # "final" is for RESULT type
    message: str
    data: Optional[Any] = None

    @classmethod
    def log(cls, level: LogLevel, message: str, data: Optional[Any] = None) -> "WorkflowMessage":
        """Create a log message."""
        return cls(
            type=MessageType.LOG,
            subtype=level,
            message=message,
            data=data
        )

    @classmethod
    def progress(cls, phase: ProgressPhase, message: str, data: Optional[Any] = None) -> "WorkflowMessage":
        """Create a progress message."""
        return cls(
            type=MessageType.PROGRESS,
            subtype=phase,
            message=message,
            data=data
        )

    @classmethod
    def result(cls, message: str, data: Any) -> "WorkflowMessage":
        """Create a result message."""
        return cls(
            type=MessageType.RESULT,
            subtype="final",
            message=message,
            data=data
        )

    def to_dict(self) -> dict:
        """Convert the message to a dictionary for dispatching."""
        return {
            "type": self.type,
            "subtype": self.subtype,
            "message": self.message,
            "data": self.data
        } 