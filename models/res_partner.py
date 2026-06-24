from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    aerotec_supplier_product_ids = fields.One2many(
        "aerotec.supplier.product",
        "partner_id",
        string="Productos autorizados por empresa",
    )
