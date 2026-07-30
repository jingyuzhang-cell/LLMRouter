# advanced_v2: program safety + end-to-end E5

## Rescue concentration

| Model | Train rescues | Top enriched operations |
|---|---:|---|
| qwen-3b-local | 400 | VerifyStr (2.93x), Count (2.42x), Or (2.14x), VerifyNum (2.10x), VerifyDate (2.06x) |
| deepseek | 451 | Or (2.85x), VerifyNum (2.36x), VerifyStr (2.34x), Count (2.30x), VerifyDate (1.83x) |
| qwen | 387 | Count (2.31x), Or (2.15x), VerifyDate (2.13x), QFilterDate (1.90x), FilterYear (1.82x) |
| zhipu | 398 | Count (2.50x), VerifyDate (2.07x), VerifyStr (2.06x), Or (1.97x), FilterYear (1.60x) |

## Program-group confidence gate

- Eligible group/model pairs: 0
- Test accuracy: 75.47%
- Test downgrades: 0

## End-to-end E5 nested CV

- OOF accuracy: 75.37%
- OOF Gemini: 75.36%
- OOF rescues/harms/3x utility: 3/2/-3
- Test accuracy: 75.47%
- Test Gemini: 75.47%
- Accepted: False
- Production policy: always_gemini

## True-label expansion estimate

- KQAPro train questions: 94,376
- Count/Or/Verify targeted pool: 18,747
- Recommended first pilot: 2,000 questions × 5 models = 10,000 evaluations (8,000 external API + 2,000 local)
- Larger round: 10,000 questions × 5 models = 50,000 evaluations (40,000 external API + 10,000 local)
- No paid expansion was started without explicit approval.
