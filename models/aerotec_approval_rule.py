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

    @api.constrains("min_amount", "max_amount", "currency_id", "company_id", "approval_type", "active")
    def _check_no_overlap(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.active:
                continue
            scope = ["both"] if rec.approval_type == "both" else [rec.approval_type, "both"]
            others = self.sudo().search(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("active", "=", True),
                    ("approval_type", "in", scope),
                ]
            )
            company = rec.company_id
            rec_min = rec.min_amount
            rec_max = rec.max_amount
            for other in others:
                # Convertir el rango de la otra regla a la moneda de esta regla.
                other_min = other.currency_id._convert(
                    other.min_amount, rec.currency_id, company, today
                ) if other.min_amount else 0.0
                other_max = other.currency_id._convert(
                    other.max_amount, rec.currency_id, company, today
                )
                if rec_min < other_max and other_min < rec_max:
                    raise ValidationError(
                        _(
                            "El rango de esta regla se solapa con la regla '%(other)s'. "
                            "Ajuste los montos para que los rangos no se superpongan.",
                            other=other.name or "",
                        )
                    )

    @api.model
    def _evaluate_for_document(self, amount, currency, company, doc_type):
        """Evalúa un comprobante contra las reglas de autorización.

        Devuelve un dict con:
        - ``status``: ``'free'`` (no requiere aprobación), ``'required'`` (requiere
          aprobación según ``rule``) o ``'blocked'`` (queda fuera de todos los rangos
          configurados y no hay usuario habilitado para autorizarlo).
        - ``rule``: el recordset de la regla aplicable (vacío salvo en ``'required'``).
        """
        today = fields.Date.context_today(self)
        rules = self.sudo().search(
            [
                ("company_id", "=", company.id),
                ("approval_type", "in", [doc_type, "both"]),
                ("active", "=", True),
            ],
            order="max_amount asc",
        )
        if not rules:
            return {"status": "free", "rule": self.browse()}
        below_all_minimums = True
        for rule in rules:
            converted = currency._convert(
                amount, rule.currency_id, company, today
            ) if currency else amount
            if rule.min_amount <= converted <= rule.max_amount:
                return {"status": "required", "rule": rule}
            if converted >= rule.min_amount:
                below_all_minimums = False
        return {
            "status": "free" if below_all_minimums else "blocked",
            "rule": self.browse(),
        }
