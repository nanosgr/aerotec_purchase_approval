from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    product_id_domain = fields.Binary(
        compute="_compute_product_id_domain",
        store=False,
    )

    @api.depends("move_id.partner_id", "move_id.move_type")
    def _compute_product_id_domain(self):
        SupplierProduct = self.env["aerotec.supplier.product"].sudo()
        partner_domain_cache = {}
        for line in self:
            if (
                line.move_id.move_type != "in_invoice"
                or not line.move_id.partner_id
            ):
                line.product_id_domain = []
                continue
            partner_id = line.move_id.partner_id.id
            if partner_id not in partner_domain_cache:
                config = SupplierProduct.search(
                    [("partner_id", "=", partner_id)],
                    limit=1,
                )
                if config and config.product_ids:
                    partner_domain_cache[partner_id] = [
                        ("product_tmpl_id", "in", config.product_ids.ids)
                    ]
                else:
                    partner_domain_cache[partner_id] = []
            line.product_id_domain = partner_domain_cache[partner_id]
