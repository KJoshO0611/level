"""
Migration 010: Template Migration

This is a template for creating new migrations. 
Copy this file and rename it using the format: NNN_description.py where NNN is a sequential number.
Then modify the SQL in APPLY_SQL and REVERT_SQL to implement your changes.

Recommended migration naming:
- 001-099: Core schema changes (tables, columns, indexes)
- 100-199: Data migrations (populating new columns, fixing data)
- 200-299: Function/procedure changes
- 300+: Other changes

Guidelines:
1. Always include BOTH apply and revert SQL
2. Check if objects exist before creating/altering them
3. Make SQL idempotent (can be run multiple times safely)
4. Keep migrations focused (one change per migration)
5. Don't assume database state beyond previous migrations
"""

# The SQL to apply the migration - this is what gets executed when migrations run
APPLY_SQL = """
-- Example: Add a new column to a table if it doesn't exist
DO $$
BEGIN
    -- First check if the column already exists
    IF NOT EXISTS (
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'your_table_name' AND column_name = 'your_new_column'
    ) THEN
        -- Add the column if it doesn't exist
        ALTER TABLE your_table_name ADD COLUMN your_new_column TEXT;
        RAISE NOTICE 'Added your_new_column to your_table_name table';
    ELSE
        RAISE NOTICE 'your_new_column already exists in your_table_name table';
    END IF;
END $$;

-- You can also run multiple statements, create indexes, etc.
-- CREATE INDEX IF NOT EXISTS idx_your_table_your_column ON your_table_name(your_new_column);
"""

# The SQL to revert the migration - this is executed if you need to roll back
REVERT_SQL = """
-- Example: Remove the column added in the APPLY_SQL
DO $$
BEGIN
    -- First check if the column exists
    IF EXISTS (
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'your_table_name' AND column_name = 'your_new_column'
    ) THEN
        -- Drop the column if it exists
        ALTER TABLE your_table_name DROP COLUMN your_new_column;
        RAISE NOTICE 'Removed your_new_column from your_table_name table';
    ELSE
        RAISE NOTICE 'your_new_column does not exist in your_table_name table';
    END IF;
END $$;

-- Don't forget to remove any indexes or constraints you added
-- DROP INDEX IF EXISTS idx_your_table_your_column;
"""

# Don't modify below this line - the migration system expects these variables
if __name__ == "__main__":
    print("This is a migration file and should not be executed directly.")
    print("To apply migrations, use the database_migration.py script.")
    print(f"To apply this specific migration: python -m utils.database_migration specific {__name__.split('.')[-1]}") 