---
title: SRVO-001 SERVO Error - Excess Followers
created: 2026-04-26
updated: 2026-04-26
type: concept
tags: [alarm, servo, SRVO, emergency-stop, r-30ib, troubleshooting]
sources: [B-83284EN-1_07_01.PDF]
confidence: high
contested: false
contradictions: []
---

# SRVO-001 SERVO Error - Excess Followers

## Alarm Definition

**SRVO-001** — *SERVO Error: Excess followers* — indicates that the position error (difference between commanded position and actual position) for one or more robot axes has exceeded the permissible threshold. This alarm triggers an emergency stop condition and halts all motion.

## Key Finding

POC testing confirmed that SRVO-001 is an **emergency stop condition** and is **NOT related to rigid parameter settings**. The alarm is triggered by actual mechanical or servo hardware issues, not by incorrect parameter configuration.

^[B-83284EN-1_07_01.PDF]

## Possible Causes

1. **Mechanical Binding** — Physical obstruction or resistance in the robot axis transmission (gearbox, coupling, bearings)
2. **Servo Amplifier Fault** — Defective or failing servo amplifier drive
3. **Motor Failure** — Faulty servo motor or encoder malfunction
4. **Excessive Payload** — Load exceeds robot specifications causing position tracking errors
5. **Cable Interruption** — Loose or damaged motor/encoder cables

## Troubleshooting Steps

1. **Check for Obstructions** — Inspect robot work envelope for physical barriers
2. **Verify Payload** — Confirm payload matches program specifications
3. **Review Servo Amplifier Status** — Check for LED fault indicators on amplifier
4. **Inspect Cables** — Verify all motor and encoder cable connections
5. **Jog Axis Manually** — Attempt to manually move affected axis to identify binding
6. **Review Alarm History** — Check if alarm recurs at specific positions or motions

^[B-83284EN-1_07_01.PDF]

## Related Parameters

- `$PARAM_KAREL` — Karel system parameters (not directly related but checked during diagnosis)
- `$SCREEN` — Display configuration parameters

## Related Entities

- [[fanuc-r30ib-controller|R-30iB Controller]] — Primary controller platform for this alarm
- [[fanuc-30i-series|FANUC 30i Series]] — Related controller ecosystem

## Manual Reference

- **B-83284EN-1_07_01.PDF** — Main servo alarm troubleshooting section (605 alarm mentions in manual)
- **B-83284EN_09_01.PDF** — Additional servo-related diagnostics

## See Also

- [[fanuc-r30ib-controller|SRVO Alarm Series]] — Other SRVO codes on R-30iB
