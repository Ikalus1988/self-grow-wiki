---
title: FANUC 30i/31i/35i Series
type: comparison
family: FANUC Series
related:
  - fanuc-r30ib-controller
concepts:
  - parameter-system-config
sources:
  - B-83284EN/01 (30i/31i/35i Operation Manual)
  - B-83284PL/01 (Parameter Manual)
tags:
  - cnc
  - fanuc
  - series-30i
created: 2026-04-26
---

# FANUC 30i/31i/35i Series Comparison

The FANUC 30i series is a family of high-performance CNC controllers designed for complex machine tool applications. This page compares the three main models within the series.

## Model Overview

| Feature | 30i | 31i | 35i |
|---------|-----|-----|-----|
| Max Controlled Axes | 32 | 24 | 16 |
| Max Spindles | 8 | 6 | 4 |
| Max PMC Axes | 32 | 24 | 16 |
| Processor | PowerPC 750FX | PowerPC 750FX | PowerPC 750FX |
| Display | 10.4" / 15" Color LCD | 10.4" Color LCD | 10.4" Color LCD |
| Memory Card | PCMCIA | PCMCIA | PCMCIA |
| Typical Application | Complex milling, turning centers | General machining centers | Simple machines, lathe |

## Key Differences

### 30i Model
The flagship model with maximum axis control capability. Designed for [[parameter-system-config|highly complex multi-axis machines]] such as 5-axis machining centers and multi-turret turning machines. Supports up to 32 linear axes and 8 spindles with full synchronization.

### 31i Model
The mid-range option balancing performance and cost. Suitable for most standard machining centers and turning centers with up to 24 controlled axes. Maintains full compatibility with the [[fanuc-r30ib-controller|R30iB controller]] ecosystem and options.

### 35i Model
Entry-level option optimized for simpler machine configurations. Commonly used in standard CNC lathes and 3-axis milling machines. Shares the same [[parameter-system-config|parameter structure]] as other 30i series models for consistency.

## Common Features

- **Same parameter system**: All three models use the FANUC parameter system configuration framework (B-83284PL/01)
- **PMC programming**: Compatible with LADDER III and the same PMC programming approach
- **Network connectivity**: Ethernet, PROFIBUS, and DeviceNet support
- **Motion control**: HRV+ and AI Advanced Preview Contour Control standard
- **Backup/Restore**: Memory card and USB flash drive support

## Related Entities

- [[fanuc-r30ib-controller]] — R30iB controller documentation
- [[parameter-system-config]] — Parameter system and configuration management

## References

- B-83284EN/01: 30i/31i/35i Series Operation Manual
- B-83284PL/01: 30i/31i/35i Series Parameter Manual
