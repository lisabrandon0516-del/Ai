# Retail Rivals

A supercenter you run one day at a time. You start with a riverside floor or an online counter selling groceries and everything else, and you grow it only as far as the drawer, the staff, and the block will allow.

Morning opens on the sales overview: yesterday's tape, what is on the shelf, who is on the floor, and the notes waiting for an answer. The desk is where orders, prices, shifts, ads, and nights get decided. Evening is the tape: sales, who carried the day, and what broke.

## Play

Python 3.11 or newer.

On Windows, unzip the folder and double-click `Play.bat`. The first launch installs the desk, then the window opens. Later launches start straight away.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m open_late
```

Saves live in `~/.open_late/saves.sqlite`. The game writes one whenever you change the day. Set `OPEN_LATE_DB` to keep a save file somewhere else.

The writing is the register tape: staff notes, customer flags, supplier offers, and what an event did to the drawer. Produce, meat and dairy, and bakery have a shelf life. Near expiry they mark down; at expiry they are written off as shrink.

## The desk

- Urgent notes have to be answered before the day can close.
- Supplier orders leave the drawer when you place them, unless that supplier has opened net 14. The credit line does not pay suppliers and does not cover a terms bill. It covers a bad Sunday, at 2% a week.
- Each person gets one assignment, including a training shift that does not sell. A raise sticks. Loyalty slips after a review date passes. Limits are on the card. Scheduling past a limit is allowed, and you will read about it later.
- Sunday takes rent, the gross wage, time and a half past eight hours, 7.65% employer tax, insurance, utilities, the sales tax you collected, and interest. Each person's card has a direct-deposit advice. Social Security, Medicare, federal income tax, state tax, and county tax come out of the gross. The drawer still pays the full gross. A profitable quarter also pays 21% income tax that day. Two Sundays in a row that do not clear ends the lease.
- Sales tax is 8% on top of the price. It sits in the drawer until Sunday, and it is not profit. Cards take 2.6% of the charge.
- Clothing is stocked as a size run. A customer who does not find their size leaves. Supplier orders add freight, and a long shipment can arrive with a damaged piece. Perishables follow a shorter clock than the 28-day markdown.
- Books is the quarter and the balance sheet: cash, inventory, prepaid orders, fixtures, tax held, payables, and owner draws. Operations is hours, coverage, and aging stock. Market is the other shop, the mailing list, and the quarter marks.
- Eight open hours is straight time. Longer hours bring more people, overtime, and more burnout on the floor. Fixtures depreciate over five years.
- Neighborhood trust and destination traffic move separately. They bring different customers, different ads, and different neighbors. A strong week puts Northline Market in your traffic, and they price against the department they push.

A careful shop can hold a month. A second door, a warehouse, or a house label is there when the cash and the reputation are.

## The office

Start as the corporate office when you want more than one city. You own the leases, the warehouse, and the payroll. Dana Ruiz runs the Evansville floor, and she writes that schedule. You set the planogram, the ads, which truck leaves Evansville, and the deals with the houses.

The other leases are Seattle, Houston, Las Vegas, and Naperville. They are not the same store. Seattle's wage floor is higher, Washington takes no state income tax, and a schedule change after Monday owes predictability pay. Houston takes no state income tax. Las Vegas is a late tourist street, quiet on Monday and busy Friday and Saturday, and the long shift pays overtime. The Naperville lease keeps the pharmacy counter off the floor, and Illinois withholds 4.95%. Sales tax is collected at the city's rate and sent on Sunday. It is not profit.

Signing a lease starts the rent that Sunday. The door does not sell during zoning and build-out: Houston 10 days, Las Vegas 8, Naperville 16, Seattle 18. You can hire, set the wall, and ship into that window.

Orders land in the Evansville warehouse. A store does not call the factory. A truck is on the road for a day to Evansville's own door, two days to Naperville, four to Houston, five to Las Vegas, and six to Seattle. A haul longer than two days arrives short. The store only holds what the planogram can face, plus a back room, and the rest comes back to the warehouse. Replenish covers a number of weeks of what that door sold in the last seven days.

The labor budget is the floor payroll, not the manager's salary. On Monday the manager keeps the strongest sellers that fit in the budget and posts that roster for the week. Someone left off it is not paid.

A house stays on list price until the chain has two doors or $1,200 with that house. The next deal is 4% off the sheet and net 30, and co-op accrues at 10% of what you buy. Four doors, or $4,000 with the house, is 8% off and 25% co-op. A better tier keeps the balance you have already earned. You claim it when an ad runs. Stock that has sat 28 days is marked down 20%, once. Sunday scores each door's contribution after cost, shrink, labor, rent, and freight.

## Tests

```bash
pytest
```
