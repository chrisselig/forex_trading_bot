# Market Structure

## What Forex Is

Foreign exchange is the simultaneous buying of one currency and selling of another. When you buy EUR/USD at 1.0850, you are paying 1.0850 US dollars for 1 euro. If the price rises to 1.0900, your euro is now worth more dollars. That's your profit.

The forex market trades approximately $7.5 trillion per day. It is the largest, most liquid financial market on earth. It runs 24 hours a day, 5 days a week, from Sydney open on Monday to New York close on Friday.

## Who Moves Price

Understanding who is in the market tells you *why* price moves the way it does.

**Central banks** are the single most important participants. When the Federal Reserve raises interest rates, it increases demand for US dollars globally. Every institutional portfolio manager, sovereign wealth fund, and corporate treasurer must adjust. Central bank policy is the tide — everything else is waves.

**Commercial banks and dealers** (JP Morgan, Citi, Deutsche Bank, UBS) handle the majority of daily volume. They make markets for clients and trade proprietary flow. The interbank market — where these banks trade with each other — is where "real" price discovery happens.

**Institutional investors** — hedge funds, pension funds, sovereign wealth funds — trade forex for portfolio hedging and speculative positioning. A pension fund with European equity exposure needs to hedge EUR/USD. A macro hedge fund betting on diverging monetary policy between the US and Japan goes long USD/JPY.

**Corporations** move enormous size for non-speculative reasons. When Toyota repatriates US revenue back to yen, that's real flow. When Apple hedges its European sales, that's real flow. Corporate flow is often predictable around quarter-end.

**Retail traders** account for roughly 5% of daily volume. In isolation, retail flow is irrelevant to price. But retail matters in one way: retail traders are consistently on the wrong side of fast moves, and their stop losses provide liquidity for institutional entries.

## How Price Actually Moves

Price does not move because buyers outnumber sellers. Every transaction has a buyer and a seller. Price moves because of **aggression** — who is willing to pay more (or accept less) to get filled immediately.

The order book has two sides:

- **Bids** — resting buy orders below the current price
- **Asks (offers)** — resting sell orders above the current price

The **spread** is the gap between the best bid and best ask. In EUR/USD during London hours, this is typically 0.1-0.3 pips. In USD/ZAR during a news event, it can blow out to 50+ pips.

When a large market order hits, it eats through resting liquidity. If someone sells 500 million EUR/USD at market, they consume every bid on the book until enough resting orders have absorbed the flow. Price drops. The thinner the book (fewer resting orders), the more price moves per unit of flow.

**This is why news events create the largest moves.** Right before a data release, market makers pull their resting orders. They don't want to be on the wrong side of a number they haven't seen yet. The book becomes thin. When the data drops and directional flow hits a thin book, price moves fast and far.

## Currency Pair Mechanics

Every forex price is a ratio. EUR/USD = 1.0850 means 1 euro costs 1.0850 dollars.

- **Base currency** — the first one (EUR in EUR/USD). When the pair rises, the base is strengthening.
- **Quote currency** — the second one (USD in EUR/USD). When the pair rises, the quote is weakening.

This matters for interpreting news:

- Strong US jobs data = USD strength
- USD is the quote in GBP/USD → pair **falls** (USD strengthening = pair price drops)
- USD is the base in USD/CAD → pair **rises** (USD strengthening = pair price rises)

Getting this backwards is one of the most common errors in news trading. The bot handles this automatically through its direction logic.

## Sessions and Liquidity

The market runs continuously but liquidity concentrates in three sessions:

| Session | Hours (ET) | Characteristics |
|---------|-----------|-----------------|
| **Asian (Tokyo)** | 7 PM - 4 AM | Lowest volume. JPY pairs most active. Ranges. |
| **European (London)** | 3 AM - 12 PM | Highest volume. Most institutional flow. Trends begin. |
| **American (New York)** | 8 AM - 5 PM | Second highest volume. US data releases. Overlaps with London 8-12. |

The **London-New York overlap** (8 AM - 12 PM ET) is the most liquid window of the day. Not coincidentally, this is when the US government releases economic data. NFP drops at 8:30 AM ET. CPI drops at 8:30 AM ET. FOMC announcements come at 2:00 PM ET.

This bot trades exclusively during these windows.

## Pips

A **pip** is the standard unit of price change in forex.

- For most pairs: 1 pip = 0.0001 (EUR/USD moving from 1.0850 to 1.0851)
- For JPY pairs: 1 pip = 0.01 (USD/JPY moving from 150.00 to 150.01)

A 20-pip move in EUR/USD on a 100,000-unit position (1 standard lot) = $200. That same move on a 10,000-unit position (1 mini lot) = $20.

Pip value varies by pair and position size. The bot calculates this automatically based on your account equity and risk parameters.

## Leverage and Margin

Forex is traded on margin. You don't need $100,000 to control a $100,000 position.

In Canada, IIROC (the Investment Industry Regulatory Organization of Canada) caps leverage. Interactive Brokers enforces these limits automatically. You cannot over-leverage beyond what IIROC allows. This is a feature, not a limitation — leverage kills more retail traders than bad strategy ever will.

!!! warning "Leverage is not free money"
    If you control $100,000 with $5,000 in margin, a 5% adverse move wipes out your entire deposit. Leverage amplifies losses exactly as much as it amplifies gains. The bot limits risk to 1% of account equity per trade specifically because of this.

## Spreads as a Cost

Every trade starts at a loss equal to the spread. If EUR/USD has a 0.3-pip spread and you buy, you need the price to move 0.3 pips in your favor just to break even.

For major pairs (EUR/USD, GBP/USD) during London/New York hours, spreads are negligible — a fraction of a pip. For exotic pairs (USD/ZAR, USD/TRY), spreads are a meaningful cost and can blow out during events.

The bot enforces a maximum spread check before placing any trade. If the spread exceeds the configured limit, the trade is rejected. You do not want to enter a position when the spread has already consumed most of your profit target.
