"""
Django management command to monitor LILA download progress.

Queries the database every 5 minutes to check how many files have downloaded_location set,
and estimates time to completion based on the download rate.

Usage:
    # Monitor lila_export_5 (default)
    uv run manage.py monitor_lila_download --settings=config.settings.prod

    # Monitor a different table
    uv run manage.py monitor_lila_download --table lila_export_4 --settings=config.settings.prod

    # Customize interval (in seconds)
    uv run manage.py monitor_lila_download --interval 60 --settings=config.settings.prod
"""

import time
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Monitor LILA download progress and estimate completion time"

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            type=str,
            default="lila_export_5",
            help="Table name to monitor (default: lila_export_5)",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=300,  # 5 minutes
            help="Check interval in seconds (default: 300 = 5 minutes)",
        )

    def handle(self, *args, **options):
        table_name = options["table"]
        interval_seconds = options["interval"]

        # Verify we're not using SQLite
        db_engine = connection.settings_dict["ENGINE"]
        if "sqlite" in db_engine:
            raise CommandError(
                "This command requires PostgreSQL. "
                "Run with: --settings=config.settings.staging or --settings=config.settings.prod"
            )

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS(f"LILA Download Monitor - {table_name}"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Checking every {interval_seconds} seconds. Press Ctrl+C to stop.")
        self.stdout.write("")

        history = []  # List of (timestamp, downloaded_count) tuples

        try:
            while True:
                now = datetime.now()
                total, downloaded = self._get_download_stats(table_name)
                remaining = total - downloaded
                progress_pct = (downloaded / total * 100) if total > 0 else 0

                history.append((now, downloaded))

                # Keep only last hour of history
                cutoff = now - timedelta(hours=1)
                history = [(t, d) for t, d in history if t > cutoff]

                # Calculate rate and ETA (need at least 2 data points)
                rate_str = "Calculating..."
                eta_str = "Calculating..."

                if len(history) >= 2:
                    first_time, first_count = history[0]
                    elapsed_seconds = (now - first_time).total_seconds()

                    if elapsed_seconds > 0:
                        images_downloaded = downloaded - first_count
                        rate = images_downloaded / elapsed_seconds  # images per second

                        if rate > 0:
                            rate_str = f"{rate * 60:.1f}/min ({rate * 3600:.0f}/hour)"
                            eta_seconds = remaining / rate
                            eta_str = self._format_duration(eta_seconds)
                            eta_time = now + timedelta(seconds=eta_seconds)
                            eta_str += f" (finish ~{eta_time.strftime('%Y-%m-%d %H:%M')})"
                        else:
                            rate_str = "0/min (stalled)"
                            eta_str = "Unknown (no progress)"

                # Print status
                self.stdout.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}]")
                self.stdout.write(f"  Progress: {downloaded:,} / {total:,} ({progress_pct:.1f}%)")
                self.stdout.write(f"  Remaining: {remaining:,}")
                self.stdout.write(f"  Rate: {rate_str}")
                self.stdout.write(f"  ETA: {eta_str}")
                self.stdout.write("")

                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped.")

    def _get_download_stats(self, table_name):
        """Get download statistics from the table."""
        with connection.cursor() as cursor:
            # Total unique images (by image_id)
            cursor.execute(f"""
                SELECT COUNT(DISTINCT image_id)
                FROM {table_name}
                WHERE dropbox_content_hash IS NOT NULL
            """)
            total = cursor.fetchone()[0]

            # Downloaded images (where downloaded_location is not null)
            cursor.execute(f"""
                SELECT COUNT(DISTINCT image_id)
                FROM {table_name}
                WHERE downloaded_location IS NOT NULL
            """)
            downloaded = cursor.fetchone()[0]

        return total, downloaded

    def _format_duration(self, seconds):
        """Format seconds into human-readable duration."""
        if seconds < 0:
            return "N/A"
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        elif seconds < 86400:
            hours = seconds / 3600
            return f"{hours:.1f}h"
        else:
            days = seconds / 86400
            hours = (seconds % 86400) / 3600
            return f"{days:.0f}d {hours:.1f}h"
