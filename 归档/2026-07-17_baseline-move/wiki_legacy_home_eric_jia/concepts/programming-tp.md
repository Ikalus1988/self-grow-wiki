---
title: TP Programming Basics
created: 2026-04-26
updated: 2026-04-26
type: concept
tags:
  - programming
  - tp
  - teach-pendant
  - robot-programming
  - fanuc
sources:
  - operator-manual
confidence: high
contested: false
contradictions: 
---

# TP Programming Basics

TP (Teach Pendant) programming is the primary method for programming FANUC industrial robots. TP programs control motion, I/O, logic, and communication operations.

## Core Motion Instructions

| Instruction | Function | Example |
|-------------|----------|---------|
| MOVJ | Joint interpolation move | `MOVJ P[1] 100% FINE` |
| MOVL | Linear move | `MOVL P[2] 500mm/s FINE` |
| MOVC | Circular move | `MOVC P[3] 200mm/s FINE` |

## Program Structure

A basic TP program consists of:
1. **Program header** — Name, creation date, version
2. **Motion instructions** — Robot movement commands
3. **I/O instructions** — Digital/analog signal control
4. **Logic instructions** — WAIT, IF, SELECT, JUMP
5. **End instruction** — `END` or `END (1)`

## Motion Groups

TP programs can control multiple motion groups (robots) simultaneously:
- `UFRAME_NUM` — User coordinate system
- `UTOOL_NUM` — Tool coordinate system
- `PAYLOAD` — Payload mass setting

## Related Concepts

TP programming on the [[fanuc-r30ib-controller|R-30iB Controller]] supports the full instruction set including advanced features like:
- Coordinated motion (multiple robots)
- Advanced I/O handling
- Ethernet/IP communication

## See Also

- [[fanuc-r30ib-controller]] — Controller supporting TP programming
- [[fanuc-arc-mate-robot]] — Robot commonly programmed via TP
