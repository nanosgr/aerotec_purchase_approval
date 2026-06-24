from odoo import fields, models


class AerotecSupplierProduct(models.Model):
    _name = "aerotec.supplier.product"
    _description = "Productos relacionados por proveedor"
    _rec_name = "partner_id"

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        domain=[("supplier_rank", ">", 0)],
        string="Proveedor",
    )
    product_ids = fields.Many2many(
        "product.template",
        string="Productos relacionados",
    )

    _sql_constraints = [
        (
            "unique_partner",
            "UNIQUE(partner_id)",
            "Ya existe una configuración de productos para este proveedor.",
        ),
    ]
