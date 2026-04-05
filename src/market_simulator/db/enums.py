from enum import Enum


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    PAST_DUE = "PAST_DUE"


class StrategyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class StrategyType(str, Enum):
    SIMULATION = "SIMULATION"
    PORTFOLIO = "PORTFOLIO"
    COMPARISON_TEMPLATE = "COMPARISON_TEMPLATE"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class RunType(str, Enum):
    SIMULATION = "SIMULATION"
    PORTFOLIO = "PORTFOLIO"
    COMPARISON = "COMPARISON"
    PARAMETER_SWEEP = "PARAMETER_SWEEP"


class ExecutorType(str, Enum):
    SIMULATION_EXECUTOR = "SIMULATION_EXECUTOR"
    PORTFOLIO_EXECUTOR = "PORTFOLIO_EXECUTOR"
    COMPARISON_EXECUTOR = "COMPARISON_EXECUTOR"
    SWEEP_EXECUTOR = "SWEEP_EXECUTOR"


class ArtifactStorageType(str, Enum):
    LOCAL = "LOCAL"
    S3 = "S3"


class TrackingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELED = "CANCELED"


class TrackingMode(str, Enum):
    LATEST_VERSION = "LATEST_VERSION"
    PINNED_VERSION = "PINNED_VERSION"