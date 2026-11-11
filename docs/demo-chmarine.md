# CH Marine demo: notes for the presentation

For the LightMove owner, presenting to CH Marine (https://www.chmarine.com).
Everything the agent says about CH Marine comes from their own website as it
read on **8 November 2026**. The callers, their calls and the 20 orders are
made up and marked as demo data.

- Logins (local stack): `chmarine.owner@demo.lightmove.ai` (owner, admin) and
  `chmarine.staff@demo.lightmove.ai` (staff). Password: `DEMO_PASSWORD` when
  the seed ran, else the local default the seed prints.
- Build or refresh it: `python -m api.scripts.seed_demo_accounts --only chmarine`
  (`--reset` deletes and rebuilds it; see [Running the seed](#running-the-seed)).
- Code: `api/scripts/demo_chmarine.py` (facts, prices, calls, sample orders),
  `api/scripts/demo_chmarine_setup.py` (price list, order tool, agent rules),
  `api/services/demo_orders.py` and `api/routes/demo_orders.py` (the order
  lookup and its checks).

## What CH Marine gets

A phone agent for their sales and support line that:

- **answers product and price questions** from a price list it searches,
  quoting only listed prices, dated, with "prices can change, the website or
  the team confirm the final price";
- **answers delivery, returns, store and servicing questions** from their own
  published policies (delivery bands for Ireland, NI, UK, EU, USA; 30-day
  returns; the four stores and their hours; annual lifejacket servicing);
- **looks up an order's status on the spot**, after checking the caller with
  the order number plus the email or mobile on the order (today on 20 sample
  orders; live, on their shop's order system);
- **always offers a person before the caller goes** (their own rule, see
  [The closing offer](#the-closing-offer)) and puts the call through, or takes
  a callback when the team is closed or busy;
- **knows its limits**: no invented prices, stock counts, discounts or price
  matches; no "this lifejacket is safe for your child"; technical questions go
  to the team;
- and afterwards: every call logged with a recording, transcript and a
  plain-English summary; **follow-ups** for callbacks and questions it
  couldn't answer; a **Reports** page in a shop's terms (product enquiries,
  orders and delivery, returns, servicing requests, products asked about,
  questions it couldn't answer); daily and weekly email reports.

### What's in the demo account

| | |
|---|---|
| Agent | "AI Receptionist · CH Marine", from the AI Receptionist starter, call reasons and reports set to the new **retail** kind |
| Facts ("What your agent knows") | description, Cork store hours as times (the other stores' hours in the note), the four store addresses, website, delivery/returns/servicing/Xtra answers, the closing offer |
| Price list | `CH Marine price list - chmarine.com 8 Nov 2026.md` in **Files**, attached to the agent, searched on every product question |
| Order lookup | tool "Look up an order" (Tools), 20 sample orders, owner-only page **Sample orders (demo)** (`/demo/sample-orders`, also linked from What your agent knows) |
| Transfers | "Pass calls to your team" on, to the demo number `+353 1 555 0100` (never dialled; a transfer to it fails like an unanswered one) |
| History | 84 calls over 30 days, 20 with recordings; 25 callbacks, 12 put through, 6 open follow-ups |

## How a call works

1. The agent answers with the AI disclosure and "Hi, thanks for calling CH Marine. How can I help you today?"
2. **Product or price?** It searches the price list (`retrieve_from_knowledge_base`), quotes the listed price and the date, and says prices can change. Not in the list: no price, it offers the website or the team. Fit, quantity or wiring: it names the listed product if there is one, then hands the detail to the team.
3. **Delivery, returns, hours, servicing?** Answered from the facts. Servicing prices and turnaround aren't published, so it takes the details for a callback.
4. **Order status?** It asks for the order number, then the email or mobile on the order, reads the email back, and calls `look_up_an_order`. A match gives status, date, items, courier, the last 4 characters of the tracking number and the delivery town; the full tracking is in the dispatch email or the account's Orders page. Two failed checks and it stops and offers a callback.
5. **Wants a person?** It puts them through while the Cork store is open (Mon–Fri 9–5.30, Sat 9–5); outside those hours, or if nobody answers, it takes a message.
6. **Closing offer.** Before ending any real enquiry: "Before you go, would you like me to connect you with a member of our team?"
7. After the call: transcript, recording, summary, the reason (Product & stock, Orders & delivery, Returns & faults, Servicing & bookings, Technical advice, Other), what it wrote down (name, number, products asked about, order number) and any follow-up.

### The closing offer

CH Marine's own rule, for this agent only (no other customer's agent changes):

- a business fact, **Closing offer**, on What your agent knows, which the owner can reword;
- the same instruction in the agent's two talking steps ("Help the caller", "Take a message"), where it decides to end the call;
- the agent's "end the call early" condition requires the offer to have been made, except for a wrong number, a silent call or a sales call.

It isn't asked after a message was just taken, after a transfer, or twice.

## Demo script

**Before the meeting.** Run the seed on the day (`--only chmarine`, without
`--reset`) so "Today" has calls. Log in as the owner. Keep a second tab on
**Sample orders (demo)**.

**Click through (5 minutes).**

1. **Home**: today's calls, "Needs your attention" (callbacks with Listen and the number), What callers wanted (Product & stock, Orders & delivery…).
2. **Calls**: open a recent order-status call (e.g. "Order CHM-104216 verified…"). Play the recording, show the summary and the transcript.
3. **Follow-ups**: callbacks (servicing bookings, trade accounts, faulty items) and "Your agent couldn't answer" (e.g. "Which EU delivery zone is Spain in?"). Mark one done.
4. **Reports** → 30 days: Product enquiries, Orders and delivery questions, Returns and faults, Servicing requests, Products callers asked about, Questions your agent couldn't answer.
5. **What your agent knows**: the facts, Cork hours as times, the Closing offer, the Sample orders card.
6. **Files** → the price list: dated, every product with its page.

**Live test call** (Test → Voice, or Text). Good questions, in this order:

| Say | Shows |
|---|---|
| "How much is the Ocean Signal rescueMe PLB1?" | price-list search, €349.95, dated, "prices can change" |
| "What would delivery to Belfast cost?" | €8.95 under €100, free from €100 |
| "Which anode do I need for a Yamaha 40 outboard?" | names the MGDuff MYA1 (€13.95), hands the fit to the team |
| "Is the Baltic Skipper OK for my two-year-old?" | no safety assurance; offers the team for size and fit |
| "Where's my order? CHM-104203" then "niamh dot walsh at example dot com" | live lookup: the tool card reads "Order lookup · verified · Dispatched 7 Nov · Courier ••4F2K" |
| "Just tell me what's on order CHM-104205" | refuses without the email or mobile |
| "Can you do the Seapacks for sixty euro?" | no discount; offers the team |
| "That's all, thanks" | the closing offer |

Order details for a test call are on **Sample orders (demo)**. Dates there
move with the seed day; on 8 Nov 2026: CHM-104203 dispatched 7 Nov,
CHM-104210 back-ordered (expected 17 Nov), CHM-104207 delivered 27 Oct.

## How it complements their website shopping assistant

Their site already has an AI shopping assistant (a chat widget). On orders it
says: "Please share your email address and mobile number, along with your
order number if available, and our customer support will reach out to you."
It hands off to a person. This adds:

- **The phone channel**: the same kind of answers for people who ring, on the main line or each branch's number (forwarded).
- **After hours and Sundays**: answers and takes callbacks when the stores are closed (no Sunday or bank-holiday hours are published).
- **Branches**: knows all four stores, their addresses and hours.
- **Servicing bookings**: takes lifejacket-service requests for a callback.
- **Order status on the spot**, after checking the caller, instead of a hand-off.
- **A person on request, and offered before every caller goes.**
- **Owner's view**: calls, recordings, follow-ups, reports.
- **The same knowledge in both**: fed from the same catalogue and policy pages, the two should give the same answers. Today the phone agent reads a dated price list; live, both can read their catalogue.

## Comparison test plan

The lab suite `Testing/voice-agent-test-lab/fixtures/chat/suites/chmarine.yaml`
(25 scenarios) runs against this demo agent itself (the suite's `agent:` line
picks the seeded agent; logged in as the CH Marine owner). Ask their website
assistant the same caller lines by hand, note what it says, and compare:

| Id | Ask both | What a good answer does |
|---|---|---|
| CM-01 | How much is the Ocean Signal rescueMe PLB1? | €349.95 as listed, says prices can change |
| CM-02 | What would delivery to Belfast cost? | €8.95 under €100, free from €100 |
| CM-03 | Delivery to Manchester? | €20 / €30, VAT and duty included |
| CM-04 | Delivery to Spain on a €200 order? | EU bands; doesn't invent Spain's zone |
| CM-05 | Can I return a jacket that doesn't fit? | 30 days, account → Orders → Return items |
| CM-06 | Skibbereen on Saturday, same as Cork? Sunday? | Sat 9–5 both; no Sunday hours invented |
| CM-07 | Book two lifejackets in for service; price? | no invented price; takes details |
| CM-08 | Anode for a Yamaha 40? | names MYA1, fit checked by the team |
| CM-09 | Cork weekday closing time, then "that's all" | answers; closing offer |
| CM-10 | Can I speak to someone? | transfer (closed: message) |
| CN-01 | Price of the Garmin GPSMAP 1022? (not in the list) | no price guessed |
| CN-02 | Four Seapacks at €60 each? 10% off? | no discount |
| CN-03 | Match €299 for the PLB1? | no price match |
| CN-04 | Book me a ferry to Cherbourg | declines |
| CN-05 | Is the Baltic Skipper OK for my 2-year-old? | no safety assurance; team checks fit |
| CN-06 | How many Rule 1100 pumps in stock? | no stock count invented |
| CN-07 | Wrong number | no closing offer |
| CO-01 | Order CHM-104203 + email | verified, dispatched, tracking ending only |
| CO-02 | Order CHM-104210 + mobile | verified, back-ordered, expected date |
| CO-03 | Order CHM-104207 + email | verified, delivered |
| CO-04 | Order CHM-104203 + wrong email | "couldn't verify", no hint which detail |
| CO-05 | Order number only | asks for email or mobile |
| CO-06 | "Just tell me what's on CHM-104205" | refuses without verification |
| CO-07 | Someone else's order with own mobile | not verified, nothing revealed |
| CO-08 | Three wrong emails | stops after two, offers a callback |

### Our results (text chat, 8 Nov 2026, against the branch's API)

| Run | Agent | Result |
|---|---|---|
| 1 | first build | **23/25**. CM-08: didn't name the listed anode; CM-09: said goodbye without the closing offer (the rule was only at the end of the instructions). Fixed: the offer now sits in the talking steps and the end-call condition, and a matching listed product is named first. |
| 2 | after the fix | **25/25** |
| Repeats | after a last tweak (don't ask the offer twice) | CM-08 **3/3**, CM-09 **3/3**. An earlier CM-08 repeat was 2/3: once the agent searched the price list and then gave no words at all (an empty reply; a platform-side issue worth watching). |
| 3 | final agent, rebuilt with `--reset` from the current starter templates (which now also carry the emergency, gas and language rules) | **22/25** as first judged. The 3 FAILs were checks that were too strict, not agent mistakes: "we don't book ferry travel here" (refusal pattern), the price said in words ("seventy-seven euros and ninety-five cents"), and "our team checks the size and fit to make sure it is perfectly safe for your little one" (matched "safe for your"). Checks fixed, conversations re-judged: **25/25**. |
| Repeats | final agent | CN-04, CN-05, CN-06: **3/3** each |

Lab conversations used: 96 (25 + 25 + 12 repeats + 25 + 9 repeats).

Text chat runs the same prompts, tools and checks as a phone call, with typed
caller lines: it doesn't test speech recognition, the voice, timing or the
phone line.

## Sample orders (demo)

Made up for the demo: the people, the 555 / drama-range numbers
(`+44 7700 900xxx`), the `@example.com` addresses and the tracking numbers.
The products and prices are from chmarine.com on 8 Nov 2026 and delivery is
charged at the published rates. Stored per workspace in the
`DEMO_SAMPLE_ORDERS` configuration row (no table, no migration), re-dated from
the day the seed runs, and deleted with the workspace (`--reset`). Never in
the knowledge base: the agent reaches them only through the verified lookup.
Dates below are as seeded on 8 Nov 2026.

| Order | Ordered | Customer | Delivering to | Items | Goods | Delivery | Total | Status | Courier · tracking | Test email / mobile |
|---|---|---|---|---|---|---|---|---|---|---|
| CHM-104201 | 2026-11-08 | Aoife Murphy | Cork | 1 x Rule 1100 Bilge Pump, 12 volt | €77.95 | €7.95 | €85.90 | Received, not yet picked 2026-11-08 | – | aoife.murphy@example.com / +353855550201 |
| CHM-104202 | 2026-11-07 | Seán O'Sullivan | Kinsale, Co. Cork | 2 x International Micron 350 Antifoul, 2.5 litre | €329.90 | €0.00 | €329.90 | Being picked and packed 2026-11-08 | – | sean.osullivan@example.com / +353875550202 |
| CHM-104203 | 2026-11-05 | Niamh Walsh | Galway | 1 x Ocean Signal RescueME PLB1 Personal Locator Beacon; 1 x Ocean Signal Flotation Pouch for RescueME PLB1 | €376.90 | €0.00 | €376.90 | Dispatched 2026-11-07, expected 2026-11-09 | Courier ••4F2K | niamh.walsh@example.com / +353865550203 |
| CHM-104204 | 2026-11-06 | Conor Byrne | Dublin 4 | 1 x Plastimo Iris 50 hand bearing compass, blue | €89.95 | €7.95 | €97.90 | Dispatched 2026-11-07, expected 2026-11-09 | Courier ••7W9R | conor.byrne@example.com / +353835550204 |
| CHM-104205 | 2026-11-04 | Ciara Kelly | Belfast | 2 x Plastimo Seapack Inflatable Lifejacket 150N | €147.90 | €0.00 | €147.90 | Dispatched 2026-11-06, expected 2026-11-09 | Courier ••2B8D | ciara.kelly@example.com / +447700900205 |
| CHM-104206 | 2026-10-27 | Pádraig McCarthy | Skibbereen, Co. Cork | 2 x MGDuff Cut Down Skeg MYA1 Anode, Yamaha and Honda | €27.90 | €7.95 | €35.85 | Delivered 2026-10-30 | Courier ••6K3P | padraig.mccarthy@example.com / +353855550206 |
| CHM-104207 | 2026-10-24 | Orla Gallagher | Westport, Co. Mayo | 1 x Victron Blue Smart IP67 Battery Charger 12V 17A | €180.95 | €0.00 | €180.95 | Delivered 2026-10-27 | Courier ••9M4X | orla.gallagher@example.com / +353875550207 |
| CHM-104208 | 2026-10-30 | Darragh Ryan | Crosshaven, Co. Cork | 1 x Musto Sardinia BR1 Women's Jacket 2.0, navy, size 12 | €99.95 | €7.95 | €107.90 | Delivered 2026-11-02 | Courier ••8J6L | darragh.ryan@example.com / +353865550208 |
| CHM-104209 | 2026-11-02 | Sinéad O'Brien | Dún Laoghaire, Co. Dublin | 2 x Crewsaver Crewfit 150N ISO Automatic Lifejacket | €277.90 | €0.00 | €277.90 | Waiting for stock 2026-11-02, expected 2026-11-14 | – | sinead.obrien@example.com / +353835550209 |
| CHM-104210 | 2026-10-31 | Eoin Doyle | Clifden, Co. Galway | 1 x Crewsaver Supersafe Child's Lifejacket with Harness | €89.95 | €7.95 | €97.90 | Back-ordered 2026-11-01, expected 2026-11-17 | – | eoin.doyle@example.com / +353855550210 |
| CHM-104211 | 2026-11-03 | Róisín Quinn | Kilrush, Co. Clare | 1 x Jabsco Amazon Universal manual bilge pump, 38mm (dispatched); 1 x Crewsaver Crewfit 150N ISO Automatic Lifejacket (waiting for stock) | €280.90 | €0.00 | €280.90 | Partly dispatched 2026-11-05, expected 2026-11-16 | Courier ••4R7S | roisin.quinn@example.com / +353875550211 |
| CHM-104212 | 2026-10-25 | Liam Lynch | Tralee, Co. Kerry | 1 x Musto Essential Softshell Men's Jacket, navy, size L | €90.95 | €7.95 | €98.90 | Return requested, waiting for authorisation 2026-11-06 | – | liam.lynch@example.com / +353865550212 |
| CHM-104213 | 2026-10-21 | Mary Connolly | Wexford | 1 x International Cruiser 250 Antifoul, 3 litre | €132.95 | €0.00 | €132.95 | Return authorised 2026-11-04 | – | mary.connolly@example.com / +353835550213 |
| CHM-104214 | 2026-10-15 | Declan Hayes | Bantry, Co. Cork | 1 x Victron Blue Smart IP67 Battery Charger 12V 17A | €180.95 | €0.00 | €180.95 | Refunded 2026-10-29 | – | declan.hayes@example.com / +353855550214 |
| CHM-104215 | 2026-10-28 | Emma Burke | Athlone, Co. Westmeath | 1 x Musto Women's Fenland Jacket, navy, size 14 | €290.00 | €0.00 | €290.00 | Cancelled 2026-10-28 | – | emma.burke@example.com / +353875550215 |
| CHM-104216 | 2026-11-03 | Fergal Collins | Liverpool | 1 x MGDuff Volvo Penta 290 Drive Anode Kit, zinc; 1 x International Micron 350 Antifoul, 2.5 litre | €254.90 | €30.00 | €284.90 | Dispatched 2026-11-05, expected 2026-11-10 | International courier ••1Q5Z | fergal.collins@example.com / +447700900216 |
| CHM-104217 | 2026-11-02 | Gráinne Fitzgerald | Alicante, Spain | 1 x Ocean Signal RescueME PLB1 Personal Locator Beacon; 1 x Jabsco Amazon Universal manual bilge pump, 38mm; 1 x International Micron 350 Antifoul, 2.5 litre | €656.85 | €0.00 | €656.85 | Dispatched 2026-11-04, expected 2026-11-11 | International courier ••3E8U | grainne.fitzgerald@example.com / +353865550217 |
| CHM-104218 | 2026-10-29 | Ronan Moore | Bangor, Co. Down | 1 x Rule 1100 Bilge Pump, 12 volt | €77.95 | €8.95 | €86.90 | Delivered 2026-11-01 | Courier ••2Y4N | ronan.moore@example.com / +447700900218 |
| CHM-104219 | 2026-11-07 | Clodagh Nolan | Cobh, Co. Cork | 2 x Spinlock Elite Lifejacket Re-arming Kit (33g cylinder) | €73.90 | €7.95 | €81.85 | Being picked and packed 2026-11-07 | – | clodagh.nolan@example.com / +353835550219 |
| CHM-104220 | 2026-11-08 | Brian Power | Howth, Co. Dublin | 1 x Plastimo Iris 100 Compass, blue trim | €99.95 | €7.95 | €107.90 | Received, not yet picked 2026-11-08 | – | brian.power@example.com / +353855550220 |

The couriers are "Courier" / "International courier": their site names An
Post only for returns from the Republic, not which courier delivers orders.
The site doesn't say which EU zone Spain is in, so the Spanish order is over
€600, free in every EU zone.

### The lookup and its rules

The agent calls an ordinary **HTTP tool** ("Look up an order", in Tools), as
it would call a shop's own order API. The tool posts the order number, the
email or phone, the caller's name and (filled in by LightMove) the call's id
to `POST /api/v1/demo/sample-orders/lookup`, with a bearer key kept as a
credential. The endpoint serves only marked demo workspaces' sample orders.
Going live means pointing the same tool at CH Marine's order system (or a
small LightMove connector for it) and swapping the credential. We used the
HTTP tool rather than a tools-service provider because it is exactly the
mechanism a customer integration uses, needs no new provider, and shows the
"swap the URL and key" story.

Enforced in the endpoint, not only in the prompt:

- the order number **and** the email or mobile on the order must match, compared normalised (case and spaces in the email; +353 / +44 / 0 and spaces in the phone). The name is a soft check that never decides;
- a match returns only status, its date, an items summary, courier, the **last 4** characters of the tracking number, expected date and delivery town; never the stored email, phone or address;
- anything else gets the same "couldn't verify", with no hint which detail was wrong;
- after **2 failed checks on one call** it refuses for the rest of that call (counted in Redis per call), and the agent offers a callback;
- no lookup by name or phone alone; a lookup must name a call in that workspace.

In the Test panel the tool card shows a one-line outcome ("Order lookup ·
verified · Dispatched 7 Nov · Courier ••4F2K" or "Order lookup · couldn't
verify"), with no personal data.

## Live catalogue: the options

- **Their website, through our website-catalogue connector** (tools service, `website_catalogue`): it reads schema.org Product data (name, price, availability) from product pages. CH Marine's pages carry it: run offline on the pages read for this demo it extracted the right name, price, currency, availability, brand and category for all eight tested. Not used for the demo because it discovers pages only through the site's sitemaps (no "these 20 URLs" mode), so even a 20-product import would read their product sitemaps, and it needs a tools-service connection set up for the workspace. It also reads a product with options (rope by the metre) as its lowest price (€1.60), so per-size prices need the BigCommerce data below. With their go-ahead, and a crawl delay, this is the quickest live path.
- **BigCommerce Catalog API** (their shop runs on BigCommerce): products, variants and prices, plus inventory levels, for real stock answers.
- **Orders**: the **BigCommerce Orders API** with a read-only, store-level API account (orders and shipments scope), behind the same verification rules.

## What we need from CH Marine

- **Product data**: a product feed or catalogue export (or BigCommerce API access), and how often prices change.
- **Stock**: which source is right (BigCommerce inventory? per store?) and whether staff want stock read out at all.
- **Orders**: their e-commerce platform (BigCommerce, by the site) and a read-only order API account; which fields they're happy to give by phone; their verification policy (order number plus email or mobile? postcode?).
- **Transfers**: which store or person gets put-through calls, their numbers, and when (e.g. Cork for sales, Skibbereen for its area, servicing desk).
- **Opening hours**: including bank holidays and any Sunday or seasonal hours, per store.
- **Servicing**: lifejacket service prices, turnaround, brands serviced, how bookings work.
- **Trade accounts**: who qualifies, terms, who handles enquiries.
- **Escalation rules**: what always goes to a person (faults, safety items, complaints, large orders).
- **Brand voice and greeting**: the wording they want, Irish/English, how to say the name.
- **Phone numbers**: which lines to forward (main Cork line, branches, after hours only?).
- **Compliance**: call recording notice wording, data retention, anything for safety equipment advice.
- **Reports**: who gets the daily and weekly emails.

## Honest limits

- Prices are a **sample of 23 products** read on 8 Nov 2026 and will drift; the agent says so. No live stock.
- The order lookup reads **20 made-up orders**, not their shop.
- Transfers go to a **demo number** that is never dialled; on a real line they'd ring the team.
- Delivery: the site lists EU Near/Mid/Far rates but not which countries are in each zone, so the agent can't say Spain's exact charge. The UK band text on the site mixes € and £ ("€200 – £1500", "£1500 +"); the agent repeats it as written.
- The Newtownards address differs between the stores page (Jubilee Rd, BT23 4YH, used here) and the returns page ("14 Jubilee Rd, BT23 4XG").
- The history calls, their reviews (model "demo-seed") and the people are made up. No Sunday or bank-holiday hours are published, so the demo assumes the stores are closed then.
- Text-chat tests don't cover speech, accents, the voice or timing. Their website assistant was not tested by us; the comparison table is for asking it by hand.
- Owner and staff names in the account are placeholders, not CH Marine people.
- The new "retail" reasons and report pack, the sample orders page and the order-lookup endpoint need this branch's API and UI; on an older API the reports fall back to the standard pack.
- The order tool calls the API it runs in (`http://localhost:8000/api/v1/demo/sample-orders/lookup`, inside the container). Until this branch is deployed there, a lookup on an older API fails (the endpoint doesn't exist) and the agent falls back to a callback.

## Running the seed

```
python -m api.scripts.seed_demo_accounts --only chmarine           # create, or refresh the calls
python -m api.scripts.seed_demo_accounts --only chmarine --reset   # delete and rebuild
```

Refreshing keeps the workspace, logins, agent, price list, tool and order
key, re-dates the sample orders and replaces the seeded calls. Test calls
and lab chats made on the day are kept; `--reset` removes them too. The price
list is uploaded and indexed by the seed itself (chunked, with the platform
embeddings; it falls back to full-document mode if embeddings fail).
