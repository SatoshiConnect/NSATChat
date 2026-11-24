"""Audit NSAT settlement against the chain and report gaps to admins.

The settling command moves submitted transfers forward; this pass checks the
books themselves. Run it after settling (hourly is enough), and use
``--fail-on-issues`` from cron so a disagreement pages instead of waiting to be
noticed by a buyer who could not open what they paid for.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.marketplace.models import MarketplaceReconciliationRun
from apps.marketplace.reconciliation import run_reconciliation


class Command(BaseCommand):
    help = "Reconcile confirmed NSAT transfers with marketplace orders, entitlements and sales."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500, help="Maximum rows to audit per check.")
        parser.add_argument("--dry-run", action="store_true", help="Report only; repair nothing.")
        parser.add_argument("--skip-chain-check", action="store_true", help="Audit the ledger without calling the indexer.")
        parser.add_argument(
            "--fail-on-issues",
            action="store_true",
            help="Exit non-zero when the pass finds any issue, for cron alerting.",
        )

    def handle(self, *args, **options):
        run = run_reconciliation(
            source=MarketplaceReconciliationRun.Source.COMMAND,
            dry_run=options["dry_run"],
            limit=options["limit"],
            check_chain=not options["skip_chain_check"],
        )
        self.stdout.write(run.summary)
        issues = run.issues.order_by("severity", "code", "created_at")[:50]
        for issue in issues:
            marker = "repaired" if issue.repaired else issue.severity
            self.stdout.write(
                f"  [{marker}] {issue.code} order={issue.order_reference or '-'} {issue.detail}".rstrip()
            )
        if run.issues_found > issues.count():
            self.stdout.write(f"  … {run.issues_found - issues.count()} more issue(s); see admin for run {run.pk}.")
        if options["fail_on_issues"] and run.issues_found:
            raise CommandError(f"{run.issues_found} reconciliation issue(s) found in run {run.pk}.")
