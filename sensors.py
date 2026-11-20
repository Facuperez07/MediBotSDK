"""Selected HG IDL-shaped IMU/BMS fields for the service-robotics HMI.

This is intentionally NOT a full LowState_ or DDS payload: we omit MotorState_.
No physics, trajectories or actuator access are implied.
"""
from copy import deepcopy
from math import cos, sin


def quaternion_from_rpy(rpy):
    """[w,x,y,z] mathematically derived from injected RPY, not read from hardware."""
    r, p, y = rpy
    cr, sr = cos(r / 2), sin(r / 2)
    cp, sp = cos(p / 2), sin(p / 2)
    cy, sy = cos(y / 2), sin(y / 2)
    return [cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy,
            cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy]


def default_sensors():
    imu = {"rpy": [0.0, 0.0, 0.0], "quaternion": [1.0, 0.0, 0.0, 0.0],
           "gyroscope": [0.0, 0.0, 0.0], "accelerometer": [0.0, 0.0, 9.81]}
    return {"source": "synthetic_default", "valid": True,
            "bms_state": {"soc": 85, "soh": 98, "current": 0, "bmsvoltage": [0, 0, 0],
                          "temperature": [0]*12},
            "low_state": {"mode_pr": 0, "mode_machine": 0, "tick": 0,
                          "imu_state": imu}}


def snapshot(sensors):
    return deepcopy(sensors)
