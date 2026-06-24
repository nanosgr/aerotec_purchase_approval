from odoo import fields, models


class AerotecSupplierProduct(models.Model):
    _name = "aerotec.supplier.product"
    _description = "Productos autorizados por proveedor"
    _rec_name = "partner_id"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        domain=[("supplier_rank", ">", 0)],
        string="Proveedor",
    )
    product_ids = fields.Many2many(
        "product.template",
        string="Productos autorizados",
    )

    _sql_constraints = [
        (
            "unique_partner_company",
            "UNIQUE(partner_id, company_id)",
            "Ya existe una configuración de productos para este proveedor en esta empresa.",
        ),
    ]
