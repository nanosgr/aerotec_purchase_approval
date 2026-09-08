def migrate(cr, version):
    """El campo `approval_rule_id` (Many2one) pasa a `approval_rule_ids` (Many2many).

    Se descartan las columnas viejas de `account_move` / `account_payment`; Odoo recomputa
    `approval_rule_ids` al actualizar el módulo. No hay constraint de BD que quitar: la
    restricción de solapamiento eliminada era solo `@api.constrains` de Python.
    """
    for table in ("account_move", "account_payment"):
        cr.execute("ALTER TABLE %s DROP COLUMN IF EXISTS approval_rule_id" % table)
