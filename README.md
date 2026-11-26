# odoo-network

A Claude Code skill for your side of Odoo's **Network Management** app, from
the terminal:

- **Hours.** Log them on the right contract, at the times you say, with a
  work description drafted from your day's git history. Read what you logged
  and what is missing, and fix it.
- **Refunds.** Claim an expense the company pays back: the agent reads the
  receipt, fills the request, attaches the file and submits it to the
  approver. Then it tells you where each request stands.

The Odoo installs this was built on serve no MCP endpoint, so the skill
talks to Odoo's JSON-2 API with a personal API key. It needs **Odoo 19 or
later**; for an older Odoo, use the tag `xmlrpc`, the last version over
XML-RPC (hours only). Stdlib Python 3.9+, nothing to install (Windows needs
`pip install tzdata` for the time zone). Runs on macOS, Linux and Windows;
only where the key is stored differs.

**Compatibility.** The script works with two models of the Network Management
app: `timesheet_entry` (contracts, accounts, principals) and `refund_request`
(through its submit wizard). It does not drive the standard Odoo Timesheets
(`account.analytic.line`) or Expenses (`hr.expense`) apps.

## Install

```bash
git clone <this repo>
cp -r odoo-network-skill/odoo-network ~/.claude/skills/odoo-network
```

Then follow [`odoo-network/SETUP.md`](odoo-network/SETUP.md): where your
Odoo is, the company VPN, and your API key. The agent reads the same file
when the key stops working.

**Coming from `odoo-hours`?** Replace `~/.claude/skills/odoo-hours` with the
new folder. Your key and `~/.config/odoo-hours/config` keep working; rename
the folder to `~/.config/odoo-network` when you like.

## Make it yours

Open `~/.claude/skills/odoo-network/SKILL.md` and edit the section
**Your rules**: your standard day, how your monthly target works, which
repos map to which contract, how you like descriptions written, your usual
approver and cost centers for refunds, and anything the agent should ask
about instead of fixing. The rest of the file is shared behaviour and should
not need changes. Your copy is local; this repo keeps the neutral version.

## Use

In any Claude Code session:

- "Log this week's hours on the Acme contract, 8 hours a day, 9 to 12 and
  13 to 18, one general description per day." The agent lists your
  contracts, reads your commits per day, drafts one plain description per
  block, shows you the plan, and writes after your ok.
- "Put 2 hours yesterday at 20:00 on research, prompt optimization."
- "How many hours do I have this month? How many are missing on research?"
- "The receipt in my Downloads is the train to the Acme workshop; claim it."
- "Where are my refunds? Has the October one been paid?"

### Example sessions

> **You:** log this week's hours on the Acme contract, 9 to 12 and 13 to 18, one plain description per block from what I committed
>
> **Claude:** Acme resolves to contract 1042 (Acme / Website Redesign). Monday to Wednesday already hold those blocks with a placeholder description, so this is an update, not new rows. From your commits:
>
> | Day | Block | Now | Proposed |
> |---|---|---|---|
> | Mon 26 | 09–12 | todo | Search results page |
> | Mon 26 | 13–18 | todo | Search filters and sorting |
> | Tue 27 | 09–12 | todo | Checkout form validation |
>
> Hours and contract unchanged. Say "ok" and I write the three, or correct any line first.
>
> **You:** ok
>
> **Claude:** Written and read back; the week now shows the descriptions above.

> **You:** the train receipt in my Downloads is for the Acme workshop, claim it
>
> **Claude:** `cp-ticket-1123.pdf`: rail operator, VAT number and QR code visible, 23 Nov, 42.30 €. Cost center: Acme / Website Redesign. Approver from your rules: Jane Doe. The plan:
>
> | Date | Amount | Cost center | Approver | Account | Receipt | Description |
> |---|---|---|---|---|---|---|
> | 2026-11-23 | 42.30 € | Website Redesign | Jane Doe | personal | cp-ticket-1123.pdf | Train Lisbon–Porto for the Acme workshop |
>
> Say "ok" and I submit it.
>
> **You:** ok
>
> **Claude:** Submitted as RR-0512, now waiting for Jane Doe's approval.

Or straight from the shell:

```bash
O=~/.claude/skills/odoo-network/scripts/odoo_network.py
python3 $O contracts
python3 $O list --from 2026-10-19 --to 2026-10-25
python3 $O month --month 2026-10
python3 $O add --contract acme --date 2026-10-28 --start 09:00 --end 12:00 --desc "Reading customer specification tables" --dry-run
python3 $O update <id> --desc "Product page performance"
python3 $O delete <id>

python3 $O refunds
python3 $O refund-options --search acme
python3 $O refund --date 2026-11-23 --amount 42.30 --cost-center acme --approver jane --desc "Train Lisbon–Porto for the Acme workshop" --file ~/Downloads/cp-ticket-1123.pdf --dry-run
python3 $O refund-file <id> ~/Downloads/receipt.pdf
```

Times are local (`ODOO_TZ`, default the computer's time zone). `add` refuses to
overlap an existing entry unless you pass `--force`, and `--dry-run` shows
what would be written without writing it.

## Good to know

- Hours: only `contract`, `work_description`, `start_time` and `end_time`
  are written; account, project and principal derive from the contract.
- `month` prints two references: the contract's monthly figure, and for a
  contract with a daily maximum, every weekday of the month at that figure;
  a contract active for part of the month shows its span instead. Which one
  applies to you is between you and whoever manages the account.
- Refunds go through the same wizard as the **New** button in Odoo. With a
  receipt the request goes straight to the approver; without one it stays in
  Draft until you attach it. The amount is in euros, what you paid. Your
  bank details stay in Odoo: the request only says personal or company
  account.
- The key is yours; the script never writes it anywhere. Revoke it in Odoo
  under Preferences → Account Security whenever you want.
