from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AerotecApprovalRule(models.Model):
    _name = "aerotec.approval.rule"
    _description = "Regla de Autorización de Compras"
    _order = "company_id, min_amount asc, max_amount asc"

    name = fields.Char(
        string="Nombre",
        compute="_compute_name",
        store=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    user_ids = fields.Many2many(
        "res.users",
        "aerotec_approval_rule_users_rel",
        "rule_id",
        "user_id",
        string="Usuarios autorizadores",
        domain=[("share", "=", False)],
    )
    approval_type = fields.Selection(
        [
            ("invoice", "Facturas de proveedor"),
            ("payment", "Pagos a proveedores"),
            ("both", "Facturas y pagos"),
        ],
        string="Aplica a",
        required=True,
        default="both",
    )
    min_amount = fields.Monetary(
        string="Monto mínimo a autorizar",
        default=0.0,
        currency_field="currency_id",
        help=(
            "Límite inferior del rango que cubre esta regla (en la moneda del tope). "
            "La regla aplica a comprobantes cuyo monto sea mayor o igual a este valor "
            "y menor o igual al monto máximo."
        ),
    )
    max_amount = fields.Monetary(
        string="Monto máximo a autorizar",
        required=True,
        currency_field="currency_id",
        help=(
            "Límite superior del rango que cubre esta regla (en la moneda del tope). "
            "Cualquiera de los usuarios autorizadores puede aprobar comprobantes cuyo monto "
            "esté dentro del rango [mínimo, máximo]. Los comprobantes que queden fuera de "
            "todos los rangos configurados no podrán confirmarse."
        ),
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda del tope",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    active = fields.Boolean(default=True)

    @api.depends("user_ids", "min_amount", "max_amount", "currency_id", "approval_type")
    def _compute_name(self):
        type_labels = {
            "invoice": "Facturas",
            "payment": "Pagos",
            "both": "Facturas y pagos",
        }
        for rec in self:
            label = type_labels.get(rec.approval_type, "")
            min_str = f"{rec.min_amount:,.2f}" if rec.min_amount else "0,00"
            max_str = f"{rec.max_amount:,.2f}" if rec.max_amount else "0,00"
            names = rec.user_ids.mapped("name")
            if not names:
                users_str = "Sin usuarios"
            elif len(names) <= 2:
                users_str = ", ".join(names)
            else:
                users_str = f"{names[0]}, {names[1]} y {len(names) - 2} más"
            rec.name = (
                f"{users_str} — "
                f"{rec.currency_id.name or ''} {min_str} – {max_str} ({label})"
            )

    @api.constrains("user_ids")
    def _check_user_ids(self):
        for rec in self:
            if not rec.user_ids:
                raise ValidationError(
                    _("Debe configurar al menos un usuario autorizador en la regla.")
                )

    @api.constrains("min_amount", "max_amount")
    def _check_amounts(self):
        for rec in self:
            if rec.max_amount <= 0:
                raise ValidationError(
                    _("El monto máximo a autorizar debe ser mayor a cero.")
                )
            if rec.min_amount < 0:
                raise ValidationError(
                    _("El monto mínimo a autorizar no puede ser negativo.")
                )
            if rec.min_amount >= rec.max_amount:
                raise ValidationError(
                    _(
                        "El monto mínimo (%(min)s) debe ser menor que el monto máximo (%(max)s).",
                        min=f"{rec.min_amount:,.2f}",
                        max=f"{rec.max_amount:,.2f}",
                    )
                )

    @api.model
    def _evaluate_for_document(self, amount, currency, company, doc_type):
        """Evalúa un comprobante contra las reglas de autorización.

        Devuelve un dict con:
        - ``status``: ``'free'`` (no requiere aprobación), ``'required'`` (requiere
          aprobación) o ``'blocked'`` (queda fuera de todos los rangos configurados y
          no hay usuario habilitado para autorizarlo).
        - ``rules``: recordset de todas las reglas cuyo rango contiene el monto (vacío
          salvo en ``'required'``). Los rangos pueden solaparse.
        - ``users``: unión de los usuarios autorizadores de esas reglas.
        """
        today = fields.Date.context_today(self)
        rules = self.sudo().search(
            [
                ("company_id", "=", company.id),
                ("approval_type", "in", [doc_type, "both"]),
                ("active", "=", True),
            ],
            order="min_amount asc, max_amount asc",
        )
        empty_rules = self.browse()
        empty_users = self.env["res.users"].browse()
        if not rules:
            return {"status": "free", "rules": empty_rules, "users": empty_users}
        matching = empty_rules
        below_all_minimums = True
        for rule in rules:
            converted = currency._convert(
                amount, rule.currency_id, company, today
            ) if currency else amount
            if rule.min_amount <= converted <= rule.max_amount:
                matching |= rule
            if converted >= rule.min_amount:
                below_all_minimums = False
        if matching:
            return {"status": "required", "rules": matching, "users": matching.user_ids}
        return {
            "status": "free" if below_all_minimums else "blocked",
            "rules": empty_rules,
            "users": empty_users,
        }
