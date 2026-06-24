from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    product_auth_warning = fields.Char(
        compute="_compute_product_auth_warning",
        string="Autorización producto",
    )

    @api.depends(
        "product_id",
        "move_id.partner_id",
        "move_id.move_type",
    )
    def _compute_product_auth_warning(self):
        SupplierProduct = self.env["aerotec.supplier.product"].sudo()
        config_cache = {}
        for line in self:
            line.product_auth_warning = False
            if (
                line.move_id.move_type != "in_invoice"
                or not line.product_id
                or not line.move_id.partner_id
            ):
                continue
            key = line.move_id.partner_id.id
            if key not in config_cache:
                config = SupplierProduct.search(
                    [("partner_id", "=", key)],
                    limit=1,
                )
                config_cache[key] = config.product_ids if config else None
            authorized = config_cache[key]
            if authorized is not None and line.product_id.product_tmpl_id not in authorized:
                line.product_auth_warning = "Producto no autorizado para este proveedor"
