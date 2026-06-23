from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    product_id_domain = fields.Binary(
        compute="_compute_product_id_domain",
        store=False,
        help="Dominio calculado para filtrar productos según los habilitados por el proveedor.",
    )

    @api.depends("order_id.partner_id", "order_id.partner_id.supplier_product_ids")
    def _compute_product_id_domain(self):
        for line in self:
            partner = line.order_id.partner_id
            if partner and partner.supplier_product_ids:
                line.product_id_domain = [
                    ("product_tmpl_id", "in", partner.supplier_product_ids.ids)
                ]
            else:
                line.product_id_domain = []
