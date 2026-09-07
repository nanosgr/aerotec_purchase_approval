def migrate(cr, version):
    """Agrega la columna min_amount a las reglas existentes con valor 0."""
    cr.execute("""
        ALTER TABLE aerotec_approval_rule
        ADD COLUMN IF NOT EXISTS min_amount numeric
    """)
    cr.execute("""
        UPDATE aerotec_approval_rule
        SET min_amount = 0
        WHERE min_amount IS NULL
    """)
