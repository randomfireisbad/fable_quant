# Model Assumptions & Parameter Audit

Every tunable constant in the platform, what justifies it, and how bias is
controlled. Maintained because tuning constants until outputs "look right" is
exactly how directional bias enters quant models.

## Principles

Direction-affecting parameters must be either symmetric (cannot favor buy or
sell), benchmark-relative (centered on the market, not on zero), or
literature-defaulted (taken from a published result, not chosen by feel).
Discretionary weightings are set to 1/N following DeMiguel, Garlappi & Uppal
(2009, RFS), who show naive equal weighting is extremely hard to beat out of
sample. When evidence justified a directional adjustment in one place (e.g.
regime-dependent momentum, Cooper-Gutierrez-Hameed 2004), we report the
information but do not act on it with made-up magnitudes.

## Parameter table

| Parameter | Value | Status | Justification |
|---|---|---|---|
| Composite model weights | 0.25 each | 1/N | DeMiguel et al. 2009; no evidence basis for unequal weights |
| Momentum leg weights (TSMOM t, 12-1 sign, relative 12-1 sign) | equal | 1/N | same |
| Mean-reversion evidence weights (ADF vs VR) | 0.5 / 0.5 | 1/N | same |
| Sharpe baseline in vol score | SPY's Sharpe, same window | benchmark-relative | removes market-direction bias; falls back to 0.4 (long-run US equity Sharpe) |
| Momentum 12-1 construction | skip most recent month | literature | Jegadeesh & Titman 1993 |
| TSMOM lookback | 252d | literature | Moskowitz-Ooi-Pedersen 2012 |
| GARCH spec | GJR(1,1)-t, fallback GARCH-normal, EWMA(0.94) | literature | GJR 1993 leverage effect; Hansen-Lunde 2005; RiskMetrics |
| Drift shrinkage | 35% sample / 65% CAPM prior | discretionary, conservative | direction-neutral (shrinks toward prior, not toward buy); motivated by Merton 1980 but the 35/65 split is a judgment call |
| Equity risk premium (CAPM prior) | 5% | convention | within the 4-6% range of long-run estimates (e.g. Damodaran's surveys) |
| Risk-free rate | 4% | approximation | should ideally track current T-bills |
| Rating bins | ±0.15, ±0.45 | discretionary, symmetric | symmetric around 0 → cannot favor a direction |
| tanh squash scales (/2, /1.5) | — | discretionary, symmetric | monotone, odd functions; affect magnitude, never direction |
| Agreement shrinkage (1 − 0.55·dispersion, floor 0.45) | — | discretionary, neutral | only ever shrinks toward Hold |
| Bootstrap | 2000 sims, 5d blocks | convention | Politis-Romano 1994; results insensitive to block 3-10 |
| Backtest costs | 5bp per turnover | convention | retail-commission-free era estimate of spread+impact for liquid names |
| Vol target (sizing) | 15% | convention | common institutional target; affects size, not direction |
| Market regime (SPY vs 200d SMA) | informational only | neutralized | Cooper et al. 2004 justify caution, not a specific reweighting — so we display it and change nothing |
| Multibagger screen points | various | discretionary | long-only screen by design (3-10x search is inherently directional); treat as a filter, not a signal |

## Feedback-loop policy (model improvements from trade outcomes)

Trades record the model's signals at entry; `quant/performance.py` attributes
closed round trips by rating/score/source. Rules for acting on this evidence:

1. No parameter changes below n = 30 closed round trips in the relevant
   bucket; prefer n ≥ 100. The review reports binomial confidence intervals —
   if the CI spans 50%, a "pattern" in win rates is noise.
2. Changes must move parameters between the categories in the table above
   (e.g. discretionary → literature/benchmark-relative), or be supported by
   the accumulated outcome evidence — never "this constant felt too low."
3. Every change is recorded in the improvement log (data/improvement_log.json)
   with observation, change, and evidence. No silent tuning.
4. Beware feedback bias: outcomes come from trades the models themselves
   suggested, so the sample is selected. Attribution can validate or refute
   the signals that fired; it says nothing about the ones that didn't.

## Known residual biases

Survivorship: yfinance shows today's listings; backtests on delisted names are
impossible here. Look-ahead: avoided in walk-forward signals (1-day lag) but
the GARCH/regression diagnostics shown are full-sample fits. Small sample:
1-5y windows; t-stats and p-values are reported so you can see how weak the
evidence usually is. Selection: you choose the tickers — analyzing only names
you already like is itself a bias no model corrects.
