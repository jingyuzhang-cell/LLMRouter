# E0 minimal effective pool (stratified-180, single-generation labels)

## overall (n=180)
full-6 oracle 0.9333; marginal oracle pp: reasoning +3.89, medium +1.67, large +0.56, small +0.00, coder +0.00, math +0.00

| pool | oracle | gap pp | best single |
|---|---|---|---|
| reasoning | 0.8500 | 0.00 | reasoning (0.8500) |
| large+reasoning | 0.9000 | 5.00 | reasoning (0.8500) |
| medium+large+reasoning | 0.9278 | 7.78 | reasoning (0.8500) |
| large+math+reasoning | 0.9111 | 6.11 | reasoning (0.8500) |
| small+large+reasoning | 0.9000 | 5.00 | reasoning (0.8500) |
| large+coder+reasoning | 0.9111 | 6.11 | reasoning (0.8500) |
| small+medium+large+coder+math+reasoning | 0.9333 | 8.33 | reasoning (0.8500) |
| greedy path | reasoning (0.8500) -> reasoning+medium (0.9111) -> reasoning+medium+large (0.9278) -> reasoning+medium+large+coder (0.9333) -> reasoning+medium+large+coder+small (0.9333) -> reasoning+medium+large+coder+small+math (0.9333) | | |

minimal pools: 95pct: medium+reasoning oracle 0.9111; 99pct: medium+large+reasoning oracle 0.9278; 100pct: medium+large+coder+reasoning oracle 0.9333

## knowledge (n=60)
full-6 oracle 0.8667; marginal oracle pp: reasoning +8.33, medium +3.33, large +1.67, small +0.00, coder +0.00, math +0.00

| pool | oracle | gap pp | best single |
|---|---|---|---|
| reasoning | 0.7000 | 0.00 | reasoning (0.7000) |
| large+reasoning | 0.8167 | 11.67 | reasoning (0.7000) |
| medium+large+reasoning | 0.8500 | 15.00 | reasoning (0.7000) |
| large+math+reasoning | 0.8333 | 13.33 | reasoning (0.7000) |
| small+large+reasoning | 0.8167 | 11.67 | reasoning (0.7000) |
| large+coder+reasoning | 0.8333 | 13.33 | reasoning (0.7000) |
| small+medium+large+coder+math+reasoning | 0.8667 | 16.67 | reasoning (0.7000) |
| greedy path | reasoning (0.7000) -> reasoning+large (0.8167) -> reasoning+large+medium (0.8500) -> reasoning+large+medium+coder (0.8667) -> reasoning+large+medium+coder+small (0.8667) -> reasoning+large+medium+coder+small+math (0.8667) | | |

minimal pools: 95pct: medium+large+reasoning oracle 0.8500; 99pct: medium+large+coder+reasoning oracle 0.8667; 100pct: medium+large+coder+reasoning oracle 0.8667

## math (n=60)
full-6 oracle 1.0000; marginal oracle pp: small +0.00, medium +0.00, large +0.00, coder +0.00, math +0.00, reasoning +0.00

| pool | oracle | gap pp | best single |
|---|---|---|---|
| reasoning | 0.9500 | 0.00 | reasoning (0.9500) |
| large+reasoning | 0.9833 | 1.67 | large (0.9667) |
| medium+large+reasoning | 1.0000 | 3.33 | large (0.9667) |
| large+math+reasoning | 1.0000 | 3.33 | large (0.9667) |
| small+large+reasoning | 0.9833 | 1.67 | large (0.9667) |
| large+coder+reasoning | 0.9833 | 1.67 | large (0.9667) |
| small+medium+large+coder+math+reasoning | 1.0000 | 3.33 | large (0.9667) |
| greedy path | large (0.9667) -> large+math (1.0000) -> large+math+small (1.0000) -> large+math+small+medium (1.0000) -> large+math+small+medium+coder (1.0000) -> large+math+small+medium+coder+reasoning (1.0000) | | |

minimal pools: 95pct: medium oracle 0.9500; 99pct: medium+math oracle 1.0000; 100pct: medium+math oracle 1.0000

## code (n=60)
full-6 oracle 0.9333; marginal oracle pp: reasoning +3.33, medium +1.67, small +0.00, large +0.00, coder +0.00, math +0.00

| pool | oracle | gap pp | best single |
|---|---|---|---|
| reasoning | 0.9000 | 0.00 | reasoning (0.9000) |
| large+reasoning | 0.9000 | 0.00 | reasoning (0.9000) |
| medium+large+reasoning | 0.9333 | 3.33 | reasoning (0.9000) |
| large+math+reasoning | 0.9000 | 0.00 | reasoning (0.9000) |
| small+large+reasoning | 0.9000 | 0.00 | reasoning (0.9000) |
| large+coder+reasoning | 0.9167 | 1.67 | reasoning (0.9000) |
| small+medium+large+coder+math+reasoning | 0.9333 | 3.33 | reasoning (0.9000) |
| greedy path | reasoning (0.9000) -> reasoning+medium (0.9333) -> reasoning+medium+small (0.9333) -> reasoning+medium+small+large (0.9333) -> reasoning+medium+small+large+coder (0.9333) -> reasoning+medium+small+large+coder+math (0.9333) | | |

minimal pools: 95pct: reasoning oracle 0.9000; 99pct: medium+reasoning oracle 0.9333; 100pct: medium+reasoning oracle 0.9333

