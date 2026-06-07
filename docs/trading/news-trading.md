# News Trading

## Why News Events Are the Edge

Most of what happens in the forex market is noise. Price oscillates within ranges driven by flow, positioning, and technical levels. It is extremely difficult to extract consistent profit from this noise.

Economic data releases are different. They are **scheduled information shocks**. At a known time, a number is published that changes the market's assessment of a country's economy. The market reprices — quickly, violently, and in a direction that is often predictable from the data.

This is the edge: the market's reaction to surprise is systematic. A strong jobs number strengthens the dollar. A hot inflation print raises rate expectations. A dovish Fed weakens the dollar. These are not opinions — they are mechanical relationships driven by how institutional money is managed.

The bot exists to exploit this narrow, repeatable edge.

## The Anatomy of a News Move

Here's what happens around a major release, second by second:

**T-60 minutes**: Liquidity is normal. Traders are positioning based on expectations. Some hedge, some speculate. There is a published forecast — the consensus of economists surveyed by news agencies.

**T-5 minutes**: Market makers begin widening spreads. Some pull liquidity from the book entirely. Volatility compresses as participants wait. This is the quiet before the event.

**T-0 (release)**: The number hits. Within 50-200 milliseconds, institutional algorithms parse the headline and fire orders. The first 500ms of price action is dominated by machine speed — no human can compete here, and you should not try.

**T+1 to T+5 seconds**: The initial spike. Price moves 10-50+ pips in the direction implied by the data. The order book is thin. Stops get swept. Retail traders who were positioned wrong get liquidated, adding fuel to the move.

**T+5 seconds to T+2 minutes**: The reaction to the reaction. Traders read beyond the headline. Was the revision to last month significant? Were the details (wage growth, participation rate) consistent with the headline? If yes, the move extends. If no, it can partially reverse.

**T+2 to T+30 minutes**: Follow-through or fade. Strong surprises with consistent details tend to see continuation. Weak surprises or mixed data see the initial move fade. This is where the trend for the next several hours is established.

**T+30 minutes to T+4 hours**: Institutional rebalancing. Portfolio managers adjust hedges. Corporate treasurers update forward contracts. The move often accelerates again during this window as real money flow kicks in.

## What Makes a Good News Trade

Three conditions must exist:

**1. Surprise magnitude matters, not direction alone.**
An NFP print of +250K when the forecast was +200K is a +25% surprise. The market was already priced for +200K. The *surprise* — the +50K gap — is what moves price. A print of +200K when the forecast was +200K moves nothing, even though the number itself is strong.

**2. The release must be high-impact.**
Not all economic data matters equally. NFP, CPI, and FOMC are in a different tier from durable goods or trade balance. The bot only trades events that have historically produced significant price reactions.

**3. Liquidity must be sufficient.**
Trading USD/TRY during a surprise NFP can be profitable, but the spread may be 30-50 pips. If your take profit is 40 pips, spread alone puts you underwater before the trade starts. The bot's spread check exists for exactly this reason.

## Why Most Traders Fail at News Trading

**They try to predict the number.** You cannot consistently predict NFP better than the consensus of hundreds of professional economists. Do not try. The straddle strategy avoids this entirely — it profits from the *size* of the move, not the direction.

**They enter too early.** Placing a market order at T+0 means getting filled during maximum spread and maximum slippage. The bot's straddle places orders *before* the event with defined entry points. The surprise strategy waits 5 seconds — long enough for the initial spike to establish direction, short enough to capture the follow-through.

**They use too much leverage.** A 30-pip stop loss on a position that risks 10% of your account is one bad trade from disaster. News events are inherently volatile. The bot caps risk at 1% per trade. This means a losing streak of 10 consecutive trades loses 10% — survivable and recoverable.

**They hold through reversals.** The initial spike direction is wrong about 20-30% of the time. Without a stop loss, a 20-pip initial move against you can become 100 pips. The bot always has a stop loss. Always.

## The Events That Matter

Not all economic releases are created equal. These are the ones that consistently produce tradeable moves:

### Tier 1: Market-Moving

| Event | Release | Why It Matters |
|-------|---------|----------------|
| **Non-Farm Payrolls (NFP)** | Monthly, first Friday, 8:30 AM ET | The single most important data release. Shows net job creation. Directly influences Fed policy expectations. Average move: 40-80+ pips on major pairs. |
| **CPI (Consumer Price Index)** | Monthly, ~10th-15th, 8:30 AM ET | The primary inflation gauge. Hot CPI = higher rates = stronger USD. Has been as market-moving as NFP during high-inflation regimes (2022-2024). |
| **FOMC Rate Decision** | 8x/year, 2:00 PM ET | The Fed's actual interest rate decision + forward guidance. The statement and press conference can produce multiple waves of price action over 90+ minutes. |

### Tier 2: Significant

| Event | Release | Why It Matters |
|-------|---------|----------------|
| **GDP** | Quarterly, 8:30 AM ET | Broadest measure of economic health. Large surprises move markets, but the quarterly frequency means fewer opportunities. |
| **Unemployment Rate** | Monthly (with NFP) | Reported alongside NFP. An inverse indicator — higher is bad for USD. Can override a strong NFP headline if it jumps unexpectedly. |
| **ISM Manufacturing PMI** | Monthly, first business day, 10:00 AM ET | Leading indicator. Above 50 = expansion, below 50 = contraction. The dividing line at 50 creates binary reactions. |

### Tier 3: Supportive

| Event | Release | Why It Matters |
|-------|---------|----------------|
| **Retail Sales** | Monthly, 8:30 AM ET | Consumer spending is ~70% of US GDP. A proxy for economic momentum. |
| **PPI (Producer Price Index)** | Monthly, 8:30 AM ET | Wholesale inflation. Leading indicator for CPI. Markets react when PPI diverges from CPI expectations. |
| **Jobless Claims** | Weekly, Thursday, 8:30 AM ET | High frequency but lower impact per release. Useful for confirming trends in the labor market. |

The bot is configured to trade all of these. The straddle strategy captures moves from any of them. The surprise strategy only triggers when the actual data diverges significantly from the forecast.
