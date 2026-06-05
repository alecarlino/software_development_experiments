# Flood Inundation - Physical Validation Report

**Verdict: PASS**

## 1. Monotonicity of flooded area

The flooded area must never decrease as the water level rises.

- Result: PASS
- Water levels swept: 30 m to 100 m (21 steps)
- Non-monotonic drops detected: none
- Plateaus (flat steps, allowed but noted): 5 step(s), e.g. [(82.5, 86.0), (86.0, 89.5), (89.5, 93.0)]

### Water level vs. flooded area

| Water level (m) | Flooded area (%) |
| ---: | ---: |
| 30.0 | 0.00 |
| 33.5 | 1.46 |
| 37.0 | 4.37 |
| 40.5 | 8.59 |
| 44.0 | 15.47 |
| 47.5 | 23.42 |
| 51.0 | 33.58 |
| 54.5 | 44.70 |
| 58.0 | 56.54 |
| 61.5 | 67.34 |
| 65.0 | 76.99 |
| 68.5 | 84.31 |
| 72.0 | 89.63 |
| 75.5 | 93.25 |
| 79.0 | 94.98 |
| 82.5 | 95.54 |
| 86.0 | 95.54 |
| 89.5 | 95.54 |
| 93.0 | 95.54 |
| 96.5 | 95.54 |
| 100.0 | 95.54 |

## 2. Unit check (metres vs. feet)

- Result: PASS
- Maximum elevation 100.0 m is within a plausible range for metres; no unit mismatch detected.

## 3. Anomalies / unexpected behaviour

- None: all checked values are within physical expectations.

---
Final verdict: **PASS**
