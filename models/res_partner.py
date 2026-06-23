from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    supplier_product_ids = fields.Many2many(
        "product.template",
        "res_partner_supplier_product_rel",
        "partner_id",
        "product_id",
        string="Productos autorizados",
        help=(
            "Productos que este proveedor está habilitado para suministrar. "
            "Si la lista está vacía se permiten todos los productos en las órdenes de compra."
        ),
    )
