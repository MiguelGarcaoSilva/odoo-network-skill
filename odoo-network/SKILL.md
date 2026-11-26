---
name: odoo-network
description: The user's side of Odoo's Network Management app. Hours - log or fill timesheet entries on the right contract with descriptions drawn from the day's git history, read how many hours a contract has or is missing, correct or delete entries. Refunds - submit an expense for the company to pay back, with its receipt attached, and follow its state. Use whenever the user mentions Odoo, logging hours, the timesheet, an expense, a receipt to claim or a refund request.
allowed-tools: Bash(python3:*), Bash(git log:*), Bash(security add-generic-password:*)
---

# Odoo Network

Two models of Odoo's Network Management app (not the standard Timesheets or
Expenses apps): hours are rows of `timesheet_entry`, expenses are rows of
`refund_request`. `scripts/odoo_network.py` talks to the Odoo named in
`~/.config/odoo-network/config` over the JSON-2 API with the user's API key.

```bash
O=~/.claude/skills/odoo-network/scripts/odoo_network.py
# hours
python3 $O contracts                      # active contracts and their monthly hours
python3 $O list [--from D --to D]         # entries, default this week
python3 $O month [--month YYYY-MM]        # hours per contract against its figures
python3 $O update <id> --desc "..." --dry-run   # also --contract, --start, --end
python3 $O add --contract acme --date 2026-10-28 --start 09:00 --end 12:00 --desc "Search results page" --dry-run
python3 $O delete <id>
# refunds
python3 $O refunds [--from D --to D]      # your requests and their state
python3 $O refund-options [--search TEXT] # approvers, and cost centers matching TEXT
python3 $O refund --date 2026-11-26 --amount 36.80 --cost-center workshop --approver marta --desc "..." --file ~/Downloads/receipt.pdf --dry-run
python3 $O refund-file <id> ~/Downloads/receipt.pdf   # attach the receipt to a Draft request
```

Times on the command line are **local** (`ODOO_TZ`, else the computer's time
zone); the script converts to UTC, so pass them as the user says them.
`--contract` takes an id or a substring of the account, project or role of a
contract active on that date; `--cost-center` and `--approver` take an id or
a substring of the name. The script refuses anything ambiguous and prints the
candidates.

When the script is not configured yet, or Odoo refuses the key (revoked or
expired), walk the user through [SETUP.md](SETUP.md); the new key comes from
them. When the script cannot reach Odoo, ask the user to connect the company
VPN and retry with the same configuration.

## Reading hours

"How many hours this month / how many are missing" is `month`: hours per
contract against the contract's monthly figure and, for a contract with a
daily maximum, against every weekday of the month at that figure (full time).
A contract active for part of the month shows its span instead of a monthly
delta. Which figure counts is in "Your rules". "What did I log this week / on
day X" is `list` with a range. Answer with the figures, in a short table when
there is more than one contract.

## Logging hours

1. **Contracts.** Run `contracts`; ids change, so read them each time. Route
   work to a contract with the table in "Your rules".

2. **The range.** `list` the days the user named. The rows already there are
   the schedule: many people create their blocks ahead with a placeholder
   description. A row with a placeholder or generic description gets
   `update`; `add` is for a day with no rows, in the user's standard day.
   Rows outside the range stay as they are.

