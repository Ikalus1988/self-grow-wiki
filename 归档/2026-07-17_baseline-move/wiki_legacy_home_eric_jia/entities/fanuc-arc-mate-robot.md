---
title: FANUC ARC Mate Robot Series
type: robot
manufacturer: FANUC Corporation
series: ARC Mate
application: Arc Welding
models:
  - ARC Mate 120+C/20T
  - M-20+A
relatedControllers:
  - R-30iB Controller
documentation:
  - B-83034EN_08.PDF
  - B-82874EN_13.PDF
tags:
  - industrial-robot
  - arc-welding
  - fanuc
  - 6-axis
---

# FANUC ARC Mate Robot Series

The **ARC Mate** is FANUC Corporation's series of 6-axis industrial robots specifically designed for arc welding applications. These robots are part of FANUC's established robotics lineup and integrate with the company's R-30iB controller platform.

## Models

### ARC Mate 120+C/20T
Mechanical unit variant documented in B-83034EN_08.PDF. Features a compact structure optimized for welding torch access in confined workspaces.

### M-20+A
Higher payload variant documented in B-82874EN_13.PDF. Offers extended reach and payload capacity suitable for larger welding fixtures and multi-station configurations.

## Specifications Overview

| Specification | ARC Mate 120+C/20T | M-20+A |
|---------------|---------------------|--------|
| Axes | 6 | 6 |
| Application | Arc Welding | Arc Welding |
| Controller | R-30iB | R-30iB |

## Integration

The ARC Mate series pairs with the [[fanuc-r30ib-controller]] for motion control and process management. The R-30iB controller provides the computational platform for welding parameter optimization, path planning, and coordination with external equipment such as welding power sources and positioners.

Related entities include [[fanuc-arc-welding-package]] for complete welding system configurations.

## See Also

- [[fanuc-r30ib-controller]]
- [[fanuc-industrial-robot-overview]]
