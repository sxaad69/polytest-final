# Market Tape Research Roadmap

## Objective
Identify the high-probability "winning patterns" for 5-minute binary crypto markets on Polymarket by analyzing raw high-fidelity tick data (Dashcam).

---

## The 7 Core Hypotheses

### 1. The Opening Bias
**Hypothesis**: The initial price discovery moment (first 10 seconds of a market opening) has strong predictive power for the final resolution.
*   *Question*: If a market opens at >0.60, does it resolve YES significantly more often than random?

### 2. Binance Lead-Time Lag
**Hypothesis**: Polymarket is a "lagging indicator" of Binance. There is a measurable 5-15 second window where Binance momentum has spiked but Polymarket has not yet repriced.
*   *Question*: Can we quantify the exact millisecond lag between a Binance momentum shift and a Polymarket price shift?

### 3. Pre-Resolution Drift
**Hypothesis**: The final 90 seconds of a market exhibit a "directional drift" toward the final resolution value (0 or 1) that is more predictable than the middle of the window.
*   *Question*: Does a steady price climb in the final 90 seconds have a >70% win rate for YES?

### 4. Flat-Then-Spike (Coiled Spring)
**Hypothesis**: Markets that remain in a tight horizontal range (e.g., 0.45-0.55) for the first 3 minutes are "coiling." The direction of the first major breakout from that range predicts the final outcome.
*   *Question*: Is a breakout from a flat period more reliable than momentum alone?

### 5. Mean Reversion vs. Momentum Continuation
**Hypothesis**: Price spikes in the first 2 minutes are either "overshoots" (Mean Reversion) or "valid breakouts" (Continuation).
*   *Question*: Can we use Binance momentum direction to filter which spikes are fake and which are real?

### 6. Tick Frequency (Smart Money Detection)
**Hypothesis**: A sudden surge in the number of ticks per second (regardless of price movement) indicates institutional or "informed" liquidity entering the book.
*   *Question*: Does high-frequency activity precede major price moves?

### 7. Empty Book Transition
**Hypothesis**: The moment a market transitions from "Empty" (Bid 0, Ask 1) to "Populated" (Tight Bid/Ask) contains the purest signal of fair value.
*   *Question*: Is the direction of the FIRST populated book predictive?

---

## Priority Order for Testing
We will test these based on ease of measurement vs. expected alpha impact:

1.  **Opening Bias** (Easiest to compute, immediate baseline).
2.  **Binance Lead-Time Lag** (The most directly actionable "arbitrage" edge).
3.  **Pre-Resolution Drift** (Identifies the last-minute entry signal).
4.  **Flat-Then-Spike** (High-conviction "Coiled Spring" entries).
5.  **Mean Reversion vs. Continuation** (Filters out noisy spikes).
6.  **Tick Frequency** (High-fidelity volume analysis).
7.  **Empty Book Transition** (Structural liquidity analysis).
