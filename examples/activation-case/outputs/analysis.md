# Synthetic experiment summary

> Synthetic demonstration only. This is not evidence about real customers or a launch recommendation.

Users: 1200; A/B allocation: 626 / 574.

## Metrics (B minus A)

| Metric | A | B | Absolute difference | 95% interval for difference |
|---|---:|---:|---:|---:|
| Primary: activation within 24h | 37.5% (n=626) | 42.9% (n=574) | +5.3 п.п. | [-0.2 п.п., +10.8 п.п.] |
| Secondary: returned on day 7 | 27.8% (n=626) | 27.0% (n=574) | -0.8 п.п. | [-5.8 п.п., +4.3 п.п.] |
| Guardrail: support contact within 7d | 5.6% (n=626) | 7.8% (n=574) | +2.2 п.п. | [-0.6 п.п., +5.2 п.п.] |
| Guardrail: refund within 30d | 1.6% (n=626) | 2.1% (n=574) | +0.5 п.п. | [-1.1 п.п., +2.2 п.п.] |

## Funnel

| Step | Unique users | Share of all | From previous step |
|---|---:|---:|---:|
| app_open | 1200 | 100.0% | n/a |
| view_offer | 1014 | 84.5% | 84.5% |
| start_activation | 795 | 66.2% | 78.4% |
| activation_success | 481 | 40.1% | 60.5% |

## Mechanical gate: `not_eligible_under_demo_rule`

Mechanical synthetic-data gate only; never an automatic ship/no-ship decision.

Approximate sample planning: about 4146 users per arm for a 3.0 п.п. absolute primary effect at 80% power and two-sided 5% alpha; this rough estimate is not a substitute for a production design review.

The AI assistant must explain limitations, compare strategic options, and leave the decision to a person. See `knowledge/metrics-and-inference.md`.
