def migrate(cr, version):
    """Migra los user_id existentes en aerotec_approval_rule a la nueva tabla M2M."""
    cr.execute("""
        INSERT INTO aerotec_approval_rule_users_rel (rule_id, user_id)
        SELECT id, user_id
        FROM aerotec_approval_rule
        WHERE user_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
