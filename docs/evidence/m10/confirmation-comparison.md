# Separate random-read confirmation

4 KiB, 64 MiB aggregate, psync depth 1 per job. MiB/s; all samples retained.
Primary: 5 trials, 5+1 seconds; confirmation: 3 trials, 10+2 seconds (measurement+warmup).
Different windows are not pooled. SD is sample standard deviation, not a confidence interval.

| Campaign | Target | Jobs | n | Mean | Median | Min | Max | SD | CV % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| primary | secureram | 1 | 5 | 69.15 | 93.42 | 6.79 | 135.29 | 57.02 | 82.46 |
| primary | secureram | 2 | 5 | 6.63 | 6.06 | 2.99 | 9.46 | 2.72 | 40.96 |
| primary | secureram | 4 | 5 | 9.08 | 8.64 | 7.28 | 11.56 | 1.62 | 17.80 |
| primary | tmpfs | 1 | 5 | 1032.65 | 1006.07 | 787.06 | 1338.38 | 218.06 | 21.12 |
| primary | tmpfs | 2 | 5 | 2071.17 | 2146.42 | 1774.46 | 2220.95 | 188.10 | 9.08 |
| primary | tmpfs | 4 | 5 | 3103.46 | 3078.00 | 1837.75 | 4380.26 | 977.84 | 31.51 |
| confirmation | secureram | 1 | 3 | 88.46 | 85.79 | 15.95 | 163.62 | 73.87 | 83.51 |
| confirmation | secureram | 2 | 3 | 8.61 | 7.58 | 7.54 | 10.70 | 1.81 | 21.06 |
| confirmation | secureram | 4 | 3 | 9.00 | 8.97 | 8.29 | 9.75 | 0.73 | 8.13 |
| confirmation | tmpfs | 1 | 3 | 1339.61 | 1369.61 | 1190.14 | 1459.09 | 136.96 | 10.22 |
| confirmation | tmpfs | 2 | 3 | 2038.42 | 2051.33 | 1979.87 | 2084.04 | 53.27 | 2.61 |
| confirmation | tmpfs | 4 | 3 | 2609.15 | 2814.79 | 2132.18 | 2880.49 | 414.38 | 15.88 |

## Individual SecureRAM samples (trial order)

- primary, 1 jobs: 6.7910, 135.2854, 98.4967, 11.7672, 93.4165 MiB/s.
- primary, 2 jobs: 2.9905, 5.4536, 9.4606, 9.1865, 6.0595 MiB/s.
- primary, 4 jobs: 9.6183, 8.6406, 8.3245, 11.5604, 7.2776 MiB/s.
- confirmation, 1 jobs: 85.7945, 15.9519, 163.6227 MiB/s.
- confirmation, 2 jobs: 10.7005, 7.5782, 7.5430 MiB/s.
- confirmation, 4 jobs: 8.9674, 9.7544, 8.2915 MiB/s.