3. **Evidence.** Unless the user already said what they did, gather the
   day's work: `git log --all --author=<name> --since=<day 00:00>
   --until=<day 23:59> --format='%ad %s' --date=iso` in the repos listed in
   "Your rules", plus what the current session built. Several checkouts of
   one repo (worktrees, clones) repeat its log: count each commit once.

4. **Descriptions the client can read.** These lines may end up on an
   invoice, so write each one as a plain phrase the client's engineer
   understands without knowing the codebase: the part of the product worked
   on and what it now does, in everyday words, in the register of "Your
   rules". Internal names stay out: repo, branch, issue number, commit
   prefix, tool or model names. One theme per block. A block with no commits
   of its own (reading, meetings, work that landed later) carries the
   previous block's description: the work continued, the log just does not
   show it.

   **Example.** Commits: "feat(search): rank results by recency (#231)",
   "fix(search): empty query no longer 500s (#240)". Description: "Search
   results ranking and fixes".

5. **Times.** Use what the user gives (dates, start/end or a total). With
   only a total, split it into the blocks of their standard day and say so.
   Keep a block on one day.

6. **Plan, confirm, write.** Run every `update` and `add` with `--dry-run`
   and show one table: date, time range, hours, contract, description before
   and after. These rows feed invoices; wait for the user's ok, then run the
   same commands without `--dry-run`. Done when `list` of the range shows
   every row with a readable description, no placeholder left, and the user
   has seen that list.

## Refund requests

An expense the user paid for the company goes back to them through a refund
request. Its path: **Draft** (no receipt yet) → **Waiting for Expense
Approval** (the approver says yes or no) → **Waiting for Official Document
Approval** (finance checks the receipt) → waiting to be set for payment →
**Waiting for Payment** → **Paid**, or **Refused** at either check. A refused
request can be corrected and its receipt replaced.

1. **The receipt.** Read the file the user points at (PDF or image; the form
   takes `.pdf`, `.jpg`, `.jpeg`, `.png`). Take the date, the total and the
   supplier. Finance refuses a receipt whose date, supplier details with VAT
   number, or QR code are not visible, or that is unreadable: say so before
   submitting.
2. **The amount** is what the user paid, VAT included, in euros. For a
   receipt in another currency, ask what the card charged in euros; do not
   convert at a rate you looked up.
3. **Cost center and approver.** `refund-options --search <word>` lists the
   approvers and the cost centers; a cost center is the project the expense
   belongs to. Take them from "Your rules" or ask. Only the approvers that
   `refund-options` lists can be picked.
4. **Description.** What was bought, the period it covers, and what it was
   for, in a line finance understands: "GitHub Copilot subscription, 26 Nov to
   16 Dec, for the AI training workshop".
5. **Plan, confirm, submit.** Run `refund ... --dry-run` and show the line:
   date, amount, cost center, approver, bank account, receipt, description.
   This asks the company for money; wait for the user's ok, then run it
   without `--dry-run`. With `--file`, the request goes straight to the
   approver; without it, it stays in Draft until `refund-file` attaches the
   receipt. Done when `refunds` shows the request in its new state and the
   user has seen it.

"Where is my refund / what have I claimed" is `refunds`; it shows each
request's state and the payment date, paid or expected.

## Your rules (edit this section; it is yours)

Everything above is the same for everyone. What differs per person lives
here, and the agent reads it as fact. Replace the examples.

- **Standard day.** `09:00–12:00 and 13:00–18:00, 8 h`. "Log this week"
  means that schedule on every weekday of the range up to today; later
  dates only when I name them.
- **Monthly target.** `8 h on every weekday of the month.` Or: `The
  contract's monthly figure, no more.` Or: `Only the hours I actually
  worked; no target.` Whatever you agreed with your manager.
- **Repo → contract.** One row per repo family; add a row when a new repo
  appears.

  | Repos / work | Contract match |
  |---|---|
  | `~/Desktop/work/client-a-*`, client A meetings and demos | `client a` |
  | `~/Desktop/research-*`, research-team talks | `research` |

- **Description register.** `Plain English, 3–8 words.` Or point at a past
  week: `list --from ... --to ...` shows it.
- **Refunds.** `Bank account: personal. Approver: <name>. Cost center:
  the project of the work, e.g. "client a" for client A travel.`
- **Exceptions.** Anything the agent should ask about instead of fixing on
  its own, for example: `Rows on future dates are placeholders I keep on
  purpose; leave them. A month that does not match the target may be
  intended; ask before trimming or filling.`
