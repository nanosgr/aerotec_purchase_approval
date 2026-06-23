from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AerotecApprovalRule(models.Model):
    _name = "aerotec.approval.rule"
    _description = "Regla de Autorización de Compras"
    _order = "company_id, max_amount asc"

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
    user_id = fields.Many2one(
        "res.users",
        string="Usuario autorizador",
        required=True,
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
    max_amount = fields.Monetary(
        string="Monto máximo a autorizar",
        required=True,
        currency_field="currency_id",
        help=(
            "Este usuario puede autorizar comprobantes cuyo monto sea menor o igual a este valor. "
            "Para montos mayores se necesita un usuario con límite superior."
        ),
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda del tope",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    active = fields.Boolean(default=True)

    @api.depends("user_id", "max_amount", "currency_id", "approval_type")
    def _compute_name(self):
        type_labels = {
            "invoice": "Facturas",
            "payment": "Pagos",
            "both": "Facturas y pagos",
        }
        for rec in self:
            label = type_labels.get(rec.approval_type, "")
            amount_str = f"{rec.max_amount:,.2f}" if rec.max_amount else "0,00"
            rec.name = (
                f"{rec.user_id.name or 'Sin usuario'} — "
                f"{rec.currency_id.name or ''} {amount_str} ({label})"
            )

    @api.constrains("max_amount")
    def _check_max_amount(self):
        for rec in self:
            if rec.max_amount <= 0:
                raise ValidationError(
                    _("El monto máximo a autorizar debe ser mayor a cero.")
                )

    @api.model
    def _find_for_document(self, amount, currency, company, doc_type):
        """Encuentra la regla con menor tope suficiente para cubrir el monto dado."""
        today = fields.Date.context_today(self)
        rules = self.sudo().search(
            [
                ("company_id", "=", company.id),
                ("approval_type", "in", [doc_type, "both"]),
                ("active", "=", True),
            ],
            order="max_amount asc",
        )
        for rule in rules:
            converted = currency._convert(
                amount,
                rule.currency_id,
                company,
                today,
            )
            if rule.max_amount >= converted:
                return rule
        return self.browse()
