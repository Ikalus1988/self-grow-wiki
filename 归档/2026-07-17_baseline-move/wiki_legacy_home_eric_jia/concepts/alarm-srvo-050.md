---
title: SRVO-050 Collision Detection Alarm
type: alarm
severity: serious
alarm_code: SRVO-050
related_alarms:
  - SRVO-051
  - SRVO-052
related_manual: B-83284EN-1_07_01.PDF
poc_test: POC test triggered SRVO-050 collision detection in testing
related_entities:
  - fanuc-r30ib-controller
  - fanuc-arc-mate-robot
tags:
  - fanuc
  - collision-detection
  - servo-alarm
  - robot-safety
created: 2026-04-26
---

# SRVO-050: Collision Detection

## Overview

SRVO-050 is a **Collision Detection** alarm on FANUC robots, indicating that the robot's servo system has detected an unexpected resistance or impact during motion. This safety feature is designed to protect the robot, tooling, and surrounding equipment from damage caused by collisions.

## Alarm Details

| Field | Value |
|-------|-------|
| Alarm Code | SRVO-050 |
| Severity | Serious |
| Alarm Type | Servo Error |
| Manual Reference | B-83284EN-1_07_01.PDF |

## Cause

SRVO-050 triggers when the robot's servo motors detect a sudden increase in torque beyond the programmed collision detection threshold. This can occur due to:

- **Physical collision** with an object, fixture, or operator
- **Incorrect collision sensitivity settings** (灵敏度设置不当)
- **Tool or workpiece interference** during program execution
- **Mechanical binding** in joints or传动部件
- **Incorrect payload settings** causing miscalculated torque expectations

## Resolution

1. **Immediate Stop**: Press the **EMERGENCY STOP** button to halt all robot motion
2. **Inspect**: Check for visible collisions, debris, or mechanical issues
3. **Clear the cause**: Remove the source of resistance or collision
4. **Reset the alarm**: Use the **RESET** button on the teach pendant
5. **Verify**: Jog the robot gently to confirm the issue is resolved before resuming

## Related Alarms

- [[alarm-srvo-051]] — Collision Detection (Chain 2)
- [[alarm-srvo-052]] — Collision Detection (Group 2)

## Related Entities

- [[fanuc-r30ib-controller]] - The controller platform where this alarm was observed
- [[fanuc-arc-mate-robot]] - The robot model involved in POC testing

## POC Test Notes

During proof-of-concept testing, SRVO-050 was triggered unexpectedly during a routine arc welding program on the [[fanuc-arc-mate-robot]]. Investigation revealed that the collision sensitivity parameters were set too aggressive for the specific tooling configuration. Parameters were subsequently tuned to allow for normal process forces while maintaining safety margins.

## References

- FANUC B-83284EN-1_07_01.PDF (Alarm & Remedy Manual)
- [[fanuc-r30ib-controller]] documentation
