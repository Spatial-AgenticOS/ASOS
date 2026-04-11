"""
FERAL HUP Reference Device Adapters
=====================================
Ready-to-use adapters for common device types.
Use these as templates when writing your own HUP adapter.
"""

from hardware.adapters.wristband import WristbandAdapter
from hardware.adapters.smart_home import SmartHomeAdapter
from hardware.adapters.robot_arm import RobotArmAdapter

__all__ = ["WristbandAdapter", "SmartHomeAdapter", "RobotArmAdapter"]
