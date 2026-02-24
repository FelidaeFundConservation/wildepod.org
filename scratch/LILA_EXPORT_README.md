# LILA Image Export

Optimized export of LILA images using monthly batching to avoid PostgreSQL query planner performance cliffs.

## Problem

Exporting large date ranges (7+ months) in a single query hits a performance cliff where the hash join batching degrades exponentially:
- 6 months: ~2.4 seconds
- 7 months: >2 minutes (or timeout)
- 3 years: Would take 20+ minutes

The issue is that the 782K row `images_species` table doesn't fit in `work_mem`, causing disk spilling that gets worse with more filtered data.

## Solution

Monthly batching keeps each query under the performance cliff:
- Each month: 1-2 seconds
- Parallel execution: 3-4x speedup
- **Total for 3 years: ~15-20 seconds**

## Usage

### Basic Export

```bash
# Export all images (defaults: 2020-01-01 to 2025-12-31)
uv run manage.py export_lila --drop-table

# Export 3 years of data with default settings
uv run manage.py export_lila --start 2022-01-01 --end 2024-12-31

# Export single year
uv run manage.py export_lila --start 2023-01-01 --end 2023-12-31
```

### Advanced Options

```bash
# Drop and recreate table before export
uv run manage.py export_lila --start 2022-01-01 --end 2024-12-31 --drop-table

# Adjust worker count (1-10)
uv run manage.py export_lila --start 2022-01-01 --end 2024-12-31 --workers 4

# Use custom table name
uv run manage.py export_lila --start 2022-01-01 --end 2024-12-31 --table my_export

# Export from default start (2020-01-01) to specific end date
uv run manage.py export_lila --end 2023-12-31

# Export from specific start date to default end (2025-12-31)
uv run manage.py export_lila --start 2022-01-01
```

## Data Quality Filters

The export only includes bounding boxes that meet these criteria:

1. **Image filters**:
   - `has_wild_animals = true`
   - `species_pipeline_complete = true`
   - Has valid `trigger_timestamp` within date range

2. **Vote confidence thresholds**:
   - **Category votes ≥ 2**: Sum of (created + accepted - rejected) votes
   - **Species votes ≥ 2**: Sum of (created + accepted - rejected) votes
   - Expert/staff votes weighted 5x, regular annotators 1x

This ensures only high-confidence annotations are exported for LILA.

## Output Table

Data is exported to `lila_export` table (or custom table name) with these columns:

- `id` - Serial primary key
- `image_id` - UUID of the image
- `bbox_id` - UUID of the bounding box
- `dropbox_content_hash` - Dropbox content hash
- `dropbox_file_name` - File name
- `thumbnail_gcloud_path` - GCloud thumbnail path
- `dropbox_file_path` - Full dropbox path
- `trigger_timestamp` - Camera trigger timestamp
- `dropbox_folder_path` - Folder path
- `category_name` - Highest voted category (votes ≥ 2)
- `category_votes` - Vote sum for category (created + accepted - rejected)
- `species_name` - Highest voted species (votes ≥ 2)
- `species_votes` - Vote sum for species (created + accepted - rejected)
- `created_at` - Export timestamp

Indexes are automatically created on:
- `image_id`
- `bbox_id`
- `trigger_timestamp`
- `species_name`

## Query Results To CSV

If you need CSV output, export from the table:

```bash
# Using psql
psql -c "\COPY (SELECT * FROM lila_export ORDER BY trigger_timestamp) TO 'lila_export.csv' CSV HEADER"

# Or using Django
python manage.py dbshell
\COPY lila_export TO 'lila_export.csv' CSV HEADER;
```

## Performance

### Expected Timings

- Single month: 1-2 seconds
- 3 years (36 months) sequential: ~36 seconds
- 3 years with 3 workers: ~15 seconds
- 3 years with 4 workers: ~12 seconds

### Monitoring

The command shows real-time progress:

```
[2022-01] ✓ 3,245 rows in 1.2s
[2022-02] ✓ 2,987 rows in 1.1s
[2022-03] ✓ 4,123 rows in 1.5s
...
```

## Files

- `scratch/export_lila_query.sql` - Optimized SQL query template
- `siteapps/images/management/commands/export_lila.py` - Django management command
- `scratch/export_lila_images_optimized.sql` - Development/testing query with EXPLAIN

## Optimization Details

The query uses several optimizations:

1. **Filter First**: Narrow to date range before any joins
2. **Partial Index**: `idx_image_wild_complete_timestamp` on filtered columns
3. **Vote Aggregation**: Only processes votes for filtered bounding boxes
4. **DISTINCT ON**: PostgreSQL-specific optimization for "top-voted" logic
5. **Vote Threshold**: Only exports records with category_votes ≥ 2 AND species_votes ≥ 2

## Troubleshooting

### Connection Pool Exhaustion

If you see connection errors, reduce `--workers`:

```bash
uv run manage.py export_lila --start 2022-01-01 --end 2024-12-31 --workers 2
```

### Slow Individual Batches

If a single batch takes >5 seconds, check:

```sql
-- Are the indices present?
SELECT indexname FROM pg_indexes WHERE tablename = 'images_image';

-- Is the partial index being used?
EXPLAIN SELECT id FROM images_image
WHERE has_wild_animals AND species_pipeline_complete
AND trigger_timestamp BETWEEN '2023-01-01' AND '2023-01-31';
```

Should see: `Index Scan using idx_image_wild_complete_timestamp`

### Memory Issues

Increase PostgreSQL's `work_mem` for better hash join performance:

```sql
-- In postgresql.conf or at session level
SET work_mem = '256MB';
```

## Related Files

- `scratch/export_lila_images.sql` - Original slow query (before optimization)
- `scratch/critical_missing_index.sql` - Index creation for the partial index
- `scratch/existing_indices.csv` - Current index inventory
