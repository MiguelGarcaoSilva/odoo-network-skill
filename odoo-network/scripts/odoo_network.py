#!/usr/bin/env python3
"""Your side of Odoo's Network Management app: hours (timesheet entries) and refund requests.

Stdlib only. Talks to Odoo's JSON-2 API (Odoo 19 or later). Times on the command line are
local (ODOO_TZ, else the computer's zone); Odoo stores UTC.

Configuration, from the environment or from ~/.config/odoo-network/config (KEY=value lines;
the old ~/.config/odoo-hours/config still works):
  ODOO_URL      your Odoo address, e.g. https://erp.example.com   (required)
  ODOO_DB       the database name; only needed when the server does not pick one by itself
  ODOO_TZ       your time zone, e.g. Europe/Paris; default the computer's (required on Windows)
  ODOO_API_KEY  your API key
      macOS: it can come from the keychain item `odoo-api-key` instead
             (security add-generic-password -a <your e-mail> -s odoo-api-key -w <key> -U)
      Linux / Windows: put it in the config file and chmod 600 it

Needs Python 3.9+; on Windows also `pip install tzdata` for the time zone.

  contracts                      your active contracts (id, account, project, role, monthly hours)
  list [--from D] [--to D]       entries in a date range (default: this week)
  month [--month YYYY-MM]        hours per contract this month vs the contract's figures
  add --contract C --date D --start HH:MM (--end HH:MM | --hours H) --desc TEXT [--dry-run] [--force]
  update ID [--desc TEXT] [--contract C] [--start HH:MM] [--end HH:MM] [--dry-run]
  delete ID [ID ...]

Refund requests (expenses the company pays back):
  refunds [--from D] [--to D]    your refund requests and their state (default: all)
  refund-options [--search TEXT] the approvers, and the active cost centers matching TEXT
  refund --date D --amount EUR --cost-center C --approver A --desc TEXT [--file PATH]
         [--account personal|company] [--dry-run]
                                 submit one request; without --file it stays in Draft
  refund-file ID PATH [--dry-run] attach the document to a request still in Draft or Refused

`--contract` takes an id or a substring of the account / project / role of an
active contract (e.g. "acme"). One call = one entry, so a wrong line is one line.
`--cost-center` and `--approver` take an id or a substring of the name, the same way.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

CONFIG = os.path.expanduser("~/.config/odoo-network/config")
if not os.path.exists(CONFIG) and os.path.exists(os.path.expanduser("~/.config/odoo-hours/config")):
    CONFIG = os.path.expanduser("~/.config/odoo-hours/config")  # the name before the rename


def setting(name: str, default: str = "") -> str:
    """ODOO_* from the environment, else from the config file (KEY=value lines)."""
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    try:
        for line in open(CONFIG):
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip():
                return v.strip().strip("'\"")
    except OSError:
        pass
    return default


URL = setting("ODOO_URL").rstrip("/")
if not URL:
    sys.exit(f"set ODOO_URL (your Odoo address), in the environment or as a KEY=value line in {CONFIG}")
DB = setting("ODOO_DB")  # empty: the server picks its database


def local_zone() -> ZoneInfo:
    """ODOO_TZ if set; else the zone /etc/localtime links to; else ask for ODOO_TZ."""
    name = setting("ODOO_TZ")
    if not name:
        path = os.path.realpath("/etc/localtime")
        if "zoneinfo/" not in path:
            sys.exit(f"cannot tell your time zone; set ODOO_TZ (e.g. Europe/Paris) in the environment or {CONFIG}")
        name = path.rsplit("zoneinfo/", 1)[1]
    return ZoneInfo(name)


TZ = local_zone()
ENTRY_FIELDS = ["start_time", "end_time", "duration_h", "contract", "work_description", "account", "project"]


# ---------------------------------------------------------------- connection
def api_key() -> str:
    """The API key: environment, else the macOS keychain item, else the config file."""
    key = os.environ.get("ODOO_API_KEY", "").strip()
    if not key and sys.platform == "darwin":
        try:
            key = subprocess.run(["security", "find-generic-password", "-s", "odoo-api-key", "-w"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if not key:
        key = setting("ODOO_API_KEY")
        if key and os.path.exists(CONFIG) and os.name != "nt" and os.stat(CONFIG).st_mode & 0o077:
            print(f"warning: {CONFIG} holds your API key and is readable by others; chmod 600 it", file=sys.stderr)
    if not key:
        sys.exit("no API key: set ODOO_API_KEY in the environment, or\n"
                 f"  macOS:  security add-generic-password -a <your e-mail> -s odoo-api-key -w <key> -U\n"
                 f"  other:  an ODOO_API_KEY=... line in {CONFIG} (chmod 600)")
    return key


class OdooError(Exception):
    pass


class Odoo:
    def __init__(self) -> None:
        self.headers = {"Authorization": f"bearer {api_key()}", "Content-Type": "application/json"}
        if DB:
            self.headers["X-Odoo-Database"] = DB
        self.uid = self.call("res.users", "context_get")["uid"]

    def call(self, model: str, method: str, **params):
        """POST /json/2/<model>/<method>; every argument is named (record ids go as `ids`)."""
        req = urllib.request.Request(f"{URL}/json/2/{model}/{method}", data=json.dumps(params).encode(),
                                     headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("message", "")
            except ValueError:
                msg = ""
            if e.code == 401:
                sys.exit(f"Odoo refused the API key (revoked or expired?): {msg or e.reason}")
            raise OdooError(f"{e.code} {msg or e.reason}") from None


# ---------------------------------------------------------------- time helpers
def to_utc(day: dt.date, hhmm: str) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), tzinfo=TZ).astimezone(dt.timezone.utc)


def odoo_str(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def from_odoo(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).astimezone(TZ)


def parse_date(s: str | None) -> dt.date:
    if not s or s == "today":
        return dt.date.today()
    if s == "yesterday":
        return dt.date.today() - dt.timedelta(days=1)
    return dt.date.fromisoformat(s)


def weekdays(lo: dt.date, hi: dt.date) -> int:
    return sum(1 for i in range(max(0, (hi - lo).days + 1)) if (lo + dt.timedelta(i)).weekday() < 5)


# ---------------------------------------------------------------- contracts
def active_contracts(o: Odoo, on: dt.date | None = None) -> list[dict]:
    on = on or dt.date.today()
    rows = o.call(
        "contract", "search_read",
        domain=[["network_member.user", "=", o.uid], ["active", "=", True],
                ["start_date", "<=", on.isoformat()], ["end_date", ">=", on.isoformat()]],
        fields=["account", "project", "job_role", "start_date", "end_date", "monthly_hours", "maximum_daily_hours"],
        order="start_date desc",
    )
    for r in rows:
        r["label"] = f"{r['account'][1]} / {r['project'][1]}"
    return rows


def resolve_contract(o: Odoo, spec: str, on: dt.date) -> dict:
    rows = active_contracts(o, on)
    if spec.isdigit():
        hits = [r for r in rows if r["id"] == int(spec)]
    else:
        s = spec.lower()
        hits = [r for r in rows if s in (r["label"] + " " + r["job_role"][1]).lower()]
    if len(hits) == 1:
        return hits[0]
    names = "\n".join(f"  {r['id']}  {r['label']}  ({r['start_date']} to {r['end_date']})" for r in rows)
    kind = "no active contract matches" if not hits else "ambiguous contract"
    sys.exit(f"{kind} {spec!r} on {on}. Active contracts:\n{names}")


# ---------------------------------------------------------------- commands
def cmd_contracts(o: Odoo, a) -> None:
    for r in active_contracts(o, parse_date(a.date)):
        print(f"{r['id']}  {r['label']}  | {r['job_role'][1]}  | {r['start_date']} to {r['end_date']}"
              f"  | {r['monthly_hours']} h/month, max {r['maximum_daily_hours']:g} h/day")


def entries_between(o: Odoo, start: dt.date, end: dt.date) -> list[dict]:
    lo = odoo_str(to_utc(start, "00:00"))
    hi = odoo_str(to_utc(end + dt.timedelta(days=1), "00:00"))
    return o.call(
        "timesheet_entry", "search_read",
        domain=[["network_member_user_id", "=", o.uid], ["start_time", ">=", lo], ["start_time", "<", hi]],
        fields=ENTRY_FIELDS, order="start_time asc",
    )


def print_entries(rows: list[dict]) -> None:
    total = 0.0
    for e in rows:
        s, t = from_odoo(e["start_time"]), from_odoo(e["end_time"])
        total += e["duration_h"]
        print(f"{e['id']}  {s:%Y-%m-%d %a} {s:%H:%M}-{t:%H:%M}  {e['duration_h']:5.2f} h  "
              f"[{e['contract'][0]}] {e['account'][1] if e['account'] else '?'}  | {e['work_description'] or ''}")
    print(f"total {total:.2f} h over {len(rows)} entries")


def cmd_list(o: Odoo, a) -> None:
    today = dt.date.today()
    start = parse_date(a.frm) if a.frm else today - dt.timedelta(days=today.weekday())
    end = parse_date(a.to) if a.to else today
    print_entries(entries_between(o, start, end))


def cmd_month(o: Odoo, a) -> None:
    first = dt.date.fromisoformat(a.month + "-01") if a.month else dt.date.today().replace(day=1)
    last = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    rows = entries_between(o, first, last)
    by: dict[int, float] = {}
    for e in rows:
        by[e["contract"][0]] = by.get(e["contract"][0], 0.0) + e["duration_h"]
    contracts = {r["id"]: r for r in active_contracts(o, first) + active_contracts(o, last)}
    today = dt.date.today()

    def figures(c: dict, hours: float) -> str:
        # Two references: the contract's monthly figure, and for a contract with a
        # daily maximum, every weekday of the month at that figure ("full time").
        # Which one your contract is measured against is between you and the account.
        lo = max(first, dt.date.fromisoformat(c["start_date"]))
        hi = min(last, dt.date.fromisoformat(c["end_date"]))
        # A contract active for part of the month has no monthly delta: show its span.
        if (lo, hi) == (first, last):
            out = f" / {c['monthly_hours']} h contract ({hours - c['monthly_hours']:+.1f})"
        else:
            out = f" / {c['monthly_hours']} h contract, active {lo:%m-%d} to {hi:%m-%d} only"
        if c["maximum_daily_hours"]:
            full = weekdays(lo, hi) * c["maximum_daily_hours"]
            due = weekdays(lo, min(hi, today)) * c["maximum_daily_hours"]
            out += f"; {full:.0f} h full time ({hours - full:+.1f}), {due:.0f} h due to date"
        return out

    for cid in sorted(set(by) | set(contracts)):
        c, hours = contracts.get(cid), by.get(cid, 0.0)
        label = c["label"] if c else f"contract {cid}"
        print(f"{cid}  {label}: {hours:.2f} h{figures(c, hours) if c else ''}")
    print(f"{first:%B %Y}: {sum(by.values()):.2f} h total")


def cmd_add(o: Odoo, a) -> None:
    day = parse_date(a.date)
    contract = resolve_contract(o, a.contract, day)
    start = to_utc(day, a.start)
    if a.end:
        end = to_utc(day, a.end)
    elif a.hours:
        end = start + dt.timedelta(hours=a.hours)
    else:
        sys.exit("give --end HH:MM or --hours H")
    if end <= start:
        sys.exit("end is not after start")
    hours = (end - start).total_seconds() / 3600
    same_day = entries_between(o, day, day)
    clash = [e for e in same_day
             if from_odoo(e["start_time"]) < end.astimezone(TZ) and from_odoo(e["end_time"]) > start.astimezone(TZ)]
    day_total = sum(e["duration_h"] for e in same_day if e["contract"][0] == contract["id"]) + hours
    plan = (f"{day:%Y-%m-%d %a} {start.astimezone(TZ):%H:%M}-{end.astimezone(TZ):%H:%M}  {hours:.2f} h  "
            f"[{contract['id']}] {contract['label']}  | {a.desc}")
    print(("DRY RUN  " if a.dry_run else "ADD      ") + plan)
    if clash:
        print("overlaps an existing entry:")
        print_entries(clash)
        if not a.force:
            sys.exit("refused; pass --force to log it anyway")
    if contract["maximum_daily_hours"] and day_total > contract["maximum_daily_hours"]:
        print(f"warning: {day_total:.2f} h on {day} exceeds the contract's {contract['maximum_daily_hours']:g} h/day")
    if a.dry_run:
        return
    [new] = o.call("timesheet_entry", "create", vals_list=[{
        "contract": contract["id"], "work_description": a.desc,
        "start_time": odoo_str(start), "end_time": odoo_str(end),
    }])
    back = o.call("timesheet_entry", "read", ids=[new], fields=ENTRY_FIELDS)[0]
    print(f"created {new}: {back['duration_h']:.2f} h on {back['account'][1] if back['account'] else '?'} / "
          f"{back['project'][1] if back['project'] else '?'}")


def cmd_update(o: Odoo, a) -> None:
    before = o.call("timesheet_entry", "read", ids=[a.id], fields=ENTRY_FIELDS)[0]
    day = from_odoo(before["start_time"]).date()
    vals: dict = {}
    if a.desc is not None:
        vals["work_description"] = a.desc
    if a.contract:
        vals["contract"] = resolve_contract(o, a.contract, day)["id"]
    if a.start:
        vals["start_time"] = odoo_str(to_utc(day, a.start))
    if a.end:
        vals["end_time"] = odoo_str(to_utc(day, a.end))
    if not vals:
        sys.exit("nothing to change: give --desc, --contract, --start or --end")
    print("before:"); print_entries([before])
    if a.dry_run:
        print("DRY RUN would write", vals); return
    o.call("timesheet_entry", "write", ids=[a.id], values=vals)  # this model names it `values`
    print("after:"); print_entries(o.call("timesheet_entry", "read", ids=[a.id], fields=ENTRY_FIELDS))


def cmd_delete(o: Odoo, a) -> None:
    rows = o.call("timesheet_entry", "read", ids=a.ids, fields=ENTRY_FIELDS)
    print_entries(rows)
    o.call("timesheet_entry", "unlink", ids=a.ids)
    print(f"deleted {len(rows)}")


# ---------------------------------------------------------------- refund requests
# `refund_request` of the same app. The web form cannot create one: its "New" opens
# `refund_request_wizard`, and the wizard's `action_submit` makes the request. With a
# document it goes to the approver; without one it stays in Draft.
REFUND_FIELDS = ["reference", "document_date", "gross_total", "currency_id", "cost_center", "approver",
                 "expense_description", "payment_bank_account_type", "state", "file_name",
                 "estimated_payment_date", "payment_date"]
DOC_TYPES = (".pdf", ".jpg", ".jpeg", ".png")  # what the form accepts


def pick(rows: list[dict], spec: str, kind: str) -> dict:
    """One row by id, exact name, or a unique substring of display_name; else list the candidates."""
    if spec.isdigit():
        hits = [r for r in rows if r["id"] == int(spec)]
    else:
        s = spec.lower()
        hits = [r for r in rows if r["display_name"].lower() == s] or \
               [r for r in rows if s in r["display_name"].lower()]
    if len(hits) == 1:
        return hits[0]
    shown = hits or rows
    names = "\n".join(f"  {r['id']}  {r['display_name']}" for r in shown[:40])
    more = f"\n  ... {len(shown) - 40} more" if len(shown) > 40 else ""
    sys.exit(f"{'ambiguous' if hits else 'no'} {kind} matching {spec!r}. Candidates:\n{names}{more}")


def cost_centers(o: Odoo) -> list[dict]:
    return o.call("project", "search_read", domain=[["active", "=", True]],
                  fields=["display_name", "account_name"], order="name asc")


def approvers(o: Odoo) -> list[dict]:
    return o.call("refund_request_approver", "search_read", domain=[], fields=["display_name"])


def read_doc(path: str) -> tuple[str, str]:
    """(file name, base64 content) of a receipt the form would accept."""
    path = os.path.expanduser(path)
    if not path.lower().endswith(DOC_TYPES):
        sys.exit(f"{path}: the form takes {', '.join(DOC_TYPES)} only")
    with open(path, "rb") as f:
        return os.path.basename(path), base64.b64encode(f.read()).decode()


def print_refunds(rows: list[dict]) -> None:
    for r in rows:
        name = lambda f: r[f][1] if r[f] else "-"
        due = r["payment_date"] or r["estimated_payment_date"]
        print(f"{r['id']}  {r['reference']}  {r['document_date']}  {r['gross_total']:8.2f} {name('currency_id')}  "
              f"{r['state']}  | {name('cost_center')}  | approver {name('approver')}  | "
              f"{r['file_name'] or 'no document'}{f'  | paid/due {due}' if due else ''}"
              f"  | {(r['expense_description'] or '').strip()}")


def cmd_refunds(o: Odoo, a) -> None:
    dom: list = [["network_member_user_id", "=", o.uid]]
    if a.frm:
        dom.append(["document_date", ">=", parse_date(a.frm).isoformat()])
    if a.to:
        dom.append(["document_date", "<=", parse_date(a.to).isoformat()])
    rows = o.call("refund_request", "search_read", domain=dom, fields=REFUND_FIELDS, order="id desc")
    print_refunds(rows)
    print(f"{len(rows)} requests, {sum(r['gross_total'] for r in rows):.2f} total")


def cmd_refund_options(o: Odoo, a) -> None:
    print("approvers:")
    for r in approvers(o):
        print(f"  {r['id']}  {r['display_name']}")
    s = (a.search or "").lower()
    print("cost centers" + (f" matching {a.search!r}" if s else "") + ":")
    for r in cost_centers(o):
        if s in (r["display_name"] + " " + (r["account_name"] or "")).lower():
            print(f"  {r['id']}  {r['display_name']}  | {r['account_name'] or '-'}")


def cmd_refund(o: Odoo, a) -> None:
    day = parse_date(a.date)
    if a.amount <= 0:
        sys.exit("--amount must be positive")
    cc = pick(cost_centers(o), a.cost_center, "cost center")
    ap = pick(approvers(o), a.approver, "approver")
    doc = read_doc(a.file) if a.file else None
    print(("DRY RUN  " if a.dry_run else "SUBMIT   ") +
          f"{day}  {a.amount:.2f}  | {cc['display_name']} ({cc['account_name'] or '-'})  | approver {ap['display_name']}"
          f"  | {a.account} account  | {doc[0] if doc else 'no document: stays in Draft'}  | {a.desc}")
    if a.dry_run:
        return
    me = o.call("refund_request_wizard", "default_get", fields=["network_member"])["network_member"]
    vals = {"network_member": me, "document_date": day.isoformat(), "gross_total": a.amount,
            "cost_center": cc["id"], "approver": ap["id"], "payment_bank_account_type": a.account,
            "expense_description": a.desc}
    if doc:
        vals.update(file_name=doc[0], file=doc[1])
    last = o.call("refund_request", "search_read", domain=[["network_member_user_id", "=", o.uid]],
                  fields=["id"], order="id desc", limit=1)
    [wiz] = o.call("refund_request_wizard", "create", vals_list=[vals])
    o.call("refund_request_wizard", "action_submit", ids=[wiz])
    new = o.call("refund_request", "search_read",
                 domain=[["network_member_user_id", "=", o.uid], ["id", ">", last[0]["id"] if last else 0]],
                 fields=REFUND_FIELDS, order="id desc")
    if not new:
        sys.exit("submitted, but no new request shows up; check Refund Requests in Odoo")
    print("created:"); print_refunds(new)


def cmd_refund_file(o: Odoo, a) -> None:
    [r] = o.call("refund_request", "read", ids=[a.id], fields=REFUND_FIELDS)
    if r["state"] not in ("draft", "refused"):
        sys.exit(f"{r['reference']} is {r['state']}; the document can only change in draft or refused")
    name, data = read_doc(a.path)
    print("before:"); print_refunds([r])
    if a.dry_run:
        print(f"DRY RUN would attach {name}"); return
    o.call("refund_request", "write", ids=[a.id], values={"file_name": name, "file": data})  # `values`, as above
    print("after:"); print_refunds(o.call("refund_request", "read", ids=[a.id], fields=REFUND_FIELDS))


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("contracts"); s.add_argument("--date", help="active on this day (default today)")
    s.set_defaults(fn=cmd_contracts)

    s = sub.add_parser("list"); s.add_argument("--from", dest="frm"); s.add_argument("--to")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("month"); s.add_argument("--month", help="YYYY-MM (default current)")
    s.set_defaults(fn=cmd_month)

    s = sub.add_parser("add")
    s.add_argument("--contract", required=True, help="id or substring of account/project/role")
    s.add_argument("--date", default="today", help="YYYY-MM-DD, today, yesterday")
    s.add_argument("--start", required=True, help="HH:MM local time")
    s.add_argument("--end", help="HH:MM local time")
    s.add_argument("--hours", type=float, help="duration instead of --end")
    s.add_argument("--desc", required=True, help="work description")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="log even if it overlaps an existing entry")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("update"); s.add_argument("id", type=int)
    s.add_argument("--desc"); s.add_argument("--contract"); s.add_argument("--start"); s.add_argument("--end")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("delete"); s.add_argument("ids", type=int, nargs="+")
    s.set_defaults(fn=cmd_delete)

    s = sub.add_parser("refunds"); s.add_argument("--from", dest="frm"); s.add_argument("--to")
    s.set_defaults(fn=cmd_refunds)

    s = sub.add_parser("refund-options"); s.add_argument("--search", help="filter cost centers by name or account")
    s.set_defaults(fn=cmd_refund_options)

    s = sub.add_parser("refund")
    s.add_argument("--date", required=True, help="the receipt's date: YYYY-MM-DD, today, yesterday")
    s.add_argument("--amount", required=True, type=float, help="total to pay back, VAT included")
    s.add_argument("--cost-center", required=True, help="id or substring of the cost center (a project)")
    s.add_argument("--approver", required=True, help="id or substring of the approver's name")
    s.add_argument("--desc", required=True, help="what the expense was")
    s.add_argument("--file", help="the receipt (.pdf, .jpg, .jpeg, .png); without it the request stays in Draft")
    s.add_argument("--account", choices=["personal", "company"], default="personal", help="bank account to pay into")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_refund)

    s = sub.add_parser("refund-file"); s.add_argument("id", type=int); s.add_argument("path")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_refund_file)

    a = p.parse_args(argv)
    try:
        a.fn(Odoo(), a)
    except OdooError as e:
        sys.exit(f"Odoo error: {e}")
    except OSError as e:
        sys.exit(f"cannot reach {URL}: {e}")


if __name__ == "__main__":
    main()
