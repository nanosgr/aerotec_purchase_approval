from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AerotecApprovalRequestWizard(models.TransientModel):
    _name = "aerotec.approval.request.wizard"
    _description = "Solicitud de autorización de compra"

    move_id = fields.Many2one("account.move", string="Factura", ondelete="cascade")
    payment_id = fields.Many2one("account.payment", string="Pago", ondelete="cascade")

    rule_id = fields.Many2one(
        "aerotec.approval.rule",
        string="Regla aplicable",
        compute="_compute_source_info",
        readonly=True,
    )
    available_approver_ids = fields.Many2many(
        "res.users",
        string="Autorizadores habilitados",
        compute="_compute_source_info",
        readonly=True,
    )
    document_label = fields.Char(
        string="Comprobante",
        compute="_compute_source_info",
        readonly=True,
    )
    amount_label = fields.Char(
        string="Importe a autorizar",
        compute="_compute_source_info",
        readonly=True,
    )
    approver_id = fields.Many2one(
        "res.users",
        string="Autorizador asignado",
        required=True,
        help="Usuario que deberá aprobar o rechazar este comprobante.",
    )
    note = fields.Text(string="Nota para el autorizador")

    @api.depends("move_id", "payment_id")
    def _compute_source_info(self):
        for wiz in self:
            record = wiz._get_record()
            wiz.rule_id = record.approval_rule_id if record else False
            wiz.available_approver_ids = record.approval_rule_id.user_ids if record else False
            if not record:
                wiz.document_label = False
                wiz.amount_label = False
            elif wiz.move_id:
                wiz.document_label = _(
                    "Factura %(ref)s — %(partner)s",
                    ref=record.name or record.ref or _("borrador"),
                    partner=record.partner_id.name or "",
                )
                wiz.amount_label = f"{record.currency_id.name or ''} {record.amount_total:,.2f}"
            else:
                wiz.document_label = _(
                    "Pago a %(partner)s", partner=record.partner_id.name or ""
                )
                wiz.amount_label = f"{record.currency_id.name or ''} {record.amount:,.2f}"

    def _get_record(self):
        self.ensure_one()
        return self.move_id or self.payment_id

    def action_confirm(self):
        self.ensure_one()
        record = self._get_record()
        if not record:
            raise UserError(_("No se encontró el comprobante a autorizar."))
        record._do_request_approval(self.approver_id, self.note)
        return {"type": "ir.actions.act_window_close"}
